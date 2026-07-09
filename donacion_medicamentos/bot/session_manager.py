"""Manejo de sesiones en memoria (antes métodos privados de BotController)."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .constants import SESSION_EXPIRY_HOURS, SessionSteps

logger = logging.getLogger(__name__)


class SessionManager:
    """Gestiona las sesiones activas del bot (estado en memoria)."""

    def __init__(self) -> None:
        self.__sessions: List[Dict[str, Any]] = []

    def create(self, telegram_id: int, documento: Optional[str] = None) -> Dict[str, Any]:
        """Antes: BotController.__create_session"""
        session = {
            "telegram_id": telegram_id,
            "documento": documento,
            "session_data": {
                "documento": documento,
                "nombre": None,
                "direccion_beneficiario": None,
                "medication_count": 0,
                "photos_uploaded": 0,
                "ocr_attempts": 0,
                "doc_attempts": 0,
                "relink_ocr_attempts": 0,
                "pending_medications": [],
                "pending_files": [],
                "documento_relink": None,
                "med_candidates": [],
                "med_search_failures": 0,
            },
            "step": SessionSteps.NEW_USER,
            "is_active": True,
            "is_completed": False,
            "is_cancelled": False,
            "is_error": False,
            "error_message": None,
            "last_activity": datetime.now(),
        }
        self.__sessions.append(session)
        logger.info(f"[{telegram_id}] Nueva sesión creada")
        return session

    def get(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Antes: BotController.__find_active_session"""
        return next(
            (s for s in self.__sessions if s["telegram_id"] == telegram_id and s["is_active"]),
            None
        )

    def update(self, telegram_id: int, step: str,
               session_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Antes: BotController.__update_session"""
        session = self.get(telegram_id)
        if not session:
            session = self.create(telegram_id)
        session["step"] = step
        session["last_activity"] = datetime.now()
        if session_data:
            session["session_data"].update(session_data)
            if "documento" in session_data and session_data["documento"]:
                session["documento"] = session_data["documento"]
        logger.info(f"[{telegram_id}] Sesión actualizada -> Step: {step}")
        return session

    def update_last_activity(self, telegram_id: int) -> None:
        """Antes: BotController.__update_last_activity"""
        session = self.get(telegram_id)
        if session:
            session["last_activity"] = datetime.now()

    def expire(self, telegram_id: int) -> bool:
        """Antes: BotController.__is_session_expired"""
        session = self.get(telegram_id)
        if not session or not session.get("last_activity"):
            return False
        elapsed = datetime.now() - session["last_activity"]
        if elapsed.total_seconds() / 3600 > SESSION_EXPIRY_HOURS:
            logger.info(f"[{telegram_id}] ⏰ Sesión expirada")
            self.finish(telegram_id, error_message="Sesión cerrada por inactividad")
            return True
        return False

    def finish(self, telegram_id: int, error_message: Optional[str] = None) -> None:
        """Antes: BotController.__end_session"""
        session = self.get(telegram_id)
        if session:
            session["is_active"] = False
            session["is_cancelled"] = True
            session["error_message"] = error_message
            session["last_activity"] = None
            logger.info(f"[{telegram_id}] Sesión finalizada: {error_message or 'Usuario cerró sesión'}")
