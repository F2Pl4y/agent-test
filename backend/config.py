import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env ubicado en la raíz del proyecto
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Settings:
    # URL del servidor MCP Toolbox
    TOOLBOX_URL: str = os.getenv("TOOLBOX_URL", "http://localhost:5001/mcp")
    
    # Proyectos GCP
    BIGQUERY_PROJECT: str = os.getenv("BIGQUERY_PROJECT", "tot-corp-plo-sbx")
    VERTEXAI_PROJECT: str = os.getenv("VERTEXAI_PROJECT", "tot-bi-corp-arq-dev")
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    # Configuración de Gemini LLM
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    USE_VERTEXAI: bool = os.getenv("USE_VERTEXAI", "true").lower() in ("true", "1", "yes")

settings = Settings()
