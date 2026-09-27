import asyncio
import json
import logging
import re
from typing import Dict, Any, List, Tuple, Optional

from backend.config import settings
from backend.models import ToolExecution, ChatResponse
from backend.agents._shared.loader import mcp_client
from backend.agents.logistica.prompts import SYSTEM_INSTRUCTION_LOGISTICA, get_system_instruction_logistica

logger = logging.getLogger("backend.agent_logistica")

class LogisticaAgent:
    """
    Agente Logístico de Tottus basado en Gemini y el catálogo de Toolbox MCP.
    Orquesta el ciclo de razonamiento, Function Calling hacia BigQuery y generación ejecutiva.
    """

    def __init__(self):
        self._genai_client = None
        self._client_mode = None

    def _get_client(self):
        """Inicializa el cliente de Google GenAI (Vertex AI o API Key)."""
        try:
            from google import genai
            if settings.USE_VERTEXAI:
                if self._genai_client is not None and self._client_mode == "vertexai":
                    return self._genai_client
                logger.info(f"☁️ Inicializando Gemini vía Vertex AI en proyecto '{settings.VERTEXAI_PROJECT}'...")
                self._genai_client = genai.Client(
                    vertexai=True,
                    project=settings.VERTEXAI_PROJECT,
                    location=settings.GOOGLE_CLOUD_LOCATION
                )
                self._client_mode = "vertexai"
                return self._genai_client

            # Modo API Key (Google AI Studio)
            api_key = settings.GEMINI_API_KEY
            if api_key:
                if self._genai_client is not None and self._client_mode == "api_key":
                    return self._genai_client
                logger.info(f"🔑 Inicializando Gemini con API Key directa ({api_key[:6]}...{api_key[-4:]})...")
                self._genai_client = genai.Client(api_key=api_key)
                self._client_mode = "api_key"
                return self._genai_client

            # Fallback si no hay clave ni vertexai
            self._genai_client = genai.Client()
            self._client_mode = "default"
            return self._genai_client
        except Exception as e:
            logger.error(f"Error al inicializar cliente de GenAI: {e}")
            return None

    async def _generate_content_with_retry(self, client, contents, config, primary_model: str):
        """
        Ejecuta generate_content con reintentos exponenciales y failover transparente
        entre modelos ante picos de demanda (503).
        """
        models_to_try = [primary_model]
        if settings.USE_VERTEXAI:
            fallbacks = ["gemini-2.5-flash", "gemini-1.5-flash"]
        else:
            fallbacks = ["gemini-3.5-flash-lite", "gemini-flash-latest"]

        for alt in fallbacks:
            if alt not in models_to_try:
                models_to_try.append(alt)

        last_error = None
        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    logger.info(f"🤖 [{model_name}] Generando contenido con IA (intento {attempt + 1})...")
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda m=model_name: client.models.generate_content(
                            model=m,
                            contents=contents,
                            config=config
                        )
                    )
                    return response, model_name
                except Exception as e:
                    last_error = e
                    err_msg = str(e)
                    if "503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg:
                        logger.warning(f"⚠️ [{model_name}] Alta demanda temporal en Google (503). Reintentando en 1.5s...")
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        raise e

        raise last_error

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
                description="Consolida los bultos, cajas, unidades, peso total en kg, volumen en m3 y camiones (por TIM, Placa, Tienda o Fecha 'YYYY-MM-DD').",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del vehículo de transporte."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código ID de la tienda destino (ej. '123', '451')."),
                        "fecha": types.Schema(type=types.Type.STRING, description="Fecha de despacho en formato 'YYYY-MM-DD' (ej. '2026-09-26').")
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
            ),
            types.FunctionDeclaration(
                name="buscar_por_shipment_o_do",
                description="Permite rastrear despachos usando el número de Shipment o número de DO (Delivery Order) cuando no se conoce el TIM.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "shipment": types.Schema(type=types.Type.STRING, description="Número identificador del shipment (ej. '90327449')."),
                        "trf_do": types.Schema(type=types.Type.STRING, description="Número de la orden de entrega Delivery Order (ej. '22796787').")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="buscar_tienda_por_nombre",
                description="Busca el código numérico ID de una tienda a partir de su nombre comercial (ej. 'Huanuco', 'San Luis', 'Angamos').",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "nombre_parcial": types.Schema(type=types.Type.STRING, description="Nombre o texto parcial de la tienda a buscar.")
                    },
                    required=["nombre_parcial"]
                )
            )
        ]

        return [types.Tool(function_declarations=function_declarations)]

    async def _execute_mcp_tool(self, tool_name: str, arguments: dict, include_data: bool = False) -> Tuple[List[Dict[str, Any]], ToolExecution]:
        """Ejecuta la herramienta seleccionada a través de Toolbox MCP."""
        fetch_all = (tool_name == "consultar_despachos_logistica" and "pagina" not in arguments)
        rows = await mcp_client.call_tool(tool_name, arguments, fetch_all_pages=fetch_all)

        execution_record = ToolExecution(
            tool_name=tool_name,
            arguments=arguments,
            result_count=len(rows),
            preview=rows[:3] if (include_data and rows) else None
        )
        return rows, execution_record

    async def run(
        self,
        user_prompt: str,
        session_id: str = "default_session",
        tienda_id: Optional[str] = None,
        include_data: bool = False
    ) -> ChatResponse:
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
            return await self._fallback_deterministic_execution(user_prompt, session_id, include_data=include_data)

        try:
            from google.genai import types

            tools = self._build_tools_declaration()
            config = types.GenerateContentConfig(
                system_instruction=get_system_instruction_logistica(),
                tools=tools,
                temperature=0.0  # Respuesta determinista y precisa
            )

            prompt_with_context = f"[Contexto de tienda seleccionada: Tienda ID '{tienda_id}']\n{user_prompt}" if tienda_id else user_prompt

            tool_role = "tool" if settings.USE_VERTEXAI else "user"
            turn_contents = [
                types.Content(role="user", parts=[types.Part.from_text(text=prompt_with_context)])
            ]
            final_text = ""

            logger.info(f"🤖 Procesando consulta: '{user_prompt}' (tienda_id={tienda_id})")

            # Bucle de razonamiento multi-paso (hasta 5 rondas de herramientas para razonamiento profundo)
            for round_idx in range(5):
                response, used_model = await self._generate_content_with_retry(
                    client=client,
                    contents=turn_contents,
                    config=config,
                    primary_model=settings.GEMINI_MODEL
                )

                if not response.candidates or not response.candidates[0].content:
                    break

                candidate_content = response.candidates[0].content
                turn_contents.append(candidate_content)

                # Verificar si Gemini solicitó ejecutar alguna función en esta ronda
                round_function_calls = []
                for part in candidate_content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        round_function_calls.append(part.function_call)

                if not round_function_calls:
                    # No hay llamadas a herramientas en esta ronda: Gemini entregó el texto final
                    text_parts = [p.text for p in candidate_content.parts if hasattr(p, "text") and p.text]
                    final_text = "".join(text_parts).strip()
                    break

                # Ejecutar herramientas invocadas por Gemini
                round_tool_responses = []
                for call in round_function_calls:
                    fn_name = call.name
                    fn_args = dict(call.args or {})
                    logger.info(f"🛠️ [Ronda {round_idx+1}] Gemini decidió ejecutar: '{fn_name}' con args: {fn_args}")

                    rows, exec_log = await self._execute_mcp_tool(fn_name, fn_args, include_data=include_data)
                    tools_executed.append(exec_log)
                    if rows:
                        raw_data.extend(rows)

                    muestra_datos = rows[:25] if len(rows) > 25 else rows
                    resumen_payload = {
                        "total_filas_obtenidas": len(rows),
                        "muestra_registros": muestra_datos,
                        "nota": f"Se recuperaron {len(rows)} filas en total de BigQuery. Aquí se proveen las primeras {len(muestra_datos)} para el resumen analítico." if len(rows) > 25 else "Totalidad de registros provistos."
                    }

                    round_tool_responses.append(
                        types.Part.from_function_response(
                            name=fn_name,
                            response={"result": resumen_payload}
                        )
                    )

                turn_contents.append(
                    types.Content(role=tool_role, parts=round_tool_responses)
                )

            # Si después del bucle aún no hay texto final, forzar síntesis ejecutiva
            if not final_text:
                logger.info("✍️ Forzando síntesis ejecutiva final...")
                turn_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text="Con los datos obtenidos anteriormente, redacta ahora la respuesta ejecutiva final en lenguaje natural para el supervisor. Si no hubo despachos en la fecha solicitada, indícalo claramente y presenta la tabla de los camiones más recientes encontrados."
                        )]
                    )
                )
                synthesis_config = types.GenerateContentConfig(
                    system_instruction=get_system_instruction_logistica(),
                    tools=tools,
                    temperature=0.2
                )
                synth_resp, _ = await self._generate_content_with_retry(
                    client=client,
                    contents=turn_contents,
                    config=synthesis_config,
                    primary_model=settings.GEMINI_MODEL
                )
                if synth_resp.candidates and synth_resp.candidates[0].content:
                    text_parts = [p.text for p in synth_resp.candidates[0].content.parts if hasattr(p, "text") and p.text]
                    final_text = "".join(text_parts).strip()

            if not final_text:
                if raw_data:
                    # Construir tabla ejecutiva automática con los camiones recuperados
                    lineas_camiones = []
                    placas_vistas = set()
                    for r in raw_data:
                        placa = r.get("Placa")
                        if placa and placa not in placas_vistas:
                            placas_vistas.add(placa)
                            fecha = r.get("fecha_despacho") or r.get("Fecha_Enviado", "")
                            tim = r.get("tim", "N/D")
                            whse = r.get("Inventario_Whse", "N/D")
                            cajas = r.get("total_cajas", r.get("Cajas", 0))
                            unidades = r.get("total_unidades", r.get("Unidades", 0))
                            peso = r.get("peso_total_kg", r.get("Peso_Total", 0))
                            vol = r.get("volumen_total_m3", r.get("Vol_Enviado", 0))
                            lineas_camiones.append(f"| **`{placa}`** | `{tim}` | {whse} | {cajas:,.0f} | {unidades:,.0f} | {peso:,.2f} kg | {vol:,.2f} m³ |")
                    
                    if lineas_camiones:
                        tabla = "\n".join(lineas_camiones[:10])
                        final_text = (
                            f"Se consultó el sistema central de transporte. A continuación tienes el detalle de los despachos y camiones encontrados:\n\n"
                            f"| PLACA | TIM | ORIGEN | CAJAS | UNIDADES | PESO TOTAL | VOLUMEN |\n"
                            f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
                            f"{tabla}\n\n"
                            f"*(Información verificada en el catálogo central de transportes Tottus)*"
                        )
                    else:
                        final_text = f"Se recuperaron {len(raw_data)} registros del sistema de transportes para tu consulta."
                else:
                    final_text = "Para la fecha indicada no se registran despachos ni camiones en el sistema de transporte en los últimos 60 días."

            return ChatResponse(
                answer=final_text,
                session_id=session_id,
                tools_executed=tools_executed,
                data=raw_data if (include_data and raw_data) else None
            )

        except Exception as e:
            err_str = str(e)
            if "PERMISSION_DENIED" in err_str or "403" in err_str:
                logger.warning(
                    f"⚠️ [Permiso Vertex AI en GCP]: Tu usuario no cuenta con el rol 'roles/aiplatform.user' en el proyecto '{settings.VERTEXAI_PROJECT}'. "
                    "Para usar Gemini con Vertex AI corporativo, el admin de GCP debe otorgar ese rol, o puedes agregar una clave GEMINI_API_KEY en tu .env. "
                    "Activando ruta de contingencia automática vía Toolbox MCP..."
                )
            else:
                logger.error(f"Error durante el ciclo de Gemini: {e}", exc_info=True)
            
            return await self._fallback_deterministic_execution(user_prompt, session_id, error_detail=err_str, include_data=include_data)

    async def _fallback_deterministic_execution(
        self,
        user_prompt: str,
        session_id: str,
        error_detail: Optional[str] = None,
        include_data: bool = False
    ) -> ChatResponse:
        """
        Ruta de contingencia (Fast-Path / Fallback):
        Si Vertex AI no está disponible de inmediato por permisos de GCP, detecta patrones como 'TIM <numero>' o 'tienda <id>'
        y consulta directamente BigQuery a través de Toolbox MCP para no bloquear el desarrollo.
        """
        logger.info("⚡ Ejecutando consulta heurística directa vía Toolbox MCP...")
        
        tim_match = re.search(r'\b(655\d{6}|\d{8,10})\b', user_prompt)
        tim_val = int(tim_match.group(1)) if tim_match else None
        
        # Detección de Placa directa (ej. "placa AJZ981" o "AJZ-981")
        placa_match = re.search(r'placa\s*[:#]?\s*([A-Za-z0-9-]+)', user_prompt, re.I)
        placa_val = placa_match.group(1).upper() if placa_match else None
        
        # 1. Consulta de Placa, Camión, Transporte o Consolidado de Carga
        es_consulta_camion = bool(re.search(r'\b(placa|camion|camión|vehiculo|vehículo|carga|transporte|flete|peso|volumen|pallet|cajas?)\b', user_prompt, re.I))
        if (es_consulta_camion and (tim_val or placa_val)) or placa_val:
            args = {}
            if tim_val:
                args["tim"] = tim_val
            if placa_val:
                args["placa"] = placa_val

            rows, exec_log = await self._execute_mcp_tool("resumen_carga_transporte", args, include_data=include_data)
            if not rows:
                criterio = f"la placa **{placa_val}**" if placa_val else f"el TIM **{tim_val}**"
                answer = f"ℹ️ Se consultó BigQuery a través de Toolbox MCP para {criterio}, pero no se encontró información de transporte o despacho en los últimos 60 días."
            else:
                r = rows[0]
                placa = r.get('Placa') or placa_val or 'No registrada / En asignación'
                tim = r.get('tim', 'N/D')
                tienda = f"{r.get('Nombre_Tienda', '')} ({r.get('Tienda', '')})"
                fecha = r.get('fecha_despacho', 'N/D')
                whse = r.get('Inventario_Whse', 'N/D')
                pallets = r.get('total_pallets', 0)
                skus = r.get('total_skus_distintos', 0)
                cajas = r.get('total_cajas', 0)
                unidades = r.get('total_unidades', 0)
                peso = r.get('peso_total_kg', 0)
                vol = r.get('volumen_total_m3', 0)

                answer = (
                    f"### 🚛 Información de Transporte y Camión\n\n"
                    f"- 🚚 **Placa del Camión:** **`{placa}`**\n"
                    f"- 📋 **TIM Asociado:** `{tim}`\n"
                    f"- 🏪 **Tienda Destino:** {tienda}\n"
                    f"- 🏭 **Almacén Origen (Whse):** {whse}\n"
                    f"- 📅 **Fecha de Despacho:** **{fecha}**\n\n"
                    f"#### 📦 Consolidado de Carga:\n"
                    f"- **Total SKUs Distintos:** {skus}\n"
                    f"- **Total Pallets:** {pallets}\n"
                    f"- **Total Cajas:** {cajas}\n"
                    f"- **Total Unidades:** {unidades}\n"
                    f"- **Peso Total:** {peso:,.2f} kg\n"
                    f"- **Volumen Total:** {vol:,.2f} m³\n"
                )
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_log],
                data=rows if (include_data and rows) else None
            )

        # 2. Consulta de Productos y Despachos generales por TIM
        if tim_val:
            rows, exec_log = await self._execute_mcp_tool("consultar_despachos_logistica", {"tim": tim_val}, include_data=include_data)
            
            if not rows:
                answer = f"ℹ️ Se consultó BigQuery a través de Toolbox MCP para el TIM **{tim_val}**, pero no se encontraron registros de despachos en los últimos 60 días."
            else:
                tienda_info = f"{rows[0].get('Nombre_Tienda', '')} ({rows[0].get('Tienda', '')})"
                fecha_envio = rows[0].get('Fecha_Enviado', 'N/D')
                whse = rows[0].get('Inventario_Whse', 'N/D')
                
                # Crear tabla markdown con los primeros 10 registros
                filas_tabla = []
                for r in rows[:10]:
                    sku = r.get('sku', '')
                    desc = (r.get('Descripcion') or '')[:35]
                    do = r.get('Trf_DO', '')
                    tipo = r.get('Tipo_DO', '')
                    filas_tabla.append(f"| `{sku}` | {desc} | `{do}` | {tipo} |")
                
                tabla_md = "\n".join(filas_tabla)
                nota_total = f"\n*(Mostrando los primeros 10 de **{len(rows)} productos** devueltos por BigQuery)*" if len(rows) > 10 else ""
                
                answer = (
                    f"### 📦 Despacho Logístico — TIM `{tim_val}`\n\n"
                    f"- **Destino:** {tienda_info}\n"
                    f"- **Fecha de Envío:** {fecha_envio}\n"
                    f"- **Almacén Origen (Whse):** {whse}\n"
                    f"- **Total de Productos / SKUs Despachados:** **{len(rows)} artículos**\n\n"
                    f"| SKU | Descripción | DO / Transferencia | Tipo |\n"
                    f"| :--- | :--- | :--- | :--- |\n"
                    f"{tabla_md}{nota_total}\n"
                )
            
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_log],
                data=rows if (include_data and rows) else None
            )

        # 3. Consulta de Shipment o DO en Fallback
        shipment_match = re.search(r'\b(9\d{6,8}|\d{8,10})\b', user_prompt)
        es_consulta_shipment = bool(re.search(r'\b(shipment|embarque|do|delivery\s*order|transferencia)\b', user_prompt, re.I))
        if es_consulta_shipment and shipment_match:
            shipment_id = shipment_match.group(1)
            rows, exec_log = await self._execute_mcp_tool("buscar_por_shipment_o_do", {"shipment": shipment_id}, include_data=include_data)
            if not rows:
                answer = f"ℹ️ Se consultó el sistema para el Shipment **{shipment_id}**, pero no se encontraron registros de despachos asociados en los últimos 60 días."
            else:
                r = rows[0]
                placa = r.get('Placa') or 'No registrada / En asignación'
                tim = r.get('tim', 'N/D')
                tienda = f"{r.get('Nombre_Tienda', '')} ({r.get('Tienda', '')})"
                fecha = r.get('fecha_despacho', 'N/D')
                do = r.get('Trf_DO', 'N/D')
                skus = r.get('total_skus', 0)
                cajas = r.get('total_cajas', 0)
                unidades = r.get('total_unidades', 0)
                peso = r.get('peso_total_kg', 0)

                answer = (
                    f"### 🚚 Rastreo de Shipment `{shipment_id}`\n\n"
                    f"- 🚛 **Camión / Placa:** **`{placa}`**\n"
                    f"- 📋 **TIM Asociado:** `{tim}`\n"
                    f"- 🏪 **Tienda Destino:** {tienda}\n"
                    f"- 📅 **Fecha de Despacho:** **{fecha}**\n"
                    f"- 📄 **Orden de Entrega (DO):** `{do}`\n\n"
                    f"#### 📦 Consolidado de Carga:\n"
                    f"- **Total SKUs:** {skus}\n"
                    f"- **Total Cajas:** {cajas}\n"
                    f"- **Total Unidades:** {unidades}\n"
                    f"- **Peso Total:** {peso:,.2f} kg\n"
                )
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_log],
                data=rows if (include_data and rows) else None
            )

        return ChatResponse(
            answer=(
                f"No pude interpretar la consulta directamente o el servicio de IA reportó: {error_detail or 'Configuración requerida'}. "
                "Por favor especifica un número de TIM (ej. '655423616'), placa de camión o Shipment para consultar los datos."
            ),
            session_id=session_id,
            tools_executed=[],
            data=None
        )

# Instancia global del agente
agente_logistica = LogisticaAgent()
