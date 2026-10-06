import os
from typing import List
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env ubicado en la raíz del proyecto
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)


class Settings:
    # URL del servidor MCP Toolbox
    TOOLBOX_URL: str = os.getenv("TOOLBOX_URL", "http://localhost:5001/mcp")

    # Proyectos GCP (leídos dinámicamente desde el archivo local .env)
    @property
    def BIGQUERY_PROJECT(self) -> str:
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("BIGQUERY_PROJECT", "").strip()

    @property
    def VERTEXAI_PROJECT(self) -> str:
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("VERTEXAI_PROJECT", "").strip()

    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    @property
    def GEMINI_MODEL(self) -> str:
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

    @property
    def GEMINI_API_KEY(self) -> str:
        # Recargar siempre .env por si se modificó en caliente
        load_dotenv(dotenv_path=env_path, override=True)
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if key.startswith("AIzaSyTuClavePersonalAqui"):
            return ""
        return key

    @property
    def USE_VERTEXAI(self) -> bool:
        load_dotenv(dotenv_path=env_path, override=True)
        explicit = os.getenv("USE_VERTEXAI")
        if explicit is not None:
            return explicit.strip().lower() in ("true", "1", "yes")
        # Si no está explícito en el .env, priorizar API Key si existe
        return not bool(self.GEMINI_API_KEY)

    @property
    def PILOT_ACCESS_KEY(self) -> str:
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("PILOT_ACCESS_KEY", "D4t4-PL$2026").strip()

    @property
    def GOOGLE_CLIENT_ID(self) -> str:
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("GOOGLE_CLIENT_ID", "").strip()

    @property
    def ALLOWED_USERS(self) -> List[str]:
        load_dotenv(dotenv_path=env_path, override=True)
        raw = os.getenv("ALLOWED_USERS", "").strip()
        # Solo se libera el acceso a todos si se escribe explícitamente 'all_users'
        if raw.lower() == "all_users":
            return ["all_users"]
        # Limpiar comillas, retornos de carro y saltos de línea
        cleaned = (
            raw.replace('"', "").replace("'", "").replace("\r", "").replace("\n", ",")
        )
        return [u.strip().lower() for u in cleaned.split(",") if u.strip()]


settings = Settings()
