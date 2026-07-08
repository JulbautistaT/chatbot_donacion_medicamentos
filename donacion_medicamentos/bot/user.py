"""Lógica de usuarios (Solicitante): buscar, crear, actualizar, revincular."""
import logging
from typing import Any, Dict, Optional, Tuple

from django.db import IntegrityError

from stock import models as stock_models

logger = logging.getLogger(__name__)


class UserService:
    """Operaciones sobre stock_models.Solicitante (antes en BotController)."""

    def get_user_by_document(self, document: str) -> Optional[stock_models.Solicitante]:
        try:
            return stock_models.Solicitante.objects.get(documento=document)
        except stock_models.Solicitante.DoesNotExist:
            return None

    def get_user_secure(
        self, telegram_id: int, document_number: str
    ) -> Tuple[Optional[stock_models.Solicitante], str]:
        user_by_doc = self.get_user_by_document(document_number)
        if not user_by_doc:
            return None, 'not_found'
        if user_by_doc.telegram_id == str(telegram_id):
            return user_by_doc, 'owner'
        logger.warning(f"[{telegram_id}] 🔒 Intento de acceso a documento ajeno: {document_number}")
        return None, 'forbidden'

    def create_user(self, telegram_id: int, session_data: Dict[str, Any]) -> stock_models.Solicitante:
        try:
            solicitante = stock_models.Solicitante(
                nombre=session_data.get("nombre"),
                documento=session_data.get("documento"),
                telegram_id=str(telegram_id),
                telefono=session_data.get("telefono"),
                direccion_beneficiario=session_data.get("direccion_beneficiario"),
            )
            solicitante.save()
            logger.info(f"[{telegram_id}] Usuario creado: {solicitante.id}")
            return solicitante
        except IntegrityError as e:
            # NOTA: en el original IntegrityError no estaba importado (NameError latente);
            # se agrega el import sin cambiar la lógica.
            logger.error(f"[{telegram_id}] IntegrityError al crear usuario: {e}")
            raise

    def update_user(self, solicitante: stock_models.Solicitante, session_data: Dict[str, Any]) -> bool:
        changed = False
        for field in ("nombre", "direccion_beneficiario", "telefono"):
            val = session_data.get(field)
            if val is not None and getattr(solicitante, field) != val:
                setattr(solicitante, field, val)
                changed = True
        if changed:
            solicitante.save()
            logger.info(f"Usuario {solicitante.id} actualizado")
        return changed

    def relink_telegram_id(
        self, solicitante: stock_models.Solicitante, new_telegram_id: int
    ) -> None:
        old_id = solicitante.telegram_id
        solicitante.telegram_id = str(new_telegram_id)
        solicitante.save(update_fields=["telegram_id"])
        logger.info(
            f"[{new_telegram_id}] 🔗 telegram_id revinculado: {old_id} -> {new_telegram_id} "
            f"para documento {solicitante.documento}"
        )

    def mark_verified(self, telegram_id: int, document: str) -> None:
        """Marca al solicitante como verificado (antes inline en el flujo de fotos)."""
        try:
            solicitante = self.get_user_by_document(document)
            if solicitante and not solicitante.verificado:
                solicitante.verificado = True
                solicitante.save(update_fields=["verificado"])
        except Exception as e:
            logger.warning(f"[{telegram_id}] Error actualizando 'verificado': {e}")
