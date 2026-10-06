from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class VerifyRequest(BaseModel):
    """Payload para verificar credenciales de acceso (email y clave de piloto)."""
    email: str = Field(..., description="Correo institucional @tottus.com.pe")
    key: str = Field(..., description="Clave de acceso de piloto o token de Google")

class VerifyResponse(BaseModel):
    """Respuesta de verificación de credenciales."""
    status: str = Field(..., example="ok")
    message: str = Field(..., example="Credenciales válidas")
    email: str = Field(..., example="fhurtadoa@tottus.com.pe")

class ChatRequest(BaseModel):
    """Payload de entrada para enviar un mensaje al agente logístico."""
    message: str = Field(..., description="Pregunta del usuario en lenguaje natural", example="¿Qué productos y despachos hay en el TIM 655423616?")
    session_id: Optional[str] = Field(default=None, description="Identificador único de sesión conversacional")
    tienda_id: Optional[str] = Field(default=None, description="Código de la tienda (ej. '123', '114') si se conoce")
    user_email: Optional[str] = Field(default=None, description="Correo corporativo del usuario autenticado para control de acceso RBAC")
    pais: Optional[str] = Field(default="PE", description="Código del país ('PE' o 'CL')")
    token: Optional[str] = Field(default=None, description="Token o clave de acceso del piloto (evita header Authorization y CORS preflight)")
    include_data: bool = Field(default=False, description="Si es True, incluye las filas crudas de BigQuery en el campo 'data'. Por defecto False para ahorrar ancho de banda.")

class ToolExecution(BaseModel):
    """Registro de trazabilidad de una herramienta MCP ejecutada por el agente."""
    tool_name: str = Field(..., description="Nombre de la herramienta MCP invocada")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Parámetros enviados a la herramienta")
    result_count: int = Field(default=0, description="Cantidad de registros devueltos por BigQuery")
    preview: Optional[Any] = Field(default=None, description="Vista previa de los datos obtenidos")

class ChatResponse(BaseModel):
    """Respuesta generada por el agente para el cliente (FastAPI / Frontend / Teams)."""
    answer: str = Field(..., description="Explicación analítica y respuesta en lenguaje natural generada por Gemini")
    session_id: str = Field(..., description="ID de sesión para mantener el hilo de la conversación")
    tools_executed: List[ToolExecution] = Field(default_factory=list, description="Lista de herramientas MCP que Gemini decidió usar")
    data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Datos crudos obtenidos de BigQuery para renderizado de tablas en el frontend")

class ToolInfo(BaseModel):
    """Información de una herramienta registrada en el servidor MCP."""
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None

class HealthResponse(BaseModel):
    """Respuesta de salud y diagnóstico del backend."""
    status: str
    toolbox_url: str
    toolbox_connected: bool
    tools_available: List[str]
    model: str

class SessionSummary(BaseModel):
    """Resumen de sesión conversacional y trazabilidad de auditoría."""
    session_id: str
    created_at: str
    updated_at: str
    user_email: Optional[str] = None
    last_tienda: Optional[str] = None
    total_turns: int

class SessionDetail(BaseModel):
    """Detalle completo del resguardo de una sesión conversacional."""
    session_id: str
    created_at: str
    updated_at: str
    user_email: Optional[str] = None
    pais: str = "PE"
    last_tienda: Optional[str] = None
    total_queries: int
    turns: List[Dict[str, Any]]
