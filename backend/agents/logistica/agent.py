import json
import logging
import re
from typing import Dict, Any, List, Tuple, Optional

from backend.config import settings
from backend.models import ToolExecution, ChatResponse
from backend.agents._shared.loader import mcp_client
from backend.agents.logistica.prompts import SYSTEM_INSTRUCTION_LOGISTICA

logger = logging.getLogger("backend.agent_logistica")

class LogisticaAgent:
    """
    Agente Logístico de Tottus basado en Gemini 2.5 Flash y el catálogo de Toolbox MCP.
    Orquesta el ciclo de razonamiento, Function Calling hacia BigQuery y generación ejecutiva.
    """

    def __init__(self):
        self._genai_client = None

    def _get_client(self):
        """Inicializa el cliente de Google GenAI (Vertex AI o API Key)."""
        if self._genai_client is not None:
            return self._genai_client

        try:
            from google import genai
            if settings.GEMINI_API_KEY:
                logger.info("🔑 Inicializando Gemini con API Key directa...")
                self._genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            elif settings.USE_VERTEXAI:
                logger.info(f"☁️ Inicializando Gemini vía Vertex AI en proyecto '{settings.VERTEXAI_PROJECT}'...")
                self._genai_client = genai.Client(
                    vertexai=True,
                    project=settings.VERTEXAI_PROJECT,
                    location=settings.GOOGLE_CLOUD_LOCATION
                )
            else:
                self._genai_client = genai.Client()
            return self._genai_client
        except Exception as e:
            logger.error(f"Error al inicializar cliente de GenAI: {e}")
            return None

    def _build_tools_declaration(self) -> list:
        """Construye las declaraciones de funciones (OpenAPI/MCP) para Gemini."""
        from google.genai import types

        function_declarations = [
            types.FunctionDeclaration(
                name="consultar_despachos_logistica",
                description="Consulta el detalle de despachos y transferencias en tránsito desde el CD hacia las tiendas (TIM, SKU, Descripción, Tienda, Fecha de Envío).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM logístico (ej. 655425244)."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de la tienda (ej. '123', '114')."),
                        "sku": types.Schema(type=types.Type.STRING, description="Código SKU puntual."),
                        "pagina": types.Schema(type=types.Type.INTEGER, description="Número de página (1 por defecto).")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="resumen_carga_transporte",
                description="Consolida los bultos, cajas, unidades, peso total en kg y volumen cargado en un camión (por TIM o por Placa).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del vehículo de transporte.")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="resumen_despachos_por_division",
                description="Devuelve el total de unidades y cajas despachadas a una tienda agrupadas por división comercial (J01 a J11).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de tienda destino (ej. '123')."),
                        "dias_atras": types.Schema(type=types.Type.INTEGER, description="Días hacia atrás a consultar (por defecto 7).")
                    },
                    required=["tienda"]
                )
            ),
            types.FunctionDeclaration(
                name="alertas_vencimiento_transito",
                description="Identifica productos en tránsito hacia una tienda cuya fecha de vencimiento esté próxima dentro de los próximos N días.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de tienda destino (ej. '123')."),
                        "dias_margen": types.Schema(type=types.Type.INTEGER, description="Días máximos antes del vencimiento (por defecto 15).")
                    },
                    required=["tienda"]
                )
            )
        ]

        return [types.Tool(function_declarations=function_declarations)]

    async def _execute_mcp_tool(self, tool_name: str, arguments: dict) -> Tuple[List[Dict[str, Any]], ToolExecution]:
        """Ejecuta la herramienta seleccionada a través de Toolbox MCP."""
        fetch_all = (tool_name == "consultar_despachos_logistica" and "pagina" not in arguments)
        rows = await mcp_client.call_tool(tool_name, arguments, fetch_all_pages=fetch_all)

        execution_record = ToolExecution(
            tool_name=tool_name,
            arguments=arguments,
            result_count=len(rows),
            preview=rows[:3] if rows else []
        )
        return rows, execution_record

    async def run(self, user_prompt: str, session_id: str = "default_session", tienda_id: Optional[str] = None) -> ChatResponse:
        """
        Flujo principal del agente:
        1. Recibe la consulta en lenguaje natural.
        2. Gemini analiza la pregunta e invoca la herramienta MCP adecuada (Function Calling).
        3. Se ejecutan los datos en BigQuery a través de Toolbox.
        4. Gemini sintetiza la respuesta ejecutiva.
        5. Retorna la respuesta con el texto y las filas estructuradas para el frontend.
        """
        client = self._get_client()
        tools_executed: List[ToolExecution] = []
        raw_data: List[Dict[str, Any]] = []

        # Si no hay cliente de IA configurado aún, aplicamos fallback heurístico inteligente
        if not client:
            return await self._fallback_deterministic_execution(user_prompt, session_id)

        try:
            from google.genai import types

            tools = self._build_tools_declaration()
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION_LOGISTICA,
                tools=tools,
                temperature=0.0  # Respuesta rápida y determinista
            )

            # Turno 1: Gemini evalúa la consulta del usuario
            logger.info(f"🤖 [Gemini 2.5 Flash] Procesando: '{user_prompt}'")
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=user_prompt,
                config=config
            )

            # Verificar si Gemini solicitó ejecutar alguna función (Tool Call)
            function_calls = []
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        function_calls.append(part.function_call)

            if not function_calls:
                # Gemini respondió directamente sin necesidad de llamar a BigQuery
                answer_text = response.text or "No se pudo obtener una respuesta directa."
                return ChatResponse(
                    answer=answer_text,
                    session_id=session_id,
                    tools_executed=[],
                    data=None
                )

            # Turno 2: Ejecutar las herramientas solicitadas por Gemini
            tool_responses_for_gemini = []
            for call in function_calls:
                fn_name = call.name
                fn_args = dict(call.args or {})
                logger.info(f"🛠️ Gemini decidió ejecutar: '{fn_name}' con args: {fn_args}")

                rows, exec_log = await self._execute_mcp_tool(fn_name, fn_args)
                tools_executed.append(exec_log)
                if rows:
                    raw_data.extend(rows)

                # Optimización de tokens: Pasar una muestra estructurada o resumen a Gemini
                # para que no desborde tokens si la consulta trajo cientos de filas
                muestra_datos = rows[:25] if len(rows) > 25 else rows
                resumen_payload = {
                    "total_filas_obtenidas": len(rows),
                    "muestra_registros": muestra_datos,
                    "nota": f"Se recuperaron {len(rows)} filas en total de BigQuery. Aquí se proveen las primeras {len(muestra_datos)} para el resumen analítico." if len(rows) > 25 else "Totalidad de registros provistos."
                }

                tool_responses_for_gemini.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": resumen_payload}
                    )
                )

            # Turno 3: Enviar los resultados de vuelta a Gemini para la redacción final
            turn_2_contents = [
                types.Content(role="user", parts=[types.Part.from_text(user_prompt)]),
                response.candidates[0].content,
                types.Content(role="user", parts=tool_responses_for_gemini)
            ]

            final_response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=turn_2_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION_LOGISTICA,
                    temperature=0.2
                )
            )

            final_text = final_response.text or "Consulta procesada con éxito."

            return ChatResponse(
                answer=final_text,
                session_id=session_id,
                tools_executed=tools_executed,
                data=raw_data if raw_data else None
            )

        except Exception as e:
            logger.error(f"Error durante el ciclo de Gemini: {e}", exc_info=True)
            # En caso de error de red o cuota en Vertex AI, usar fallback para no dejar colgado al usuario
            return await self._fallback_deterministic_execution(user_prompt, session_id, error_detail=str(e))

    async def _fallback_deterministic_execution(self, user_prompt: str, session_id: str, error_detail: Optional[str] = None) -> ChatResponse:
        """
        Ruta de contingencia (Fast-Path / Fallback):
        Si Vertex AI no está disponible de inmediato, detecta patrones como 'TIM <numero>' o 'tienda <id>'
        y consulta directamente BigQuery a través de Toolbox MCP para no bloquear el desarrollo.
        """
        logger.info("⚡ Ejecutando ruta de contingencia determinista...")
        tim_match = re.search(r'\b(655\d{6}|\d{8,10})\b', user_prompt)
        
        if tim_match:
            tim_val = int(tim_match.group(1))
            rows, exec_log = await self._execute_mcp_tool("consultar_despachos_logistica", {"tim": tim_val})
            
            if not rows:
                answer = f"ℹ️ Se consultó BigQuery a través de Toolbox MCP para el TIM **{tim_val}**, pero no se encontraron registros de despachos en los últimos 60 días."
            else:
                tienda_info = f"{rows[0].get('Nombre_Tienda', '')} ({rows[0].get('Tienda', '')})"
                fecha_envio = rows[0].get('Fecha_Enviado', 'N/D')
                whse = rows[0].get('Inventario_Whse', 'N/D')
                answer = (
                    f"### 📦 Resumen de Despacho Logístico — TIM `{tim_val}`\n\n"
                    f"- **Destino:** {tienda_info}\n"
                    f"- **Fecha de Envío:** {fecha_envio}\n"
                    f"- **Almacén Origen (Whse):** {whse}\n"
                    f"- **Total de Productos / SKUs Despachados:** **{len(rows)} artículos**\n\n"
                    f"*(Nota operativa: Consulta completada vía Toolbox MCP BigQuery con {len(rows)} registros recuperados)*"
                )
            
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_log],
                data=rows
            )

        return ChatResponse(
            answer=(
                f"No pude interpretar la consulta directamente o el servicio de IA reportó: {error_detail or 'Configuración requerida'}. "
                "Por favor especifica un número de TIM (ej. '655423616') o verifica las credenciales de Gemini en el archivo .env."
            ),
            session_id=session_id,
            tools_executed=[],
            data=None
        )

# Instancia global del agente
agente_logistica = LogisticaAgent()
