import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("backend.session_manager")

class SessionManager:
    """
    Gestor de Sesiones y Auditoría con Mejores Prácticas de Resguardo de Datos.
    
    Características clave:
    1. Sanitización estricta de session_id (protección contra Path Traversal e inyección).
    2. Resguardo persistente en disco (JSON estructurado) de todas las consultas y respuestas.
    3. Trazabilidad completa para auditoría: timestamp, usuario, tienda, herramientas ejecutadas y recuento de registros.
    4. Caché de alta velocidad en memoria con recarga automática desde disco si el servidor se reinicia.
    5. Ventana deslizante para el LLM para evitar desbordamiento de tokens manteniendo el resguardo completo en archivo.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            # agent-test/data/sessions/
            self.storage_dir = Path(__file__).resolve().parent.parent.parent / "data" / "sessions"
        else:
            self.storage_dir = Path(storage_dir)

        # Crear directorio de resguardo si no existe
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"💾 Almacén de resguardo de sesiones activo en: {self.storage_dir}")

        # Caché rápida en memoria {session_id: dict}
        self._cache: Dict[str, Dict[str, Any]] = {}

    def sanitize_session_id(self, session_id: Optional[str]) -> str:
        """
        Sanitiza el session_id para asegurar que sea seguro contra Path Traversal
        y nombres de archivo inválidos en Windows/Linux.
        """
        if not session_id or not isinstance(session_id, str):
            return f"sess_{uuid.uuid4().hex[:12]}"
        
        # Permitir solo caracteres alfanuméricos, guiones y guiones bajos
        clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', session_id.strip())
        
        # Limitar longitud para evitar abusos de memoria o límites de OS
        clean = clean[:64]
        
        if not clean or clean == "_" or clean.startswith("."):
            return f"sess_{uuid.uuid4().hex[:12]}"
            
        return clean

    def _get_file_path(self, safe_session_id: str) -> Path:
        return self.storage_dir / f"{safe_session_id}.json"

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        user_email: Optional[str] = None,
        pais: str = "PE"
    ) -> Dict[str, Any]:
        """Recupera la sesión de la memoria o disco, o la inicializa si es nueva."""
        safe_id = self.sanitize_session_id(session_id)

        # 1. Buscar en caché en memoria
        if safe_id in self._cache:
            session = self._cache[safe_id]
            if user_email and not session.get("user_email"):
                session["user_email"] = user_email
            return session

        # 2. Buscar en disco persistente
        file_path = self._get_file_path(safe_id)
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    session = json.load(f)
                    self._cache[safe_id] = session
                    logger.info(f"📂 Sesión '{safe_id}' restaurada exitosamente desde disco ({len(session.get('turns', []))} turnos)")
                    return session
            except Exception as e:
                logger.warning(f"⚠️ No se pudo leer el archivo de sesión {file_path}: {e}")

        # 3. Crear nueva estructura de sesión bajo estándares de auditoría
        now_iso = datetime.now(timezone.utc).isoformat()
        new_session = {
            "session_id": safe_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "user_email": user_email or "supervisor@tottus.com.pe",
            "pais": pais,
            "last_tienda": None,
            "total_queries": 0,
            "turns": []
        }
        self._cache[safe_id] = new_session
        self._persist_to_disk(new_session)
        return new_session

    def get_last_tienda(self, session_id: str) -> Optional[str]:
        """Obtiene la última tienda asociada a esta sesión conversacional."""
        safe_id = self.sanitize_session_id(session_id)
        session = self.get_or_create_session(safe_id)
        return session.get("last_tienda")

    def set_last_tienda(self, session_id: str, tienda: str):
        """Registra la tienda activa en el estado de la sesión."""
        safe_id = self.sanitize_session_id(session_id)
        session = self.get_or_create_session(safe_id)
        session["last_tienda"] = str(tienda)
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._persist_to_disk(session)

    def get_recent_history_for_llm(self, session_id: str, max_turns: int = 6) -> List[Dict[str, str]]:
        """
        Retorna los últimos N turnos formateados para contexto de Gemini:
        [{"role": "user", "text": "..."}, {"role": "model", "text": "..."}]
        """
        safe_id = self.sanitize_session_id(session_id)
        session = self.get_or_create_session(safe_id)
        turns = session.get("turns", [])
        
        recent = turns[-max_turns:] if len(turns) > max_turns else turns
        history = []
        for t in recent:
            if t.get("user_message"):
                history.append({"role": "user", "text": t["user_message"]})
            if t.get("ai_response"):
                history.append({"role": "model", "text": t["ai_response"]})
        return history

    def record_turn(
        self,
        session_id: str,
        user_message: str,
        ai_response: str,
        tools_executed: Optional[List[Any]] = None,
        records_count: int = 0,
        tienda_id: Optional[str] = None,
        user_email: Optional[str] = None,
        pais: Optional[str] = "PE",
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Registra y resguarda un turno completo con todos sus metadatos y trazabilidad.
        """
        safe_id = self.sanitize_session_id(session_id)
        session = self.get_or_create_session(safe_id, user_email=user_email, pais=pais or "PE")
        
        now_iso = datetime.now(timezone.utc).isoformat()
        session["updated_at"] = now_iso
        session["total_queries"] = session.get("total_queries", 0) + 1

        if tienda_id:
            session["last_tienda"] = str(tienda_id)
        if user_email:
            session["user_email"] = user_email

        # Formatear herramientas ejecutadas para auditoría
        formatted_tools = []
        if tools_executed:
            for t in tools_executed:
                if hasattr(t, "model_dump"):
                    formatted_tools.append(t.model_dump())
                elif hasattr(t, "dict"):
                    formatted_tools.append(t.dict())
                elif isinstance(t, dict):
                    formatted_tools.append(t)
                else:
                    formatted_tools.append({"tool_name": str(t)})

        turn_entry = {
            "turn_index": len(session.get("turns", [])) + 1,
            "timestamp": now_iso,
            "user_message": user_message,
            "ai_response": ai_response,
            "tienda_context": session.get("last_tienda"),
            "tools_executed": formatted_tools,
            "records_count": records_count,
            "error": error
        }

        session.setdefault("turns", []).append(turn_entry)
        self._persist_to_disk(session)
        logger.info(f"✅ [Resguardo Auditoría] Turno #{turn_entry['turn_index']} guardado para sesión '{safe_id}' (registros={records_count})")
        return session

    def _persist_to_disk(self, session: Dict[str, Any]):
        """Persiste la sesión de forma atómica y segura en archivo JSON."""
        safe_id = session.get("session_id", "default")
        file_path = self._get_file_path(safe_id)
        temp_path = file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
            temp_path.replace(file_path)
        except Exception as e:
            logger.error(f"❌ Error al guardar resguardo de sesión en {file_path}: {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def delete_session(self, session_id: str) -> bool:
        """Elimina una sesión tanto de la memoria como del disco de resguardo."""
        safe_id = self.sanitize_session_id(session_id)
        self._cache.pop(safe_id, None)
        file_path = self._get_file_path(safe_id)
        if file_path.exists():
            try:
                file_path.unlink()
                logger.info(f"🗑️ Sesión de resguardo '{safe_id}' eliminada.")
                return True
            except Exception as e:
                logger.error(f"Error al eliminar archivo de sesión {file_path}: {e}")
                return False
        return True

    def list_recent_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista el resumen de las sesiones recientes para auditoría y monitoreo."""
        results = []
        try:
            for p in self.storage_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        results.append({
                            "session_id": data.get("session_id"),
                            "created_at": data.get("created_at"),
                            "updated_at": data.get("updated_at"),
                            "user_email": data.get("user_email"),
                            "last_tienda": data.get("last_tienda"),
                            "total_turns": len(data.get("turns", [])),
                        })
                except Exception:
                    continue
            results.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error(f"Error al listar sesiones: {e}")
            return []

# Instancia singleton del gestor de sesiones
session_manager = SessionManager()
