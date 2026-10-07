# ==============================================================================
# Dockerfile para Google Cloud Run — Asistente de Transporte Tottus Perú
# Estándar oficial Google ADK + FastAPI + Uvicorn
# ==============================================================================

# Imagen base ligera oficial de Python optimizada para contenedores en GCP
FROM python:3.11-slim

# Variables de entorno para ejecución sin buffering y puerto Cloud Run dinámico
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Instalar certificados raíz y herramientas de red esenciales
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python (FastAPI, Google GenAI SDK, Google ADK, httpx, etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del backend y configuraciones
COPY backend/ ./backend/
COPY toolbox/ ./toolbox/

# Copiar el frontend para que FastAPI lo sirva automáticamente en /app/
# (Si la carpeta existe en el contexto de compilación se copia; si no, el backend funciona en modo API Gateway)
COPY frontend/ ./frontend/

# Exponer el puerto estándar de Cloud Run (8080 por defecto)
EXPOSE 8080

# Iniciar servidor Uvicorn escuchando en el puerto asignado por Cloud Run ($PORT)
CMD exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1