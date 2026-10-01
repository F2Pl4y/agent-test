import uuid
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

from backend.models import ChatRequest, ChatResponse, HealthResponse, SessionSummary, SessionDetail
from backend.agents.logistica.agent import agente_logistica
from backend.agents._shared.loader import mcp_client
from backend.services.session_manager import session_manager
from backend.config import settings

router = APIRouter(prefix="/api", tags=["Logística & Chat"])

@router.post("/chat", response_model=ChatResponse, summary="Enviar consulta conversacional al agente logístico")
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    Endpoint principal para interactuar con el agente en lenguaje natural.
    Gemini 3.5 Flash-Lite evalúa la pregunta, consulta BigQuery vía Toolbox MCP si es necesario,
    resguarda la auditoría persistente y devuelve la síntesis analítica junto con la tabla de datos estructurados.
    """
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    try:
        response = await agente_logistica.run(
            user_prompt=request.message,
            session_id=session_id,
            tienda_id=request.tienda_id,
            include_data=request.include_data,
            user_email=request.user_email,
            pais=request.pais or "PE"
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

@router.post("/cache/clear", summary="Limpiar la memoria caché de consultas")
async def clear_cache_endpoint():
    """Purga la memoria caché de consultas para forzar a BigQuery a recalcular datos frescos."""
    mcp_client.clear_cache()
    return {"status": "ok", "message": "Caché de consultas purgada exitosamente."}

@router.get("/sessions", response_model=List[SessionSummary], summary="Listar sesiones registradas para auditoría")
async def list_sessions_endpoint(limit: int = 50) -> List[SessionSummary]:
    """Lista las sesiones activas y recientes resguardadas en el sistema para auditoría y trazabilidad."""
    return session_manager.list_recent_sessions(limit=limit)

@router.get("/sessions/{session_id}", response_model=SessionDetail, summary="Consultar trazabilidad completa de una sesión")
async def get_session_detail_endpoint(session_id: str) -> SessionDetail:
    """Devuelve el historial completo, trazabilidad de herramientas ejecutadas y metadatos de una sesión."""
    safe_id = session_manager.sanitize_session_id(session_id)
    session = session_manager.get_or_create_session(safe_id)
    return session

@router.delete("/sessions/{session_id}", summary="Eliminar o reiniciar el resguardo de una sesión")
async def delete_session_endpoint(session_id: str):
    """Purga la memoria y el archivo de resguardo de una sesión para iniciar una conversación limpia."""
    safe_id = session_manager.sanitize_session_id(session_id)
    deleted = session_manager.delete_session(safe_id)
    return {"status": "ok", "message": f"Sesión '{safe_id}' purgada con éxito." if deleted else "No se encontró la sesión."}
