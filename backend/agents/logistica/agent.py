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
        entre modelos ante picos de demanda (503 / 429) o micro-cortes de conexión.
        """
        models_to_try = [primary_model]
        if settings.USE_VERTEXAI:
            fallbacks = ["gemini-2.5-flash", "gemini-2.0-flash"]
        else:
            fallbacks = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]

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
                    es_reintentable = any(x in err_msg for x in ["503", "UNAVAILABLE", "429", "10054", "ConnectionReset", "RemoteDisconnected", "timeout"])
                    if es_reintentable and attempt == 0:
                        logger.warning(f"⚠️ [{model_name}] Demanda de Google o micro-corte de red ({err_msg[:60]}). Reintentando en 1s...")
                        await asyncio.sleep(1.0)
                        continue
                    else:
                        break  # Pasar inmediatamente al siguiente modelo fallback

        raise last_error

    def _parse_gemini_error(self, err_str: Optional[str]) -> Tuple[str, str]:
        """
        Interpreta el error técnico devuelto por Google GenAI / Gemini / Red y
        devuelve:
        1. Código o tipo de error corto (ej: '500', '404', '403', '429', 'Conexión')
        2. Mensaje amigable y empático indicando entre paréntesis el tipo/código de error.
        """
        if not err_str:
            return ("Desconocido", "No se pudo procesar tu respuesta debido a una interrupción en el servicio de IA (Error Desconocido).")

        raw = err_str.lower()

        # 1. Error 500 (Internal Server Error)
        if "500" in err_str or "internal" in raw:
            return ("500", "No se pudo procesar tu respuesta debido a un error con el servidor (500).")

        # 2. Error 503 (Service Unavailable / Sobrecarga)
        if "503" in err_str or "unavailable" in raw:
            return ("503", "No se pudo procesar tu respuesta debido a que el servidor de IA se encuentra temporalmente fuera de línea o saturado (503).")

        # 3. Error 404 (Not Found / Modelo no encontrado)
        if "404" in err_str or "not_found" in raw or "not found" in raw:
            return ("404", "No se pudo procesar tu respuesta debido a que el modelo o recurso de IA solicitado no fue encontrado en el servidor (404).")

        # 4. Error 403 / 401 (Permission Denied / Unauthorized)
        if "403" in err_str or "401" in err_str or "permission_denied" in raw or "unauthorized" in raw or "permission denied" in raw:
            return ("403", "No se pudo procesar tu respuesta debido a un problema de permisos o credenciales con el servidor de IA (403).")

        # 5. Error 429 (Too Many Requests / Cuota agotada)
        if "429" in err_str or "resource_exhausted" in raw or "quota" in raw:
            return ("429", "No se pudo procesar tu respuesta debido a que se alcanzó el límite temporal de consultas en el servidor (429).")

        # 6. Error 400 (Bad Request / Argumento inválido)
        if "400" in err_str or "invalid_argument" in raw or "bad request" in raw:
            return ("400", "No se pudo procesar tu respuesta debido a que la solicitud no tiene un formato válido para el servidor de IA (400).")

        # 7. Problemas de red, corte de conexión o timeouts
        if any(w in raw for w in ["timeout", "timed out", "connection", "remote", "10054", "reset", "refused", "desconectado"]):
            return ("Conexión", "No se pudo procesar tu respuesta debido a una interrupción en la conexión de red con el servidor (Error de Conexión).")

        # 8. Extraer código HTTP numérico si existe en el texto
        code_match = re.search(r'\b(4\d{2}|5\d{2})\b', err_str)
        if code_match:
            code = code_match.group(1)
            return (code, f"No se pudo procesar tu respuesta debido a un error con el servidor ({code}).")

        # 9. Fallback general
        return ("Servicio IA", "No se pudo procesar tu respuesta debido a una incidencia en la comunicación con el servidor de inteligencia artificial (Error de Servicio).")

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
            return await self._fallback_deterministic_execution(
                user_prompt, 
                session_id, 
                tienda_id=tienda_id, 
                error_detail="No se pudo inicializar el cliente de IA (Credenciales o configuración no encontradas)", 
                include_data=include_data
            )

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
            
            return await self._fallback_deterministic_execution(user_prompt, session_id, tienda_id=tienda_id, error_detail=err_str, include_data=include_data)

    async def _fallback_deterministic_execution(
        self,
        user_prompt: str,
        session_id: str,
        tienda_id: Optional[str] = None,
        error_detail: Optional[str] = None,
        include_data: bool = False
    ) -> ChatResponse:
        """
        Ruta de contingencia (Fast-Path / Fallback):
        Si Vertex AI no está disponible de inmediato por permisos de GCP, detecta patrones como 'TIM <numero>' o 'tienda <id>'
        y consulta directamente BigQuery a través de Toolbox MCP para no bloquear el desarrollo.
        """
        logger.info("⚡ Ejecutando consulta heurística directa vía Toolbox MCP...")
        
        err_code, err_friendly = self._parse_gemini_error(error_detail)
        contingency_banner = f"> ⚠️ **Modo de contingencia activo:** {err_friendly} Se procedió a consultar directamente la base de datos de transportes." if error_detail else ""

        tim_match = re.search(r'\b(655\d{6}|\d{8,10})\b', user_prompt)
        tim_val = int(tim_match.group(1)) if tim_match else None
        
        # Detección de Placa directa (ej. "placa AJZ981" o "AJZ-981")
        placa_match = re.search(r'placa\s*[:#]?\s*([A-Za-z0-9-]+)', user_prompt, re.I)
        placa_val = placa_match.group(1).upper() if placa_match else None
        
        # 0. Saludo o solicitud de ayuda general (excluye si incluye preguntas explícitas de cálculo matemático o ajenas)
        es_pregunta_ajena = bool(re.search(r'\b(sumar?|restar?|multiplicar?|dividir?|calcular|calculadora|chiste|cuento|poema)\b', user_prompt, re.I))
        es_saludo = bool(re.search(r'\b(hola|buen(?:os)?\s*(?:d[ií]as|tardes|noches)|saludos?|ayuda|ayudarme|puedes ayudarme|qu[eé] haces|qu[eé] puedes hacer|c[oó]mo funcionas?)\b', user_prompt, re.I)) and not es_pregunta_ajena
        if es_saludo and not (tim_val or placa_val):
            if error_detail:
                saludo_texto = (
                    f"¡Hola! Con mucho gusto. Soy tu **Asistente de Transporte y Despachos de Tottus Perú** 🇵🇪.\n\n"
                    f"> ℹ️ **Estado del Asistente:** {err_friendly}\n\n"
                    "Para mantener la continuidad operativa, se encuentra habilitado el **Modo de Contingencia Directa** conectado a la base de datos de transportes:\n\n"
                    "- 🚛 **Camiones y Transportes:** Saber qué camiones fueron a una tienda en una fecha específica (ej. *'¿Qué camión fue a Angamos el 26.09?'*).\n"
                    "- 📋 **Detalle de Transferencias (TIM):** Conocer los productos despachados usando el número de TIM (ej. *'Productos del TIM 655423616'*).\n"
                    "- 📦 **Consolidado de Carga:** Ver el total de cajas, unidades, peso y volumen de un camión o placa.\n"
                    "- 🔍 **Rastreo por Shipment o DO:** Rastrear envíos específicos desde los almacenes del CD.\n\n"
                    "¿Qué consulta te gustaría realizar hoy?"
                )
            else:
                saludo_texto = (
                    "¡Hola! Con mucho gusto. Soy tu **Asistente de Transporte y Despachos de Tottus Perú** 🇵🇪.\n\n"
                    "Puedo asistirte en tiempo real con las operaciones logísticas del Centro de Distribución y Tiendas:\n\n"
                    "- 🚛 **Camiones y Transportes:** Saber qué camiones fueron a una tienda en una fecha específica (ej. *'¿Qué camión fue a Angamos el 26.09?'*).\n"
                    "- 📋 **Detalle de Transferencias (TIM):** Conocer los productos despachados usando el número de TIM (ej. *'Productos del TIM 655423616'*).\n"
                    "- 📦 **Consolidado de Carga:** Ver el total de cajas, unidades, peso y volumen de un camión o placa.\n"
                    "- 🔍 **Rastreo por Shipment o DO:** Rastrear envíos específicos desde los almacenes del CD.\n\n"
                    "¿Qué consulta te gustaría realizar hoy?"
                )
            return ChatResponse(
                answer=saludo_texto,
                session_id=session_id,
                tools_executed=[],
                data=None
            )

        # Detección de Tienda por nombre, código numérico o contexto del dropdown
        tienda_val = tienda_id
        tiendas_map = {
            "angamos": "123",
            "san luis": "114",
            "huanuco": "451",
            "huánuco": "451",
            "atocongo": "104",
            "megaplaza": "109"
        }
        for nombre, tid in tiendas_map.items():
            if re.search(r'\b' + re.escape(nombre) + r'\b', user_prompt, re.I):
                tienda_val = tid
                break
        if not tienda_val:
            tienda_match = re.search(r'\btienda\s*[:#]?\s*(\d{3})\b', user_prompt, re.I)
            tienda_val = tienda_match.group(1) if tienda_match else None

        # Detección de Fecha (ej. 'ayer', 'hoy', '27.09', '26.09', '26/09', '26-09' o '2026-09-26')
        fecha_val = None
        if re.search(r'\bayer\b', user_prompt, re.I):
            from datetime import date, timedelta
            fecha_val = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        elif re.search(r'\bhoy\b', user_prompt, re.I):
            from datetime import date
            fecha_val = date.today().strftime("%Y-%m-%d")
        else:
            fecha_corta = re.search(r'\b(\d{1,2})[./\-](\d{1,2})\b', user_prompt)
            if fecha_corta:
                dia = fecha_corta.group(1).zfill(2)
                mes = fecha_corta.group(2).zfill(2)
                fecha_val = f"2026-{mes}-{dia}"
            else:
                fecha_iso = re.search(r'\b(202\d-\d{2}-\d{2})\b', user_prompt)
                if fecha_iso:
                    fecha_val = fecha_iso.group(1)

        # 1. Consulta de Placa, Camión, Transporte, TIM o Despachos generales
        es_consulta_camion = bool(re.search(r'\b(placa|placas|camion|camión|camiones|vehiculo|vehículo|vehiculos|vehículos|carga|transporte|transportes|flete|peso|volumen|pallet|pallets|cajas?)\b', user_prompt, re.I))
        es_consulta_logistica = bool(re.search(r'\b(tim|tims|despacho|despachos|transferencia|transferencias|envio|envío|envios|envíos|salida|salidas)\b', user_prompt, re.I))
        es_consulta_productos = bool(re.search(r'\b(productos?|mercader[ií]a|art[ií]culos?|skus?|items?|contenido)\b', user_prompt, re.I))
        
        # 1A. Consulta de TIMs, Despachos o Camiones por Fecha (hacia una tienda o general)
        if (es_consulta_logistica or es_consulta_camion) and fecha_val:
            args = {"fecha": fecha_val}
            if tienda_val:
                args["tienda"] = tienda_val

            rows, exec_log = await self._execute_mcp_tool("resumen_carga_transporte", args, include_data=include_data)
            if not rows:
                tienda_info = f" para la tienda **{tienda_val}**" if tienda_val else ""
                answer = f"ℹ️ Se consultó el sistema central de transporte{tienda_info} para la fecha **{fecha_val}**, pero no se registran transferencias (TIMs) ni despachos en esa fecha."
            else:
                lineas_camiones = []
                total_cajas_dia = 0
                total_unidades_dia = 0
                total_peso_dia = 0.0
                placas_vistas = set()
                for r in rows:
                    placa = r.get("Placa", "N/D")
                    placas_vistas.add(placa)
                    tim = r.get("tim", "N/D")
                    whse = r.get("Inventario_Whse", "N/D")
                    cajas = float(r.get("total_cajas") or 0)
                    unidades = float(r.get("total_unidades") or 0)
                    peso = float(r.get("peso_total_kg") or 0)
                    vol = float(r.get("volumen_total_m3") or 0)
                    tienda_nombre = r.get("Nombre_Tienda", r.get("Tienda", ""))
                    total_cajas_dia += cajas
                    total_unidades_dia += unidades
                    total_peso_dia += peso
                    lineas_camiones.append(f"| **`{placa}`** | `{tim}` | {whse} | {tienda_nombre} | {cajas:,.0f} | {unidades:,.0f} | {peso:,.2f} kg | {vol:,.2f} m³ |")

                tabla = "\n".join(lineas_camiones[:15])
                nota_total = f"\n\n*(Mostrando 15 de {len(rows)} transferencias)*" if len(rows) > 15 else ""
                titulo_tienda = f" — Tienda {rows[0].get('Nombre_Tienda', tienda_val)}" if tienda_val else ""

                answer = (
                    f"### 📋 Transferencias y Despachos (TIMs){titulo_tienda}\n\n"
                    f"- 📅 **Fecha:** **{fecha_val}**\n"
                    f"- 🚛 **Camiones Identificados:** **{len(placas_vistas)} vehículos físicos** ({len(rows)} transferencias/TIMs)\n"
                    f"- 📦 **Carga Total:** {total_cajas_dia:,.0f} cajas | {total_unidades_dia:,.0f} unidades | {total_peso_dia:,.2f} kg\n\n"
                    f"| PLACA | TIM | CD ORIGEN | DESTINO | CAJAS | UNIDADES | PESO TOTAL | VOLUMEN |\n"
                    f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
                    f"{tabla}{nota_total}\n\n"
                    f"*(Información verificada en el catálogo central de transportes Tottus)*"
                )
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_log],
                data=rows if (include_data and rows) else None
            )

        # 1B. Consulta de Camiones hacia una Tienda sin fecha puntual
        if es_consulta_camion and tienda_val:
            args = {"tienda": tienda_val}
            rows, exec_log = await self._execute_mcp_tool("resumen_carga_transporte", args, include_data=include_data)
            if not rows:
                answer = f"ℹ️ Se consultó el sistema de transporte para la tienda **{tienda_val}**, pero no se encontraron despachos registrados en los últimos 60 días."
            else:
                lineas_camiones = []
                total_cajas_dia = 0
                total_unidades_dia = 0
                total_peso_dia = 0.0
                placas_vistas = set()
                for r in rows:
                    placa = r.get("Placa", "N/D")
                    placas_vistas.add(placa)
                    tim = r.get("tim", "N/D")
                    whse = r.get("Inventario_Whse", "N/D")
                    cajas = float(r.get("total_cajas") or 0)
                    unidades = float(r.get("total_unidades") or 0)
                    peso = float(r.get("peso_total_kg") or 0)
                    vol = float(r.get("volumen_total_m3") or 0)
                    total_cajas_dia += cajas
                    total_unidades_dia += unidades
                    total_peso_dia += peso
                    lineas_camiones.append(f"| **`{placa}`** | `{tim}` | {whse} | {cajas:,.0f} | {unidades:,.0f} | {peso:,.2f} kg | {vol:,.2f} m³ |")

                tabla = "\n".join(lineas_camiones[:10])
                nombre_tienda = rows[0].get("Nombre_Tienda", tienda_val)

                answer = (
                    f"### 🚚 Despacho de Camiones — Tienda {nombre_tienda} ({tienda_val})\n\n"
                    f"- 🚛 **Camiones Identificados:** **{len(placas_vistas)} vehículos físicos** ({len(rows)} transferencias/TIMs)\n"
                    f"- 📦 **Carga Total:** {total_cajas_dia:,.0f} cajas | {total_unidades_dia:,.0f} unidades | {total_peso_dia:,.2f} kg\n\n"
                    f"| PLACA | TIM | CD ORIGEN | CAJAS | UNIDADES | PESO TOTAL | VOLUMEN |\n"
                    f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
                    f"{tabla}\n\n"
                    f"*(Información verificada en el catálogo central de transportes Tottus)*"
                )
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_log],
                data=rows if (include_data and rows) else None
            )

        # 1C. Consulta Compuesta: Camión Y Productos para un TIM simultáneamente
        if tim_val and es_consulta_camion and es_consulta_productos:
            rows_camion, exec_camion = await self._execute_mcp_tool("resumen_carga_transporte", {"tim": tim_val}, include_data=include_data)
            rows_prod, exec_prod = await self._execute_mcp_tool("consultar_despachos_logistica", {"tim": tim_val}, include_data=include_data)

            if not rows_camion and not rows_prod:
                answer = f"ℹ️ Se consultó el sistema para el TIM **{tim_val}**, pero no se encontraron registros de transporte ni productos en los últimos 60 días."
            else:
                bloque_camion = ""
                if rows_camion:
                    r = rows_camion[0]
                    placa = r.get('Placa') or 'No registrada / En asignación'
                    tienda = f"{r.get('Nombre_Tienda', '')} ({r.get('Tienda', '')})"
                    fecha = r.get('fecha_despacho', 'N/D')
                    whse = r.get('Inventario_Whse', 'N/D')
                    cajas = float(r.get('total_cajas') or 0)
                    unidades = float(r.get('total_unidades') or 0)
                    peso = float(r.get('peso_total_kg') or 0)
                    vol = float(r.get('volumen_total_m3') or 0)
                    bloque_camion = (
                        f"### 🚛 Información de Transporte y Camión\n\n"
                        f"- 🚚 **Placa del Camión:** **`{placa}`**\n"
                        f"- 📋 **TIM Asociado:** `{tim_val}`\n"
                        f"- 🏪 **Tienda Destino:** {tienda}\n"
                        f"- 🏭 **Almacén Origen (Whse):** {whse}\n"
                        f"- 📅 **Fecha de Despacho:** **{fecha}**\n\n"
                        f"#### 📦 Consolidado de Carga:\n"
                        f"- **Cajas:** {cajas:,.0f} | **Unidades:** {unidades:,.0f} | **Peso:** {peso:,.2f} kg | **Volumen:** {vol:,.2f} m³\n\n"
                    )

                bloque_prod = ""
                if rows_prod:
                    filas_tabla = []
                    for r in rows_prod[:10]:
                        sku = r.get('sku', '')
                        desc = (r.get('Descripcion') or '')[:35]
                        do = r.get('Trf_DO', '')
                        tipo = r.get('Tipo_DO', '')
                        filas_tabla.append(f"| `{sku}` | {desc} | `{do}` | {tipo} |")
                    tabla_md = "\n".join(filas_tabla)
                    nota_total = f"\n*(Mostrando los primeros 10 de **{len(rows_prod)} productos** devueltos)*" if len(rows_prod) > 10 else ""
                    bloque_prod = (
                        f"### 📋 Detalle de Mercadería y Productos (TIM `{tim_val}`)\n\n"
                        f"| SKU | Descripción | DO / Transferencia | Tipo |\n"
                        f"| :--- | :--- | :--- | :--- |\n"
                        f"{tabla_md}{nota_total}\n\n"
                    )

                nota_compuesta = "> ℹ️ **Consulta Compuesta Atendida:** Se procesó la consulta múltiple de camión asignado y lista de productos para esta TIM.\n\n"
                answer = f"{nota_compuesta}{bloque_camion}{bloque_prod}*(Información verificada en el catálogo central de transportes Tottus)*"

            return ChatResponse(
                answer=answer,
                session_id=session_id,
                tools_executed=[exec_camion, exec_prod],
                data=(rows_prod or rows_camion) if include_data else None
            )

        # 1D. Consulta de Camión por TIM o Placa puntual
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

        if error_detail:
            answer = (
                f"⚠️ **Aviso de Operación en Contingencia**\n\n"
                f"{err_friendly}\n\n"
                f"El **modo de contingencia directa** se encuentra activo. En este modo de respaldo el asistente no cuenta con razonamiento conversacional ni puede realizar cálculos u operaciones ajenas al despacho (como sumas o preguntas generales).\n\n"
                f"Para consultar información operativa directamente en el sistema de transporte, por favor especifica:\n"
                f"- Un número de **TIM** (ej. `'655423616'`)\n"
                f"- Una **placa de camión** (ej. `'AJZ-981'`)\n"
                f"- Nombre de **tienda** y **fecha** (ej. *Angamos el 26.09*)"
            )
        else:
            answer = (
                "Para consultar directamente los datos de despacho, por favor especifica un número de **TIM** (ej. `'655423616'`), "
                "**placa de camión** o nombre de **tienda** y **fecha** (ej. *Angamos el 26.09*)."
            )

        return ChatResponse(
            answer=answer,
            session_id=session_id,
            tools_executed=[],
            data=None
        )

# Instancia global del agente
agente_logistica = LogisticaAgent()
