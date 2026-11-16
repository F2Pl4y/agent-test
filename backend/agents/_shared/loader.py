import json
import time
import logging
from typing import Dict, Any, List, Optional
import httpx

from backend.config import settings

logger = logging.getLogger("backend.mcp_loader")

ALL_TIENDA_SENTINEL = "__ALL_TIENDA__"
TIENDA_WILDCARDS = {"", "*", "TODAS", "ALL", "__ALL_TIENDA__"}

# Esquema canónico de valores neutros por herramienta MCP ([MCP-07])
# Garantiza que Toolbox/BigQuery siempre reciba todos los parámetros tipados sin nulos ni duplicados.
TOOL_PARAM_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "consultar_despachos_logistica": {
        "pais": "PE",
        "tim": 0,
        "tienda": ALL_TIENDA_SENTINEL,
        "sku": "",
        "placa": "",
    },
    "resumen_carga_transporte": {
        "pais": "PE",
        "tim": 0,
        "placa": "",
        "tienda": ALL_TIENDA_SENTINEL,
        "fecha": "",
        "fecha_fin": "",
    },
    "resumen_despachos_por_division": {
        "pais": "PE",
        "tienda": ALL_TIENDA_SENTINEL,
        "dias_atras": 7,
    },
    "alertas_vencimiento_transito": {
        "pais": "PE",
        "tienda": ALL_TIENDA_SENTINEL,
        "dias_margen": 15,
    },
    "buscar_por_shipment_o_do": {
        "pais": "PE",
        "shipment": "",
        "trf_do": "",
    },
    "buscar_tienda_por_nombre": {
        "pais": "PE",
        "nombre_parcial": "",
    },
    "consultar_cargas_pendientes_despacho": {
        "pais": "PE",
        "tienda": ALL_TIENDA_SENTINEL,
        "placa": "",
        "dias_atras": 15,
    },
}


class SimpleTTLCache:
    """Caché en memoria LRU + TTL para evitar re-consultar BigQuery repetidamente."""
    def __init__(self, maxsize: int = 200, ttl_seconds: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self.cache: Dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            timestamp, value = self.cache[key]
            if time.monotonic() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: Any):
        # NUNCA guardar en caché resultados vacíos o nulos para no bloquear consultas posteriores
        if not value:
            return
        if len(self.cache) >= self.maxsize:
            # Eliminar la clave más antigua
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[key]
        self.cache[key] = (time.monotonic(), value)

    def clear(self):
        self.cache.clear()


