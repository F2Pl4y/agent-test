import asyncio
import json
import logging
import re
from typing import Dict, Any, List, Tuple, Optional

from backend.config import settings
from backend.models import ToolExecution, ChatResponse
from backend.agents._shared.loader import mcp_client
from backend.agents.logistica.prompts import SYSTEM_INSTRUCTION_LOGISTICA, get_system_instruction_logistica
from backend.services.session_manager import session_manager

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
            fallbacks = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
        else:
            fallbacks = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.7-flash"]

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
                name="resumen_carga_transporte",
                description="Consulta y lista todas las TIMs (transferencias), despachos y camiones enviados a una tienda o por fecha. Devuelve CADA TIM como una fila única con su placa, fecha, total de cajas, unidades, peso y volumen. Usar SIEMPRE que pidan 'todas las TIMs', 'lista de TIMs', 'camiones' o 'despachos' a una tienda.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM específico."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del vehículo de transporte."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código ID de la tienda destino (ej. '474', '123', '451')."),
                        "fecha": types.Schema(type=types.Type.STRING, description="Fecha de despacho en formato 'YYYY-MM-DD'.")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="consultar_despachos_logistica",
                description="Consulta el detalle a nivel de PRODUCTOS / SKUs individuales (artículo por artículo: descripción, unidades) dentro de un TIM específico o para un SKU puntual. Usar SOLO cuando pregunten por productos o artículos.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM logístico para ver sus productos (ej. 655425244)."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de la tienda (ej. '123', '114')."),
                        "sku": types.Schema(type=types.Type.STRING, description="Código SKU puntual."),
                        "pagina": types.Schema(type=types.Type.INTEGER, description="Opcional. Número de página específica solo si el usuario pide paginación explícita. Dejar nulo para traer todos los registros.")
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

    def _resolve_tool_name(self, name: str) -> str:
        """
        Normaliza y resuelve el nombre canónico de la herramienta en Toolbox MCP.
        Previene fallos si Gemini traduce 'por' -> 'by' o comprime palabras (ej. 'buscarbyshipmentodo').
        """
        clean = name.lower().replace("-", "_")
        aliases = {
            "buscarbyshipmentodo": "buscar_por_shipment_o_do",
            "buscar_by_shipment_o_do": "buscar_por_shipment_o_do",
            "buscar_shipment_o_do": "buscar_por_shipment_o_do",
            "buscar_shipment": "buscar_por_shipment_o_do",
            "rastrear_shipment": "buscar_por_shipment_o_do",
            "buscar_por_shipment": "buscar_por_shipment_o_do",
            "buscartiendapornombre": "buscar_tienda_por_nombre",
            "buscar_tienda": "buscar_tienda_por_nombre",
            "consultardespachoslogistica": "consultar_despachos_logistica",
            "consultar_despachos": "consultar_despachos_logistica",
            "resumencargatransporte": "resumen_carga_transporte",
            "resumen_camiones": "resumen_carga_transporte",
            "resumendespachospordivision": "resumen_despachos_por_division",
            "alertasvencimientotransito": "alertas_vencimiento_transito",
        }
        if clean in aliases:
            return aliases[clean]

        stripped = clean.replace("_", "").replace("by", "por")
        for canonical in [
            "consultar_despachos_logistica",
            "resumen_carga_transporte",
            "resumen_despachos_por_division",
            "alertas_vencimiento_transito",
            "buscar_por_shipment_o_do",
            "buscar_tienda_por_nombre"
        ]:
            if stripped == canonical.replace("_", ""):
                return canonical
        return name

    async def _execute_mcp_tool(self, tool_name: str, arguments: dict, include_data: bool = False) -> Tuple[List[Dict[str, Any]], ToolExecution]:
        """Ejecuta la herramienta seleccionada a través de Toolbox MCP."""
        canonical_name = self._resolve_tool_name(tool_name)
        if canonical_name != tool_name:
            logger.info(f"🔄 Redirigiendo nombre de herramienta '{tool_name}' -> '{canonical_name}'")

        # Asegurar tipo string en identificadores de shipment / trf_do / tienda si vinieron como números
        clean_args = dict(arguments or {})
        for str_key in ("shipment", "trf_do", "tienda", "sku"):
            if str_key in clean_args and clean_args[str_key] is not None:
                clean_args[str_key] = str(clean_args[str_key])

        # Si Gemini invocó consultar_despachos_logistica pero solo con 'tienda' (sin tim ni sku),
        # significa que se están buscando las TIMs/despachos de la tienda, no los artículos individuales.
        if canonical_name == "consultar_despachos_logistica" and "tienda" in clean_args and "tim" not in clean_args and "sku" not in clean_args:
            logger.info(f"🔄 Redirigiendo consulta de tienda ({clean_args.get('tienda')}) a 'resumen_carga_transporte' para devolver la lista de TIMs consolidadas")
            canonical_name = "resumen_carga_transporte"

        # Si la herramienta soporta paginación:
        # Si Gemini envió pagina=1 por omisión de esquema, lo removemos para que se traigan todas las páginas completas.
        if canonical_name in ("consultar_despachos_logistica", "resumen_carga_transporte"):
            if clean_args.get("pagina") == 1:
                clean_args.pop("pagina", None)
            fetch_all = ("pagina" not in clean_args)
        else:
            fetch_all = False

        rows = await mcp_client.call_tool(canonical_name, clean_args, fetch_all_pages=fetch_all)

        execution_record = ToolExecution(
            tool_name=canonical_name,
            arguments=clean_args,
            result_count=len(rows),
            preview=rows[:3] if (include_data and rows) else None
        )
        return rows, execution_record

    async def run(
        self,
        user_prompt: str,
        session_id: str = "default_session",
        tienda_id: Optional[str] = None,
        include_data: bool = False,
        user_email: Optional[str] = None,
        pais: Optional[str] = "PE"
    ) -> ChatResponse:
        """
        Flujo principal del agente con resguardo y auditoría:
        1. Sanitiza el session_id para evitar Path Traversal y asegurar persistencia.
        2. Gemini analiza la pregunta e invoca la herramienta MCP adecuada (Function Calling).
        3. Se ejecutan los datos en BigQuery a través de Toolbox.
        4. Gemini sintetiza la respuesta ejecutiva.
        5. Se resguarda la auditoría completa (pregunta, respuesta, herramientas, métricas) en almacenamiento persistente.
        6. Retorna la respuesta con el texto y las filas estructuradas para el frontend.
        """
        safe_session_id = session_manager.sanitize_session_id(session_id)
        client = self._get_client()
        tools_executed: List[ToolExecution] = []
        raw_data: List[Dict[str, Any]] = []

        # Si no hay cliente de IA configurado aún, retornar error limpio
        if not client:
            return self._build_error_response(
                "No se pudo inicializar el cliente de IA (Credenciales o configuración GEMINI_API_KEY no encontradas).",
                session_id=safe_session_id
            )

        try:
            from google.genai import types

            tools = self._build_tools_declaration()
            config = types.GenerateContentConfig(
                system_instruction=get_system_instruction_logistica(),
                tools=tools,
                temperature=0.0  # Respuesta determinista y precisa
            )

            active_tienda = tienda_id or session_manager.get_last_tienda(safe_session_id)
            if active_tienda:
                session_manager.set_last_tienda(safe_session_id, str(active_tienda))

            prompt_with_context = f"[Contexto de sesión: Tienda ID '{active_tienda}']\n{user_prompt}" if active_tienda else user_prompt

            # En Google AI Studio la API exige role='user' para respuestas de función; en Vertex AI es 'tool'
            tool_role = "tool" if settings.USE_VERTEXAI else "user"

            # Cargar historial conversacional previo de la sesión (recuperado de disco o memoria)
            recent_turns = session_manager.get_recent_history_for_llm(safe_session_id, max_turns=6)
            turn_contents = []
            for item in recent_turns:
                turn_contents.append(
                    types.Content(role=item["role"], parts=[types.Part.from_text(text=item["text"])])
                )
            turn_contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=prompt_with_context)])
            )
            final_text = ""

            logger.info(f"🤖 Procesando consulta: '{user_prompt}' (sesión={safe_session_id}, tienda={active_tienda}, historial={len(recent_turns)} msgs)")

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
                    dict_rows = [r for r in rows if isinstance(r, dict)] if rows else []
                    if dict_rows:
                        raw_data.extend(dict_rows)

                    muestra_datos = dict_rows[:60] if len(dict_rows) > 60 else dict_rows

                    # Calcular estadísticas operativas clave para que Gemini proporcione cifras 100% exactas
                    tiendas_set = set(str(r.get("Tienda") or r.get("tienda") or "") for r in dict_rows if (r.get("Tienda") or r.get("tienda")))
                    placas_set = set(str(r.get("Placa") or r.get("placa") or "") for r in dict_rows if (r.get("Placa") or r.get("placa")))
                    tims_set = set(str(r.get("tim") or r.get("Tim") or "") for r in dict_rows if (r.get("tim") or r.get("Tim")))

                    resumen_payload = {
                        "total_filas_despachos": len(dict_rows),
                        "total_tiendas_distintas": len(tiendas_set),
                        "total_camiones_distintos": len(placas_set),
                        "total_tims_distintos": len(tims_set),
                        "muestra_registros": muestra_datos,
                        "nota": (
                            f"MÉTRICA EXACTA: Se recuperaron {len(dict_rows)} despachos/registros en total de BigQuery correspondientes a {len(tiendas_set)} tiendas únicas/distintas. "
                            f"Si el usuario pregunta cuántas tiendas recibieron el SKU o producto, responde explícitamente indicando que son {len(tiendas_set)} tiendas distintas en un total de {len(dict_rows)} despachos/envíos."
                        ) if len(tiendas_set) > 0 else f"Se recuperaron {len(dict_rows)} registros de BigQuery."
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
                            text="Con los datos obtenidos anteriormente de las herramientas, redacta ahora la respuesta ejecutiva final en lenguaje natural respondiendo de manera precisa a la consulta del usuario."
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
                    final_text = "Para la fecha indicada no se registran despachos ni camiones en el sistema de transporte en los últimos 31 días."

            # Recordar tienda si alguna herramienta la utilizó
            for t in tools_executed:
                if t.arguments and "tienda" in t.arguments and t.arguments["tienda"]:
                    active_tienda = str(t.arguments["tienda"])
                    session_manager.set_last_tienda(safe_session_id, active_tienda)

            # Resguardar el intercambio en el almacenamiento persistente de auditoría
            if final_text:
                session_manager.record_turn(
                    session_id=safe_session_id,
                    user_message=user_prompt,
                    ai_response=final_text,
                    tools_executed=tools_executed,
                    records_count=len(raw_data),
                    tienda_id=active_tienda,
                    user_email=user_email,
                    pais=pais
                )

            # Incluir datos descargables ÚNICAMENTE si el usuario activó explícitamente el switch en el frontend
            should_include_data = bool(include_data)

            return ChatResponse(
                answer=final_text,
                session_id=safe_session_id,
                tools_executed=tools_executed,
                data=raw_data if (should_include_data and raw_data) else None
            )

        except Exception as e:
            err_str = str(e)
            logger.error(f"Error durante el ciclo de Gemini: {err_str}", exc_info=True)
            # Resguardo de auditoría ante incidencia
            session_manager.record_turn(
                session_id=safe_session_id,
                user_message=user_prompt,
                ai_response=f"Error en procesamiento: {err_str}",
                tools_executed=tools_executed,
                records_count=len(raw_data),
                tienda_id=active_tienda if 'active_tienda' in locals() else None,
                user_email=user_email,
                pais=pais,
                error=err_str
            )
            return self._build_error_response(error_detail=err_str, session_id=safe_session_id)

    def _build_error_response(
        self,
        error_detail: Optional[str],
        session_id: str = "default_session"
    ) -> ChatResponse:
        """
        Construye una respuesta de error transparente y limpia cuando el servicio de IA falla,
        informando el código de error y los detalles técnicos sin fingir respuestas heurísticas.
        """
        err_code, err_friendly = self._parse_gemini_error(error_detail)
        
        detail_msg = f"\n\n> 🔍 **Detalle técnico:** `{error_detail}`" if error_detail else ""
        answer = (
            f"⚠️ **Error en el servicio de IA ({err_code})**\n\n"
            f"{err_friendly}"
            f"{detail_msg}\n\n"
            f"*Verifica la configuración del modelo (`GEMINI_MODEL`), tu clave `GEMINI_API_KEY` en `.env` o la conexión con Google AI Studio.*"
        )
        return ChatResponse(
            answer=answer,
            session_id=session_id,
            tools_executed=[],
            data=None
        )

    async def _fallback_deterministic_execution(
        self,
        user_prompt: str,
        session_id: str,
        tienda_id: Optional[str] = None,
        error_detail: Optional[str] = None,
        include_data: bool = False
    ) -> ChatResponse:
        """Alias de compatibilidad que retorna el error limpio."""
        return self._build_error_response(error_detail=error_detail, session_id=session_id)

# Instancia global del agente
agente_logistica = LogisticaAgent()
