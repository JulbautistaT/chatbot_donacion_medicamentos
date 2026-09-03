"""Lógica de solicitudes: crear solicitud, consultar, guardar medicamentos y fórmula."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from rapidfuzz import fuzz, process

from django.core import files as django_files
from django.db.models import Count
from django.utils.formats import date_format


from stock import models as stock_models

from .constants import FUZZY_SCORE_THRESHOLD, MAX_SEARCH_RESULTS
from .user import UserService
from .validators import FormulaValidator

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
            stock_models.Solicitud.Estado.ENTREGADA: "📦",
        }
        request_info = f"📋 Tienes <b>{solicitudes.count()}</b> solicitud(es):\n"
        for item in solicitudes.values('estado').annotate(count=Count('estado')).order_by('estado'):
            emoji = estado_emojis.get(item['estado'], "")
            request_info += f"- {emoji} <b>{item['count']}</b> {item['estado'].capitalize()}\n"

        ultima = solicitudes.order_by('-fecha').first()
        if ultima:
            emoji = estado_emojis.get(ultima.estado, "")
            fecha = date_format(ultima.fecha, r"j \d\e F \d\e Y")
            request_info += (
                f"\n🕓 La última solicitud <b>#{ultima.id}</b> del "
                f"<b>{fecha}</b> "
                f"está en estado {emoji} <b>{ultima.estado.capitalize()}</b>."
            )

        return request_info

    # ========== BÚSQUEDA DE MEDICAMENTOS (fuzzy search) ==========

    @staticmethod
    def rank_medications(query: str, meds: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """Lógica pura de ranking (sin BD, testeable).

        meds: lista de {"id", "nombre_comercial", "concentracion"}.
        Devuelve (status, candidatos) donde status ∈ {"ok", "fuzzy", "too_many", "none"}
        y cada candidato es {"id", "label"} con label = "nombre - concentracion".
        """
        query_norm = FormulaValidator.normalize_text(query)
        if not query_norm:
            return "none", []

        def label(m):
            return f"{m['nombre_comercial']} - {m['concentracion']}"

        normalized = [(m, FormulaValidator.normalize_text(m["nombre_comercial"])) for m in meds]

        # 1) Coincidencias exactas/parciales (subcadena sobre texto normalizado)
        partial = [(m, name) for m, name in normalized if query_norm in name]
        if len(partial) > MAX_SEARCH_RESULTS:
            return "too_many", []
        if partial:
            # Primero los que comienzan con la consulta, luego alfabético
            partial.sort(key=lambda t: (not t[1].startswith(query_norm), t[1]))
            return "ok", [{"id": m["id"], "label": label(m)} for m, _ in partial]

        # 2) Búsqueda difusa (errores de escritura)
        choices = {i: name for i, (_, name) in enumerate(normalized)}
        results = process.extract(
            query_norm, choices, scorer=fuzz.WRatio,
            limit=MAX_SEARCH_RESULTS, score_cutoff=FUZZY_SCORE_THRESHOLD,
        )
        if results:
            candidates = [{"id": normalized[key][0]["id"], "label": label(normalized[key][0])}
                          for _, _, key in results]
            return "fuzzy", candidates

        return "none", []

    def search_medications(self, query: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Busca en el inventario por nombre_comercial (parcial + fuzzy)."""
        meds = list(stock_models.Medicamento.objects.values("id", "nombre_comercial", "concentracion"))
        status, candidates = self.rank_medications(query, meds)
        logger.info(f"🔎 Búsqueda de medicamento '{query}': status={status}, candidatos={len(candidates)}")
        return status, candidates

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

        # El archivo ya quedó copiado en MEDIA_ROOT/formulas/: el temporal en
        # BASE_DIR/photos/ sobra y solo duplica espacio en disco.
        try:
            photo_path.unlink()
        except OSError as e:
            logger.warning(f"No se pudo eliminar el temporal {file_path} tras guardarlo en media/formulas/: {e}")
        return formula_obj
