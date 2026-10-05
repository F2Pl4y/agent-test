import uuid
import secrets
from fastapi import APIRouter, HTTPException, Header
from typing import List, Dict, Any, Optional

from backend.models import VerifyRequest, VerifyResponse, ChatRequest, ChatResponse, HealthResponse, SessionSummary, SessionDetail
from backend.agents.logistica.agent import agente_logistica
from backend.agents._shared.loader import mcp_client
from backend.services.session_manager import session_manager
from backend.config import settings

router = APIRouter(prefix="/api", tags=["Logística & Chat"])

@router.post("/auth/verify", response_model=VerifyResponse, summary="Verificar credenciales de acceso antes de entrar")
async def verify_auth_endpoint(request: VerifyRequest) -> VerifyResponse:
    """
    Verifica inmediatamente el correo institucional y la clave de acceso del piloto (o token de Google).
    Si las credenciales no son válidas, rechaza con 401 o 403 impidiendo el ingreso al chat.
    """
    user_email = (request.email or "").strip().lower()
    if not user_email.endswith("@tottus.com.pe"):
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: El correo debe pertenecer exclusivamente al dominio corporativo @tottus.com.pe."
        )

    # 1. Control de Lista Blanca
    allowed_list = settings.ALLOWED_USERS
    if "all_users" not in allowed_list:
        if not allowed_list:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado: No hay colaboradores configurados en la lista de acceso (ALLOWED_USERS)."
            )
        if user_email not in allowed_list:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado: La cuenta '{user_email}' no figura en la lista de colaboradores autorizados para este piloto."
            )

    # 2. Control de Clave Secreta
    token = (request.key or "").strip()
    is_authorized = False

    # Clave del Piloto
    if token and settings.PILOT_ACCESS_KEY and secrets.compare_digest(token, settings.PILOT_ACCESS_KEY):
        is_authorized = True

    # Google OAuth (futuro)
    if not is_authorized and token and settings.GOOGLE_CLIENT_ID:
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
            google_email = (idinfo.get("email") or "").lower()
            if google_email == user_email:
                is_authorized = True
        except Exception:
            pass

    if not is_authorized:
        raise HTTPException(
            status_code=401,
            detail="Clave de acceso de piloto incorrecta. Por favor, verifica la clave del equipo."
        )

    return VerifyResponse(
        status="ok",
        message="Credenciales verificadas exitosamente.",
        email=user_email
    )

@router.post("/chat", response_model=ChatResponse, summary="Enviar consulta conversacional al agente logístico")
async def chat_endpoint(
    request: ChatRequest,
    authorization: Optional[str] = Header(None)
) -> ChatResponse:
    """
    Endpoint principal para interactuar con el agente en lenguaje natural.
    Control de seguridad en Modo Dual:
    1. Exige dominio @tottus.com.pe en user_email.
    2. Valida la credencial en Authorization: Bearer <token>:
       - Clave del Piloto (D4t4-PL$2026) vía comparación criptográfica secrets.compare_digest
       - O Token de Google OAuth si se encuentra configurado GOOGLE_CLIENT_ID a futuro.
    """
    # 🔒 1. Control de dominio corporativo: Exclusivo para colaboradores @tottus.com.pe
    user_email = (request.user_email or "").strip().lower()
    if not user_email.endswith("@tottus.com.pe"):
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: El asistente logístico está restringido exclusivamente a colaboradores con cuenta corporativa @tottus.com.pe."
        )

    # 🔒 1.1 Control estricto de Lista Blanca (Whitelist)
    allowed_list = settings.ALLOWED_USERS
    # Solo se permite paso libre si explícitamente se configuró "all_users"
    if "all_users" not in allowed_list:
        if not allowed_list:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado: No hay colaboradores configurados en la lista de acceso (ALLOWED_USERS). Contacta al administrador."
            )
        if user_email not in allowed_list:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado: La cuenta '{user_email}' no figura en la lista de colaboradores autorizados para este piloto."
            )

    # 🔒 2. Validación de Credencial (Modo Dual: Clave Piloto o Google OAuth)
    token = ""
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    is_authorized = False

    # Caso A: Verificación con Clave Secreta del Piloto
    if token and settings.PILOT_ACCESS_KEY and secrets.compare_digest(token, settings.PILOT_ACCESS_KEY):
        is_authorized = True

    # Caso B: Verificación con Google OAuth (cuando se configure GOOGLE_CLIENT_ID a futuro)
    if not is_authorized and token and settings.GOOGLE_CLIENT_ID:
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
            google_email = (idinfo.get("email") or "").lower()
            if google_email.endswith("@tottus.com.pe"):
                if "all_users" not in allowed_list:
                    if not allowed_list or google_email not in allowed_list:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Acceso denegado: La cuenta '{google_email}' autenticada con Google no figura en la lista de colaboradores autorizados para este piloto."
                        )
                is_authorized = True
                user_email = google_email
        except HTTPException:
            raise
        except Exception:
            pass

    if not is_authorized:
        raise HTTPException(
            status_code=401,
            detail="Credencial no autorizada. Ingresa la clave válida del piloto o inicia sesión con tu cuenta corporativa."
        )

    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    try:
        response = await agente_logistica.run(
            user_prompt=request.message,
            session_id=session_id,
            tienda_id=request.tienda_id,
            include_data=request.include_data,
            user_email=user_email,
            pais=request.pais or "PE"
        )
        return response
    except HTTPException:
        raise
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

@router.get("/audit", summary="Bitácora unificada de todas las consultas para gobernanza")
async def get_audit_log_endpoint(limit: int = 150, user_email: Optional[str] = None):
    """
    Devuelve la cronología unificada de todas las consultas realizadas por TODOS los colaboradores.
    Permite auditar en una sola vista quién preguntó qué, a qué hora y qué herramientas se ejecutaron.
    """
    return session_manager.get_unified_audit_log(limit=limit, user_email=user_email)