class ToolboxMCPClient:
    """
    Cliente oficial para interactuar con el servidor MCP Toolbox (Go binary en http://localhost:5001/mcp).
    Implementa el protocolo estándar JSON-RPC 2.0 (tools/list y tools/call) con normalización de centinelas.
    """
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.TOOLBOX_URL
        self.cache = SimpleTTLCache(maxsize=200, ttl_seconds=300)
        self._cached_tools: Optional[List[Dict[str, Any]]] = None

    def clear_cache(self):
        """Purga la caché en memoria inmediatamente."""
        self.cache.clear()
        self._cached_tools = None
        logger.info("🧹 Caché de Toolbox MCP purgada completamente.")

    def _normalize_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza los parámetros enviados al servidor MCP Toolbox ([MCP-07]):
        - Convierte comodines de tienda ('*', 'TODAS', '') al centinela '__ALL_TIENDA__'.
        - Inyecta valores neutros (0, '') para todos los parámetros opcionales omitidos.
        - Asegura que 'pais' sea 'PE' o 'CL' (por defecto 'PE').
        - Descarta parámetros obsoletos (como 'pagina') para evitar errores 400 en Toolbox.
        """
        defaults = TOOL_PARAM_DEFAULTS.get(tool_name)
        raw_args = dict(arguments or {})

        if defaults is None:
            return {k: v for k, v in raw_args.items() if v is not None}

        normalized: Dict[str, Any] = {}
        for param_name, default_val in defaults.items():
            val = raw_args.get(param_name)

            if param_name == "pais":
                pais_str = str(val).strip().upper() if val is not None else ""
                normalized["pais"] = pais_str if pais_str else str(default_val)
                continue

            if param_name == "tienda":
                tienda_str = str(val).strip() if val is not None else ""
                if tienda_str.upper() in TIENDA_WILDCARDS:
                    normalized["tienda"] = ALL_TIENDA_SENTINEL
                else:
                    normalized["tienda"] = tienda_str
                continue

            if isinstance(default_val, int):
                if val is None or str(val).strip() == "":
                    normalized[param_name] = default_val
                else:
                    try:
                        parsed_int = int(val)
                        normalized[param_name] = parsed_int if parsed_int >= 0 else default_val
                    except (TypeError, ValueError):
                        normalized[param_name] = default_val
                continue

            # Parámetros tipo string
            if val is None:
                normalized[param_name] = default_val
            else:
                text_val = str(val).strip()
                if param_name == "placa":
                    text_val = text_val.upper()
                elif param_name == "nombre_parcial" and text_val.upper() in TIENDA_WILDCARDS:
                    text_val = ALL_TIENDA_SENTINEL if text_val else ""
                normalized[param_name] = text_val

        return normalized

    async def check_health(self) -> bool:
        """Verifica si el servidor MCP Toolbox está activo y responde."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {}
                }
                res = await client.post(self.base_url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.warning(f"No se pudo conectar al servidor MCP en {self.base_url}: {e}")
            return False

    async def list_tools(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Consulta las herramientas disponibles registradas en el catálogo de Toolbox MCP.
        Devuelve el formato MCP estándar con nombres, descripciones y esquemas de parámetros.
        """
        if self._cached_tools and not force_refresh:
            return self._cached_tools

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(self.base_url, json=payload)
            res.raise_for_status()
            data = res.json()
            tools = data.get("result", {}).get("tools", [])
            self._cached_tools = tools
            return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], fetch_all_pages: bool = False) -> List[Dict[str, Any]]:
        """
        Invoca una herramienta en BigQuery a través de Toolbox MCP.
        - Normaliza todos los parámetros con centinelas y valores neutros ([MCP-07]).
        - Utiliza caché en memoria si la consulta ya fue ejecutada recientemente.
        - Las consultas SQL aplican LIMIT 500 directamente sin paginación ([MCP-05]).
        """
        clean_args = self._normalize_arguments(tool_name, arguments)

        # Verificar caché
        cache_key = f"{tool_name}:{json.dumps(clean_args, sort_keys=True)}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"⚡ [Caché 0ms Hit] Herramienta '{tool_name}' con args {clean_args}")
            return cached_result

        logger.info(f"⏳ [BigQuery Execution] Invocando '{tool_name}' con args {clean_args}")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": clean_args
            }
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(self.base_url, json=payload)
            res.raise_for_status()
            resp_json = res.json()

            if "error" in resp_json:
                err_msg = resp_json["error"].get("message", str(resp_json["error"]))
                raise RuntimeError(f"Error MCP en '{tool_name}': {err_msg}")

            result_obj = resp_json.get("result", {})
            if result_obj.get("isError"):
                content = result_obj.get("content", [])
                err_txt = " ".join([c.get("text", "") for c in content if isinstance(c, dict)])
                logger.error(f"❌ Error devuelto por Toolbox MCP en '{tool_name}': {err_txt}")
                raise RuntimeError(f"Error MCP en '{tool_name}': {err_txt}")

            content = result_obj.get("content", [])
            rows = []
            for item in content:
                txt = item.get("text", "")
                try:
                    parsed = json.loads(txt)
                    if isinstance(parsed, list):
                        rows.extend(parsed)
                    elif isinstance(parsed, dict):
                        rows.append(parsed)
                except Exception as parse_err:
                    logger.warning(f"⚠️ No se pudo parsear fila JSON de '{tool_name}': {txt[:120]} ({parse_err})")

        # Guardar en caché
        self.cache.set(cache_key, rows)
        return rows


# Instancia singleton accesible globalmente
mcp_client = ToolboxMCPClient()
