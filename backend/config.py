import os
from typing import List
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env ubicado en la raíz del proyecto
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)


class Settings:
    """
    Configuración Centralizada del Sistema (Arquitectura Google ADK / GCP).
    
    Permite el desacoplamiento total entre código y configuración mediante:
    1. Archivo local .env (en desarrollo).
    2. Variables de entorno inyectadas por Google Cloud Run (en producción).
    """

    # URL del servidor MCP Toolbox (Go binary en local o servicio Cloud Run en GCP)
    TOOLBOX_URL: str = os.getenv("TOOLBOX_URL", "http://localhost:5001/mcp")

    # Ubicación geográfica de los recursos de IA en Google Cloud (por defecto us-central1)
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    @property
    def BIGQUERY_PROJECT(self) -> str:
        """Proyecto de Google Cloud donde reside el dataset y la tabla particionada de BigQuery."""
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("BIGQUERY_PROJECT", "tot-corp-plo-sbx").strip()

    @property
    def VERTEXAI_PROJECT(self) -> str:
        """Proyecto de Google Cloud para invocar Gemini a través de Vertex AI."""
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("VERTEXAI_PROJECT", "tot-corp-plo-sbx").strip()

    @property
    def GEMINI_MODEL(self) -> str:
        """
        Modelo de lenguaje orquestador de Google Gemini.
        Por defecto 'gemini-3.5-flash-lite' para máxima velocidad y eficiencia de costos.
        """
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

    @property
    def GEMINI_API_KEY(self) -> str:
        """Clave de API para desarrollo directo con Google AI Studio (opcional en Cloud Run)."""
        load_dotenv(dotenv_path=env_path, override=True)
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if key.startswith("AIzaSyTuClavePersonalAqui"):
            return ""
        return key

    @property
    def USE_VERTEXAI(self) -> bool:
        """
        Modo de inferencia de IA:
        - True (Producción en Cloud Run): Utiliza Vertex AI con credenciales de cuenta de servicio GCP.
        - False (Desarrollo local): Utiliza Gemini API Key directa de Google AI Studio.
        """
        load_dotenv(dotenv_path=env_path, override=True)
        explicit = os.getenv("USE_VERTEXAI")
        if explicit is not None:
            return explicit.strip().lower() in ("true", "1", "yes")
        # Si no está explícito en el .env, priorizar API Key si existe; si no, Vertex AI
        return not bool(self.GEMINI_API_KEY)

    @property
    def PILOT_ACCESS_KEY(self) -> str:
        """Clave de acceso secreta compartida para el piloto operativo de Tottus Perú."""
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("PILOT_ACCESS_KEY", "D4t4-PL$2026").strip()

    @property
    def GOOGLE_CLIENT_ID(self) -> str:
        """Client ID de Google Identity Services para autenticación OAuth 2.0 en producción."""
        load_dotenv(dotenv_path=env_path, override=True)
        return os.getenv("GOOGLE_CLIENT_ID", "").strip()

    @property
    def ALLOWED_USERS(self) -> List[str]:
        """
        Lista Blanca de Control de Acceso Basado en Roles (Whitelist RBAC).
        - Si contiene 'all_users', permite acceso libre a cualquier cuenta corporativa @tottus.com.pe.
        - Si contiene correos específicos, restringe el acceso exclusivamente a esas cuentas autorizadas.
        """
        load_dotenv(dotenv_path=env_path, override=True)
        raw = os.getenv("ALLOWED_USERS", "").strip()
        if raw.lower() == "all_users":
            return ["all_users"]
        cleaned = (
            raw.replace('"', "").replace("'", "").replace("\r", "").replace("\n", ",")
        )
        return [u.strip().lower() for u in cleaned.split(",") if u.strip()]


settings = Settings()
