import uuid
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from backend.models import ChatRequest, ChatResponse, HealthResponse
from backend.agents.logistica.agent import agente_logistica
from backend.agents._shared.loader import mcp_client
from backend.config import settings

router = APIRouter(prefix="/api", tags=["Logística & Chat"])

@router.post("/chat", response_model=ChatResponse, summary="Enviar consulta conversacional al agente logístico")
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Endpoint principal para interactuar con el agente en lenguaje natural.
    Gemini 2.5 Flash evalúa la pregunta, consulta BigQuery vía Toolbox MCP si es necesario,
    y devuelve la síntesis analítica junto con la tabla de datos estructurados.
    """
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    try:
        response = await agente_logistica.run(
            user_prompt=request.message,
            session_id=session_id,
            tienda_id=request.tienda_id
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar la consulta: {str(e)}")

@router.get("/tools", summary="Listar catálogo de herramientas MCP activas")
async def list_tools_endpoint() -> List[Dict[str, Any]]:
    """Devuelve las herramientas analíticas disponibles en el servidor Toolbox MCP."""
    try:
        return await mcp_client.list_tools()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar el catálogo MCP: {str(e)}")

@router.get("/health", response_model=HealthResponse, summary="Verificar estado de salud del backend y Toolbox")
async def health_endpoint() -> HealthResponse:
    """Verifica la conectividad con el servidor MCP Toolbox y la configuración general."""
    is_connected = await mcp_client.check_health()
    tools = []
    if is_connected:
        try:
            mcp_tools = await mcp_client.list_tools()
            tools = [t.get("name") for t in mcp_tools if "name" in t]
        except Exception:
            pass

    return HealthResponse(
        status="ok" if is_connected else "warning_mcp_unreachable",
        toolbox_url=settings.TOOLBOX_URL,
        toolbox_connected=is_connected,
        tools_available=tools,
        model=settings.GEMINI_MODEL
    )
