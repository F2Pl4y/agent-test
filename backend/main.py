import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.chat import router as chat_router
from backend.agents._shared.loader import mcp_client
from backend.config import settings

# Configuración de Logging estructurado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backend.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida del servidor: verifica conectividad con Toolbox MCP al iniciar."""
    logger.info("🚀 Iniciando Backend del Agente Logístico Tottus...")
    logger.info(f"📡 Conectando a Toolbox MCP en: {settings.TOOLBOX_URL}")
    
    is_up = await mcp_client.check_health()
    if is_up:
        tools = await mcp_client.list_tools()
        logger.info(f"✅ Toolbox MCP conectado exitosamente. Herramientas activas ({len(tools)}):")
        for t in tools:
            logger.info(f"   ↳ 🛠️ {t.get('name')}: {t.get('description', '')[:60]}...")
    else:
        logger.warning(
            f"⚠️ No se pudo contactar a Toolbox MCP en {settings.TOOLBOX_URL}. "
            "Asegúrate de que 'toolbox.exe' esté corriendo en la Terminal 1 (puerto 5001)."
        )
    
    yield
    logger.info("🛑 Deteniendo Backend...")

app = FastAPI(
    title="Tottus Logistics AI Agent API",
    description="Backend API Gateway con FastAPI, Gemini 3.5 Flash-Lite y Toolbox MCP sobre BigQuery",
    version="1.0.0",
    lifespan=lifespan
)

# Configuración de CORS para permitir conexiones desde cualquier frontend (Next.js, React, Swagger UI, Teams)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

# Ruta al repositorio frontend agente-transporte-front
front_path = Path(__file__).resolve().parent.parent.parent / "agente-transporte-front"
if front_path.exists():
    app.mount("/app", StaticFiles(directory=str(front_path), html=True), name="frontend")
    logger.info(f"🌐 Frontend montado en: http://localhost:8000/app/ (desde {front_path})")

# Registrar las rutas del API
app.include_router(chat_router)

from fastapi.responses import Response

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=b"", media_type="image/x-icon")

@app.get("/", tags=["General"])
async def root():
    if front_path.exists():
        return RedirectResponse(url="/app/")
    return {
        "message": "Bienvenido al Backend del Agente Logístico Tottus",
        "docs_url": "/docs",
        "health_check": "/api/health",
        "chat_endpoint": "/api/chat"
    }
