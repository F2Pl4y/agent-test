import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

from backend.config import settings
from backend.models import ToolExecution, ChatResponse
from backend.agents._shared.loader import mcp_client
from backend.agents.logistica.prompts import SYSTEM_INSTRUCTION_LOGISTICA, get_system_instruction_logistica
from backend.services.session_manager import session_manager
from backend.services.monitoreo_service import monitoreo_service

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
                description="Consulta y lista las TIMs (transferencias), despachos y camiones (por placa o tienda). Devuelve cada TIM con su placa, fecha de despacho, hora_carga, lead_time_horas (24h locales '1xx', 48h provincia '3xx', 72h oriente '4xx', 96h otras), fecha_estimada_llegada a tienda, total de cajas, unidades, peso y volumen.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM específico."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del vehículo de transporte."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código ID de la tienda destino (ej. '474', '123', '451'), o '*' / 'TODAS' para toda la cadena."),
                        "fecha": types.Schema(type=types.Type.STRING, description="Fecha de despacho o fecha de inicio en formato 'YYYY-MM-DD'."),
                        "fecha_fin": types.Schema(type=types.Type.STRING, description="Opcional. Fecha final en formato 'YYYY-MM-DD' cuando se consulta un rango de fechas.")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="consultar_cargas_pendientes_despacho",
                description="Consulta camiones (placas) o transferencias (TIMs) que ya fueron cargados en el Centro de Distribución (CD) pero que aún NO han sido despachados o enviados (Hora_de_Carga registrada pero Fecha_Enviado es nula o pendiente) hasta el día de hoy. Usar cuando el usuario pregunte por camiones cargados sin enviar o pendientes de salida.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código ID de la tienda destino (ej. '123', '107'), o '*' / 'TODAS' para todas las tiendas. Opcional."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del camión de transporte. Opcional."),
                        "dias_atras": types.Schema(type=types.Type.INTEGER, description="Días hacia atrás a consultar para cargas pendientes (por defecto 15 días).")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="consultar_despachos_logistica",
                description="Consulta el detalle a nivel de PRODUCTOS / SKUs individuales (artículo por artículo: descripción, unidades, hora_carga) dentro de un TIM específico o para un SKU/placa puntual. Usar SOLO cuando pregunten por productos o artículos.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número de TIM logístico para ver sus productos (ej. 655425244)."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de la tienda (ej. '123', '114'), o '*' / 'TODAS' para toda la cadena."),
                        "sku": types.Schema(type=types.Type.STRING, description="Código SKU puntual."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del vehículo puntual.")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="resumen_despachos_por_division",
                description="Devuelve el total de unidades y cajas despachadas a una tienda (o a toda la cadena con '*') agrupadas por división comercial (J01 a J11).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de tienda destino (ej. '123'), o '*' / 'TODAS' para consolidado global."),
                        "dias_atras": types.Schema(type=types.Type.INTEGER, description="Días hacia atrás a consultar (por defecto 7).")
                    },
                    required=["tienda"]
                )
            ),
            types.FunctionDeclaration(
                name="alertas_vencimiento_transito",
                description="Identifica productos en tránsito hacia una tienda (o toda la cadena con '*') cuya fecha de vencimiento esté próxima dentro de los próximos N días.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de tienda destino (ej. '123'), o '*' / 'TODAS' para toda la cadena."),
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
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "shipment": types.Schema(type=types.Type.STRING, description="Número identificador del shipment (ej. '90327449')."),
                        "trf_do": types.Schema(type=types.Type.STRING, description="Número de la orden de entrega Delivery Order (ej. '22796787').")
                    },
                    required=[]
                )
            ),
            types.FunctionDeclaration(
                name="buscar_tienda_por_nombre",
                description="Busca y valida si una tienda existe en la base de datos por su nombre comercial (ej. 'Huanuco', 'San Luis', 'Angamos') o por su código numérico ID (ej. '123', '451', '454'). Retorna el código y nombre oficial si existe, o lista vacía si NO existe.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "pais": types.Schema(type=types.Type.STRING, description="Código del país ('PE' para Perú, 'CL' para Chile). Por defecto 'PE'."),
                        "nombre_parcial": types.Schema(type=types.Type.STRING, description="Nombre comercial o código numérico ID de la tienda a buscar o validar (ej. 'Huanuco', '123', '454').")
                    },
                    required=["nombre_parcial"]
                )
            ),
            types.FunctionDeclaration(
                name="consultar_monitoreo_provincia",
                description="Consulta el reporte operativo en tiempo real de monitoreo de unidades de transporte EXCLUSIVAMENTE para tiendas de PROVINCIA (norte y sur, códigos que comienzan con '3') y ORIENTE / SELVA (códigos que comienzan con '4', como 474 Pucallpa o 451 Huánuco) desde SharePoint/Excel (Tabla3 - Hoja Perú). NO aplica para tiendas locales de Lima/Callao. Proporciona seguimiento en vivo: si el viaje es con carga ÚNICA o COMPARTIDA, el orden de paradas (Punto 1, 2, 3), la ruta programada de tiendas, la placa del tracto (TRACTO), tipo de unidad (TIPO DE UT: SEMITRAILER, DOBLE NIVEL, FURGÓN), hora de fin de carga en CD (FIN DE CARGA), salida a ruta, ubicación actual (UBICACIÓN), estado operativo en vivo (STATUS) e incidencias (MOTIVO). Permite buscar por TIM, placa o tienda destino.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tim": types.Schema(type=types.Type.INTEGER, description="Número identificador del TIM logístico."),
                        "placa": types.Schema(type=types.Type.STRING, description="Placa del camión, remolque o tracto."),
                        "tienda": types.Schema(type=types.Type.STRING, description="Código de la tienda destino de provincia u oriente (ej. '318', '352', '451', '474')."),
                        "tracto": types.Schema(type=types.Type.STRING, description="Placa del tracto o cabina motriz del camión.")
                    },
                    required=[]
                )
            )
        ]

        return [types.Tool(function_declarations=function_declarations)]

    def _is_reprogramacion_intent(self, user_prompt: str, recent_turns: list) -> bool:
        """
        Detecta si la consulta del usuario o el contexto reciente corresponde
        al flujo interactivo de Reprogramaciones y Órdenes de Compra (OC).
        """
        lowered = user_prompt.lower().strip()

        # Si el usuario hace una consulta logística explícita de camiones/tienda, no es reprogramación
        logistics_keywords = ["camion", "camiones", "placa", "despacho", "salidas", "inventario", "cajas", "pallets", "peso total"]
        if any(lk in lowered for lk in logistics_keywords):
            return False

        reprog_keywords = [
            "reprogramaci", "orden de compra", "oc ", " oc", "oc:", "oc?", "pedido",
            "en reparto", "registrado", "fallo de entrega", "excepcion", "excepción",
            "cliente ausente", "fuera de horario", "fuera de ruta", "direccion",
            "dirección", "distrito errado", "calle con dificil", "calle con difícil",
            "siniestro ol", "bodega por", "rechazado por cliente", "zona peligrosa",
            "requiere maniobra", "más personal", "mas personal", "no se cual es", "no lo se", "no sé"
        ]
        if any(k in lowered for k in reprog_keywords):
            return True

        # Si el usuario responde con un código numérico / alfanumérico corto o respuesta en flujo de reprogramación
        if recent_turns:
            for turn in reversed(recent_turns[-4:]):
                txt = turn.get("text", "").lower()
                if any(k in txt for k in [
                    "indícame el estado del pedido",
                    "indicame el estado del pedido",
                    "envíame la oc",
                    "enviame la oc",
                    "orden de compra",
                    "reprogramaci",
                    "excepción de entrega",
                    "excepcion de entrega",
                    "tipo de excepción",
                    "tipo de excepcion",
                    "acción requerida",
                    "accion requerida"
                ]):
                    return True

        return False

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
            "consultarcargaspendientesdespacho": "consultar_cargas_pendientes_despacho",
            "cargaspendientesdespacho": "consultar_cargas_pendientes_despacho",
            "cargas_pendientes_despacho": "consultar_cargas_pendientes_despacho",
            "camiones_pendientes_despacho": "consultar_cargas_pendientes_despacho",
            "camiones_cargados_pendientes": "consultar_cargas_pendientes_despacho",
            "cargas_pendientes": "consultar_cargas_pendientes_despacho",
            "camiones_cargados": "consultar_cargas_pendientes_despacho",
            "consultarmonitoreounidades": "consultar_monitoreo_provincia",
            "consultar_monitoreo_unidades": "consultar_monitoreo_provincia",
            "consultarmonitoreoprovincia": "consultar_monitoreo_provincia",
            "consultar_monitoreo_provincia": "consultar_monitoreo_provincia",
            "consultar_monitoreo": "consultar_monitoreo_provincia",
            "monitoreo_unidades": "consultar_monitoreo_provincia",
            "monitoreo_provincia": "consultar_monitoreo_provincia",
            "monitoreo_sharepoint": "consultar_monitoreo_provincia",
            "reporte_monitoreo": "consultar_monitoreo_provincia",
            "consultar_sharepoint": "consultar_monitoreo_provincia",
            "monitoreo_ut": "consultar_monitoreo_provincia",
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
            "buscar_tienda_por_nombre",
            "consultar_cargas_pendientes_despacho",
            "consultar_monitoreo_provincia"
        ]:
            if stripped == canonical.replace("_", ""):
                return canonical
        return name

    async def _execute_mcp_tool(
        self,
        tool_name: str,
        arguments: dict,
        include_data: bool = False,
        active_fecha: Optional[str] = None,
        pais: Optional[str] = "PE"
    ) -> Tuple[List[Dict[str, Any]], ToolExecution]:
        """Ejecuta la herramienta seleccionada a través de Toolbox MCP."""
        canonical_name = self._resolve_tool_name(tool_name)
        if canonical_name != tool_name:
            logger.info(f"🔄 Redirigiendo nombre de herramienta '{tool_name}' -> '{canonical_name}'")

        # Asegurar tipo string en identificadores de shipment / trf_do / tienda si vinieron como números
        clean_args = dict(arguments or {})
        clean_args.pop("pagina", None)  # [MCP-05] Paginación reemplazada por LIMIT 500
        if not clean_args.get("pais"):
            clean_args["pais"] = (pais or "PE").strip().upper()
        for str_key in ("shipment", "trf_do", "tienda", "sku", "pais"):
            if str_key in clean_args and clean_args[str_key] is not None:
                clean_args[str_key] = str(clean_args[str_key]).strip()

        if "placa" in clean_args and clean_args["placa"] is not None:
            clean_args["placa"] = str(clean_args["placa"]).strip().upper()

        if "tim" in clean_args and clean_args["tim"] is not None:
            try:
                clean_args["tim"] = int(clean_args["tim"])
            except Exception:
                pass

        # Si Gemini invocó consultar_despachos_logistica pero solo con 'tienda' (sin tim ni sku),
        # significa que se están buscando las TIMs/despachos de la tienda, no los artículos individuales.
        if canonical_name == "consultar_despachos_logistica" and "tienda" in clean_args and "tim" not in clean_args and "sku" not in clean_args:
            logger.info(f"🔄 Redirigiendo consulta de tienda ({clean_args.get('tienda')}) a 'resumen_carga_transporte' para devolver la lista de TIMs consolidadas")
            canonical_name = "resumen_carga_transporte"

        # Si se consulta resumen_carga_transporte para una tienda sin fecha, pero hay una fecha activa en la sesión:
        if canonical_name == "resumen_carga_transporte" and "tienda" in clean_args and not clean_args.get("fecha") and not clean_args.get("tim") and not clean_args.get("placa"):
            if active_fecha:
                logger.info(f"📅 Asociando fecha activa de sesión ({active_fecha}) a consulta de camiones para tienda {clean_args.get('tienda')}")
                clean_args["fecha"] = active_fecha

        # Manejo especializado de la herramienta de Monitoreo de Unidades (SharePoint / Excel - Locales y Provincia)
        if canonical_name in ("consultar_monitoreo_unidades", "consultar_monitoreo_provincia"):
            tim_param = clean_args.get("tim")
            placa_param = clean_args.get("placa")
            tienda_param = clean_args.get("tienda")
            tracto_param = clean_args.get("tracto")
            status_param = clean_args.get("status")

            rows = monitoreo_service.buscar_monitoreo(
                tim=tim_param,
                placa=placa_param,
                tienda=tienda_param,
                tracto=tracto_param,
                status=status_param,
                force_refresh=True,
                limit=15
            )

            execution_record = ToolExecution(
                tool_name=canonical_name,
                arguments=clean_args,
                result_count=len(rows),
                preview=rows[:3] if (include_data and rows) else None
            )
            return rows, execution_record

        rows = await mcp_client.call_tool(canonical_name, clean_args)
        rows = self._enrich_rows_with_arrival_estimates(rows)

        execution_record = ToolExecution(
            tool_name=canonical_name,
            arguments=clean_args,
            result_count=len(rows),
            preview=rows[:3] if (include_data and rows) else None
        )
        return rows, execution_record

    def _enrich_rows_with_arrival_estimates(self, rows: list) -> list:
        """
        Enriquece cada registro de despacho/camión con el cálculo preciso
        de Lead Time y Fecha Estimada de Llegada a partir de su hora_carga o fecha_despacho.
        """
        if not rows:
            return rows
        for r in rows:
            if not isinstance(r, dict):
                continue
            tienda = str(r.get("Tienda") or r.get("tienda") or "")
            if tienda.startswith("1"):
                lt = 24
            elif tienda.startswith("3"):
                lt = 48
            elif tienda.startswith("4"):
                lt = 72
            else:
                lt = 96
            r["lead_time_horas"] = lt

            hora_carga = r.get("hora_carga") or r.get("Hora_de_Carga")
            fecha_desp = r.get("fecha_despacho") or r.get("Fecha_Enviado")
            fecha_est = None

            if hora_carga:
                try:
                    clean_hc = str(hora_carga).strip()
                    if "." in clean_hc:
                        clean_hc = clean_hc.split(".")[0]
                    dt = datetime.strptime(clean_hc, "%Y-%m-%d %H:%M:%S")
                    dt_llegada = dt + timedelta(hours=lt)
                    fecha_est = dt_llegada.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            if not fecha_est and fecha_desp:
                try:
                    clean_fd = str(fecha_desp).strip()[:10]
                    d = datetime.strptime(clean_fd, "%Y-%m-%d")
                    d_llegada = d + timedelta(days=(lt // 24))
                    fecha_est = d_llegada.strftime("%Y-%m-%d")
                except Exception:
                    pass

            if fecha_est:
                r["fecha_estimada_llegada"] = fecha_est
        return rows

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

            # Cargar historial conversacional previo de la sesión (recuperado de disco o memoria)
            recent_turns = session_manager.get_recent_history_for_llm(safe_session_id, max_turns=10, user_email=user_email)
            is_reprog = self._is_reprogramacion_intent(user_prompt, recent_turns)

            if is_reprog:
                logger.info("📦 Flujo de Reprogramaciones/OC activo: desactivando herramientas MCP para respuesta determinista según protocolo.")
                tools = []
                config = types.GenerateContentConfig(
                    system_instruction=get_system_instruction_logistica(),
                    tools=None,
                    temperature=0.2
                )
                prompt_with_context = user_prompt
                active_tienda = None
            else:
                tools = self._build_tools_declaration()
                config = types.GenerateContentConfig(
                    system_instruction=get_system_instruction_logistica(),
                    tools=tools,
                    temperature=0.0  # Respuesta determinista y precisa
                )

                active_tienda = tienda_id or session_manager.get_last_tienda(safe_session_id)
                if active_tienda:
                    session_manager.set_last_tienda(safe_session_id, str(active_tienda))

                active_fecha = session_manager.get_last_fecha(safe_session_id)

                context_items = []
                if active_tienda:
                    context_items.append(f"Tienda activa: '{active_tienda}'")
                if active_fecha:
                    context_items.append(f"Fecha previamente consultada: '{active_fecha}'")

                # Detección de consulta de seguimiento/ubicación/estado en vivo
                lowered_prompt = user_prompt.lower()
                is_tracking_query = any(k in lowered_prompt for k in [
                    "dónde", "donde", "ubicaci", "se encuentra", "paradero", "en ruta", "estado actual", "status actual", "está el camión", "esta el camion", "está la tim", "esta la tim"
                ])

                if is_tracking_query:
                    context_items.append(
                        "CONSULTA EN VIVO: El usuario solicita la ubicación o estado actual del camión/TIM en tiempo real. "
                        "DEBES EJECUTAR OBLIGATORIAMENTE la herramienta 'consultar_monitoreo_provincia' en esta ronda para "
                        "obtener la última posición viva actualizada del sistema; ESTÁ TERMINANTEMENTE PROHIBIDO responder de memoria o repetir la ubicación de turnos previos."
                    )

                prompt_with_context = f"[Contexto de sesión: {', '.join(context_items)}]\n{user_prompt}" if context_items else user_prompt

            # En Google AI Studio la API exige role='user' para respuestas de función; en Vertex AI es 'tool'
            tool_role = "tool" if settings.USE_VERTEXAI else "user"

            turn_contents = []
            for item in recent_turns:
                turn_contents.append(
                    types.Content(role=item["role"], parts=[types.Part.from_text(text=item["text"])])
                )
            turn_contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=prompt_with_context)])
            )
            final_text = ""

            logger.info(f"🤖 Procesando consulta: '{user_prompt}' (sesión={safe_session_id}, tienda={active_tienda}, reprogramación={is_reprog}, historial={len(recent_turns)} msgs)")

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

                    rows, exec_log = await self._execute_mcp_tool(
                        fn_name,
                        fn_args,
                        include_data=include_data,
                        active_fecha=active_fecha,
                        pais=pais
                    )
                    tools_executed.append(exec_log)
                    dict_rows = [r for r in rows if isinstance(r, dict)] if rows else []
                    if dict_rows:
                        canonical = self._resolve_tool_name(fn_name)
                        if canonical in ("resumen_carga_transporte", "consultar_despachos_logistica", "resumen_despachos_por_division", "buscar_por_shipment_o_do", "alertas_vencimiento_transito", "consultar_cargas_pendientes_despacho", "consultar_monitoreo_unidades", "consultar_monitoreo_provincia"):
                            if any(t.tool_name == "buscar_tienda_por_nombre" for t in tools_executed[:-1]) and len(raw_data) <= 5:
                                raw_data = list(dict_rows)
                            else:
                                raw_data.extend(dict_rows)
                        elif canonical == "buscar_tienda_por_nombre":
                            if not raw_data:
                                raw_data.extend(dict_rows)
                        else:
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
                            text="Con los datos obtenidos anteriormente de las herramientas, redacta ahora la respuesta ejecutiva final respondiendo con precisión a la consulta del usuario. REGLA ESTRICTA: Coloca el bloque de 'Resumen operativo' (totales de camiones, TIMs, cajas, unidades y peso) SIEMPRE ARRIBA de la tabla, e incluye en la tabla la columna de 'Fecha Estimada de Llegada' calculada aproximadamente según el Lead Time de la tienda a partir de la hora de carga de cada camión."
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
                    sum_cajas = 0
                    sum_unidades = 0
                    sum_peso = 0.0
                    for r in raw_data:
                        cajas = r.get("total_cajas", r.get("Cajas", 0)) or 0
                        unidades = r.get("total_unidades", r.get("Unidades", 0)) or 0
                        peso = r.get("peso_total_kg", r.get("Peso_Total", 0)) or 0.0
                        sum_cajas += cajas
                        sum_unidades += unidades
                        sum_peso += peso
                        placa = r.get("Placa")
                        if placa and placa not in placas_vistas:
                            placas_vistas.add(placa)
                        fecha = r.get("fecha_despacho") or r.get("Fecha_Enviado", "Pendiente")
                        hora_carga = r.get("hora_carga", r.get("Hora_de_Carga", "N/D"))
                        tim = r.get("tim", "N/D")
                        whse = r.get("Inventario_Whse", "N/D")
                        fecha_est = r.get("fecha_estimada_llegada", "N/D")
                        lineas_camiones.append(f"| {len(lineas_camiones)+1} | **`{placa or 'N/D'}`** | `{tim}` | {whse} | {hora_carga} | {fecha} | {fecha_est} | {cajas:,.0f} | {unidades:,.0f} | {peso:,.2f} kg |")
                    
                    if lineas_camiones:
                        tabla = "\n".join(lineas_camiones[:15])
                        placas_lista = ", ".join(f"`{p}`" for p in sorted(placas_vistas))
                        final_text = (
                            f"Se consultó el sistema central de transporte con los siguientes resultados:\n\n"
                            f"**Resumen operativo:**\n"
                            f"• **Total de camiones (placas distintas):** {len(placas_vistas)} ({placas_lista})\n"
                            f"• **Total de transferencias (TIMs):** {len(raw_data)}\n"
                            f"• **Total de cajas:** {sum_cajas:,.0f}\n"
                            f"• **Total de unidades:** {sum_unidades:,.0f}\n"
                            f"• **Peso total:** {sum_peso:,.2f} kg\n\n"
                            f"*(El lead time estimado se calcula a partir de la hora de carga de cada camión en patio)*\n\n"
                            f"A continuación el detalle de los despachos:\n\n"
                            f"| # | PLACA (CAMIÓN) | TIM | CD ORIGEN | HORA DE CARGA | FECHA DESPACHO | FECHA ESTIMADA DE LLEGADA | CAJAS | UNIDADES | PESO TOTAL (KG) |\n"
                            f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
                            f"{tabla}\n\n"
                            f"*(Información verificada en el catálogo central de transportes Tottus)*"
                        )
                    else:
                        final_text = f"Se recuperaron {len(raw_data)} registros del sistema de transportes para tu consulta."
                else:
                    final_text = "Para la fecha indicada no se registran despachos ni camiones en el sistema de transporte en los últimos 31 días."

            # Recordar tienda y fecha si alguna herramienta las utilizó
            for t in tools_executed:
                if t.arguments:
                    if "tienda" in t.arguments and t.arguments["tienda"]:
                        active_tienda = str(t.arguments["tienda"])
                        session_manager.set_last_tienda(safe_session_id, active_tienda)
                    if "fecha" in t.arguments and t.arguments["fecha"]:
                        active_fecha = str(t.arguments["fecha"])
                        session_manager.set_last_fecha(safe_session_id, active_fecha)

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

            # FILTRO ESTRICTO DE NEGOCIO:
            # Solo devolver datos estructurados (para tabla y descarga de Excel)
            # si efectivamente se ejecutó una herramienta logística sustantiva (camiones, despachos, etc.)
            # Y NUNCA cuando solo se hizo una búsqueda auxiliar de tienda o la IA está pidiendo fecha.
            substantive_tools = {
                "resumen_carga_transporte",
                "consultar_despachos_logistica",
                "resumen_despachos_por_division",
                "buscar_por_shipment_o_do",
                "alertas_vencimiento_transito",
                "consultar_cargas_pendientes_despacho"
            }
            has_substantive_data = any(t.tool_name in substantive_tools for t in tools_executed)
            is_asking_for_date = any(kw in final_text.lower() for kw in [
                "indícame la fecha", "indicame la fecha", "indica la fecha", "rango de fechas", "fecha puntual", "qué fecha", "para qué fecha"
            ])

            should_send_data = bool(include_data) and bool(raw_data) and has_substantive_data and (not is_asking_for_date)

            return ChatResponse(
                answer=final_text,
                session_id=safe_session_id,
                tools_executed=tools_executed,
                data=raw_data if should_send_data else None
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
