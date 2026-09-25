import json
import time
import logging
from typing import Dict, Any, List, Optional
import httpx

from backend.config import settings

logger = logging.getLogger("backend.mcp_loader")

class SimpleTTLCache:
    """Caché en memoria LRU + TTL para evitar re-consultar BigQuery repetidamente."""
    def __init__(self, maxsize: int = 200, ttl_seconds: int = 1800):
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
        if len(self.cache) >= self.maxsize:
            # Eliminar la clave más antigua
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
        self.cache[key] = (time.monotonic(), value)

    def clear(self):
        self.cache.clear()


class ToolboxMCPClient:
    """
    Cliente oficial para interactuar con el servidor MCP Toolbox (Go binary en http://localhost:5001/mcp).
    Implementa el protocolo estándar JSON-RPC 2.0 (tools/list y tools/call).
    """
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.TOOLBOX_URL
        self.cache = SimpleTTLCache(maxsize=200, ttl_seconds=1800)
        self._cached_tools: Optional[List[Dict[str, Any]]] = None

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
        - Utiliza caché en memoria si la consulta ya fue ejecutada recientemente.
        - Soporta paginación automática si fetch_all_pages es True (ej. para traer todas las 106 filas de un TIM).
        """
        # Filtrar argumentos nulos o vacíos
        clean_args = {k: v for k, v in arguments.items() if v is not None and v != ""}
        
        # Verificar caché
        cache_key = f"{tool_name}:{json.dumps(clean_args, sort_keys=True)}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"⚡ [Caché 0ms Hit] Herramienta '{tool_name}' con args {clean_args}")
            return cached_result

        logger.info(f"⏳ [BigQuery Execution] Invocando '{tool_name}' con args {clean_args}")

        async def _call_single_page(args_dict: dict) -> List[Dict[str, Any]]:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args_dict
                }
            }
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(self.base_url, json=payload)
                res.raise_for_status()
                resp_json = res.json()

                if "error" in resp_json:
                    err_msg = resp_json["error"].get("message", str(resp_json["error"]))
                    raise RuntimeError(f"Error MCP en '{tool_name}': {err_msg}")

                content = resp_json.get("result", {}).get("content", [])
                rows = []
                for item in content:
                    txt = item.get("text", "")
                    try:
                        rows.append(json.loads(txt))
                    except Exception:
                        pass
                return rows

        if fetch_all_pages and tool_name == "consultar_despachos_logistica":
            # Descargar todas las páginas secuencialmente (hasta 500 registros máx)
            all_rows = []
            page = 1
            while page <= 10:
                page_args = dict(clean_args)
                page_args["pagina"] = page
                batch = await _call_single_page(page_args)
                if not batch:
                    break
                all_rows.extend(batch)
                if len(batch) < 50:
                    break
                page += 1
            final_rows = all_rows
        else:
            final_rows = await _call_single_page(clean_args)

        # Guardar en caché
        self.cache.set(cache_key, final_rows)
        return final_rows


# Instancia singleton accesible globalmente
mcp_client = ToolboxMCPClient()
