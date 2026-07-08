"""Lógica de solicitudes: crear solicitud, consultar, guardar medicamentos y fórmula."""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from django.core import files as django_files
from django.db.models import Count

from stock import models as stock_models

from .user import UserService

logger = logging.getLogger(__name__)


class RequestService:
    """Operaciones sobre Solicitud / DetalleSolicitud / Formula / Medicamento."""

    def __init__(self, user_service: UserService) -> None:
        self.user_service = user_service

    def commit_full_request(
        self, telegram_id: int, session: Dict[str, Any]
    ) -> Optional[stock_models.Solicitud]:
        """Antes: BotController._commit_full_request"""
        documento = session["session_data"].get("documento")
        if not documento:
            logger.error(f"[{telegram_id}] Commit fallido: no hay documento en sesión")
            return None
        solicitante = self.user_service.get_user_by_document(documento)
        if not solicitante:
            logger.error(f"[{telegram_id}] Commit fallido: solicitante no encontrado")
            return None

        solicitud = stock_models.Solicitud(
            solicitante=solicitante,
            solicitud_propia=True,
            estado=stock_models.Solicitud.Estado.PENDIENTE,
        )
        solicitud.save()
        logger.info(f"[{telegram_id}] ✅ Solicitud creada en BD: {solicitud.id}")

        for item in session["session_data"].get("pending_medications", []):
            try:
                medicamento = stock_models.Medicamento.objects.get(id=item["medication_id"])
                stock_models.DetalleSolicitud(
                    solicitud=solicitud,
                    medicamento=medicamento,
                    cantidad_entregada=0,
                ).save()
                logger.info(f"[{telegram_id}] ✅ Detalle creado: med={item['medication_id']}")
            except stock_models.Medicamento.DoesNotExist:
                logger.error(f"[{telegram_id}] Medicamento {item['medication_id']} no encontrado")
        return solicitud

    def get_request_info(self, session: Dict[str, Any]) -> str:
        """Antes: BotController.get_request_info"""
        documento = session.get("documento") if session else None
        if not documento:
            return "No tienes solicitudes pendientes."
        solicitante = self.user_service.get_user_by_document(documento)
        if not solicitante:
            return "No tienes solicitudes pendientes."
        solicitudes = stock_models.Solicitud.objects.filter(solicitante=solicitante)
        if not solicitudes.exists():
            return "No tienes solicitudes pendientes."

        estado_emojis = {
            stock_models.Solicitud.Estado.PENDIENTE: "⏳",
            stock_models.Solicitud.Estado.RECHAZADA: "❌",
            stock_models.Solicitud.Estado.ACEPTADA: "✅",
        }
        request_info = f"📋 Tienes <b>{solicitudes.count()}</b> solicitudes:\n"
        for item in solicitudes.values('estado').annotate(count=Count('estado')):
            emoji = estado_emojis.get(item['estado'], "")
            request_info += f"- {emoji} <b>{item['count']}</b> {item['estado'].capitalize()}\n"
        ultima = solicitudes.order_by('-fecha').first()
        if ultima:
            emoji = estado_emojis.get(ultima.estado, "")
            request_info += (
                f"\n🕓 La última solicitud <b>#{ultima.id}</b> del <b>{ultima.fecha.strftime('%d de %B de %Y')}</b> "
                f"está en estado {emoji} <b>{ultima.estado.capitalize()}</b>."
            )

        return request_info

    def get_available_medications(self, first_letter: str) -> Optional[str]:
        """Antes: BotController.get_available_medications"""
        medicamentos = stock_models.Medicamento.objects.filter(
            nombre_comercial__istartswith=first_letter
        )
        if not medicamentos.exists():
            return None
        return "\n".join(
            f"{med.id}. {med.nombre_comercial} - {med.concentracion}"
            for med in medicamentos
        )

    def medication_exists(self, selected_id: int, first_letter: str) -> bool:
        """Consulta que antes estaba inline en el paso REQ_MED_LIST_CHOSEN."""
        return stock_models.Medicamento.objects.filter(
            id=selected_id,
            nombre_comercial__istartswith=first_letter
        ).exists()

    def save_formula(
        self, solicitud_obj: stock_models.Solicitud, file_path: str,
        texto_extraido: Optional[str]
    ) -> stock_models.Formula:
        """Guarda la fórmula (archivo + texto OCR). Antes inline en los flujos de fotos.

        Las excepciones se manejan en el llamador, igual que en el original.
        """
        photo_path = Path(file_path)
        with photo_path.open('rb') as pf:
            formula_obj = stock_models.Formula.objects.create(
                solicitud=solicitud_obj,
                archivo_formula=django_files.File(pf, name=photo_path.name),
            )
            if texto_extraido:
                formula_obj.texto_ocr = texto_extraido
                formula_obj.save(update_fields=["texto_ocr"])
        return formula_obj
