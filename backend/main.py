import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.chat import router as chat_router
from backend.agents._shared.loader import mcp_client
from backend.config import settings

# Configuración de Logging estructurado
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida del servidor: verifica conectividad con Toolbox MCP al iniciar."""
    mcp_client.clear_cache()
    logger.info("🚀 Iniciando Backend del Agente Logístico Tottus...")
    logger.info(f"📡 Conectando a Toolbox MCP en: {settings.TOOLBOX_URL}")

    is_up = await mcp_client.check_health()
    if is_up:
        tools = await mcp_client.list_tools()
        logger.info(
            f"✅ Toolbox MCP conectado exitosamente. Herramientas activas ({len(tools)}):"
        )
        for t in tools:
            logger.info(f"   ↳ 🛠️ {t.get('name')}: {t.get('description', '')[:60]}...")
    else:
        logger.warning(
            f"⚠️ No se pudo contactar a Toolbox MCP en {settings.TOOLBOX_URL}. "
            "Asegúrate de que 'toolbox.exe' esté corriendo en la Terminal 1 (puerto 5001)."
        )

    # Verificación del reporte de Monitoreo en Vivo (SharePoint / Excel)
    try:
        from backend.services.monitoreo_service import monitoreo_service
        monitoreo_service.buscar_monitoreo(limit=1)
        p = monitoreo_service._get_excel_path()
        if p and monitoreo_service._cached_records:
            logger.info(
                f"📊 Monitoreo de Transporte (SharePoint) enlazado: '{p.name}' "
                f"({len(monitoreo_service._cached_records)} unidades activas registradas)"
            )
        else:
            logger.warning(
                f"⚠️ Archivo de Monitoreo no cargó registros o no se encontró en: {settings.MONITOREO_EXCEL_PATH}"
            )
    except Exception as em:
        logger.warning(f"Aviso al verificar servicio de monitoreo: {em}")

    yield
    logger.info("🛑 Deteniendo Backend...")


app = FastAPI(
    title="Tottus Logistics AI Agent API",
    description="Backend API Gateway con FastAPI, Gemini 3.5 Flash-Lite y Toolbox MCP sobre BigQuery",
    version="1.0.0",
    lifespan=lifespan,
)

from fastapi.middleware.gzip import GZipMiddleware

# Compresión GZIP automática para acelerar la carga de archivos estáticos y respuestas JSON por el túnel
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configuración de CORS para permitir conexiones desde cualquier frontend (Next.js, React, Swagger UI, Teams)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cache_headers_middleware(request, call_next):
    """Cachea recursos estáticos de /app/ para acelerar la carga en el navegador."""
    response = await call_next(request)
    if request.url.path.startswith("/app/") and any(request.url.path.endswith(ext) for ext in [".js", ".css", ".svg", ".png", ".ico", ".woff2"]):
        response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=3600"
    return response

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, Response

# ------------------------------------------------------------------------------
# Montaje del Frontend (Compatible con Entorno Local y Google Cloud Run)
# Busca automáticamente en múltiples ubicaciones candidatas para máxima portabilidad
# ------------------------------------------------------------------------------
frontend_candidates = [
    Path(__file__).resolve().parent.parent / "frontend",                                    # /app/frontend (En contenedor Docker)
    Path(__file__).resolve().parent.parent / "agente-transporte-front",                     # /app/agente-transporte-front (En contenedor)
    Path(__file__).resolve().parent.parent.parent / "agente-transporte-front",              # ../agente-transporte-front (Entorno de desarrollo local)
    Path("/app/frontend"),                                                                  # Ruta absoluta en contenedor Cloud Run
    Path("/app/agente-transporte-front")                                                    # Alternativa absoluta
]

front_path = None
for candidate in frontend_candidates:
    if candidate.exists() and (candidate / "index.html").exists():
        front_path = candidate
        break

if front_path:
    app.mount(
        "/app", StaticFiles(directory=str(front_path), html=True), name="frontend"
    )
    logger.info(
        f"🌐 Frontend montado exitosamente en: /app/ (sirviendo desde '{front_path}')"
    )
else:
    logger.warning(
        "⚠️ No se encontró la carpeta con el frontend estático. La API operará en modo Headless/Gateway exclusivo."
    )

# Registrar enrutadores oficiales del API (Chat, Health, Tools, Auth)
app.include_router(chat_router)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Devuelve favicon vacío para evitar errores 404 en navegadores."""
    return Response(content=b"", media_type="image/x-icon")


@app.get("/", tags=["General"], summary="Redirección raíz o metadatos del servicio")
async def root():
    """
    Ruta raíz del servicio:
    - Si el frontend está montado, redirige automáticamente a /app/
    - Si no, entrega metadatos descriptivos de la API y enlaces de documentación OpenAPI
    """
    if front_path:
        return RedirectResponse(url="/app/")
    return {
        "service": "Tottus Logistics AI Agent API Gateway",
        "version": "1.0.0",
        "architecture": "Google ADK (Agent Development Kit) + GenAI Toolbox MCP",
        "docs_url": "/docs",
        "health_check": "/api/health",
        "chat_endpoint": "/api/chat",
    }

