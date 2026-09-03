"""Flujo de fotos/OCR: subida de archivos, validación de la fórmula y commit."""
import asyncio
import logging
import os

from telegram import ForceReply, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from ..constants import MAX_MEDICATIONS, MAX_OCR_ATTEMPTS, SessionSteps
from ..keyboards import retry_photo_keyboard
from ..ocr import OCRService
from ..request import RequestService
from ..session_manager import SessionManager
from ..user import UserService

logger = logging.getLogger(__name__)


class PhotoFlow:
    """Pasos REQ_PHOTO, REQ_PHOTO_VALIDATION y REQ_MORE_PHOTOS
    (antes en request_session_step y process_multiple_files_with_validation)."""

    def __init__(self, session_manager: SessionManager, user_service: UserService,
                 request_service: RequestService, ocr_service: OCRService) -> None:
        self.sessions = session_manager
        self.users = user_service
        self.requests = request_service
        self.ocr = ocr_service

    @staticmethod
    def _discard_file(path: str) -> None:
        """Borra un archivo temporal de photos/ que ya no se va a usar (intento
        rechazado o reemplazado por uno más nuevo)."""
        try:
            os.remove(path)
        except OSError as e:
            logger.warning(f"No se pudo eliminar el temporal {path}: {e}")

    async def process_multiple_files_with_validation(
        self, update: Update, telegram_id: int, session: dict
    ) -> None:
        """Antes: BotController.process_multiple_files_with_validation"""
        file_path = await self.ocr.download_file(update)
        if not file_path:
            await update.message.reply_text("❌ Error al recibir el archivo. Intenta nuevamente.")
            return

        # Cada intento reemplaza al anterior (no se combinan varias fotos): el
        # intento previo, si lo hay, ya perdió su validez y no aporta nada.
        for old_path in session["session_data"].get("pending_files", []):
            self._discard_file(old_path)
        session["session_data"]["pending_files"] = [file_path]
        session["session_data"]["photos_uploaded"] = session["session_data"].get("photos_uploaded", 0) + 1

        await asyncio.sleep(1.5)
        await update.message.reply_text(
            "🔍 Analizando documento(s), por favor espera...\n"
            "Este proceso puede tardar unos minutos, te notificaremos cuando terminemos de analizarlo.",
            reply_markup=ReplyKeyboardRemove()
        )

        combined_text = await asyncio.to_thread(
            self.ocr.process_recipe, session["session_data"].get("pending_files", [])
        )

        session["session_data"]["ocr_attempts"] = session["session_data"].get("ocr_attempts", 0) + 1
        current_attempt = session["session_data"]["ocr_attempts"]

        if not combined_text or len(combined_text) < 50:
            # Intento rechazado (no se pudo leer texto): el archivo no sirve para nada más.
            for fp in session["session_data"].get("pending_files", []):
                self._discard_file(fp)
            session["session_data"]["pending_files"] = []

            if current_attempt >= MAX_OCR_ATTEMPTS:
                await update.message.reply_text(
                    "❌ No se pudo leer el texto del documento después de 2 intentos.\n\n"
                    "Vamos a continuar describiendo los medicamentos manualmente.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.sessions.update(telegram_id, SessionSteps.REQ_MED_COUNT, session["session_data"])
                await update.message.reply_text(
                    f"🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
            else:
                await update.message.reply_text(
                    "❌ No se pudo leer el texto del documento. La imagen puede estar borrosa o en mal estado.\n\n"
                    f"📷 Tienes {MAX_OCR_ATTEMPTS - current_attempt} intento(s) más.\n\n"
                    "¿Qué deseas hacer?",
                    reply_markup=retry_photo_keyboard()
                )
                self.sessions.update(telegram_id, SessionSteps.REQ_PHOTO_VALIDATION, session["session_data"])
            return

        expected_document = session["session_data"].get("documento")
        expected_name = session["session_data"].get("nombre")
        validation_result = self.ocr.validate_recipe(combined_text, expected_document, expected_name)
        logger.info(f"[{telegram_id}] Validación OCR intento {current_attempt}: {validation_result}")

        if validation_result['is_valid']:
            solicitud_obj = self.requests.commit_full_request(telegram_id, session)
            if not solicitud_obj:
                await update.message.reply_text(
                    "❌ Error al guardar la solicitud. Intenta más tarde.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.sessions.finish(telegram_id, "Error en commit de solicitud")
                return

            # Solo se conserva el último archivo (el que validó); cualquier otro
            # remanente en pending_files se descarta sin guardarlo.
            pending = session["session_data"].get("pending_files", [])
            if pending:
                final_file = pending[-1]
                for fp in pending[:-1]:
                    self._discard_file(fp)
                try:
                    texto_extraido = await asyncio.to_thread(self.ocr.extract_text, final_file)
                    self.requests.save_formula(solicitud_obj, final_file, texto_extraido)
                except Exception as e:
                    logger.warning(f"[{telegram_id}] Error guardando archivo en commit: {e}")

            self.users.mark_verified(telegram_id, expected_document)

            await update.message.reply_html(
                f"📋 Documento: Verificado\n"
                f"👤 Nombre: Verificado\n\n"
                f"✅ ¡Gracias! Hemos recibido todos tus archivos y tu solicitud fue registrada con el número <b>#{solicitud_obj.id}</b>.\n"
                f"Te notificaremos cuando esté lista.",
                reply_markup=ReplyKeyboardRemove()
            )
            self.sessions.finish(telegram_id, "Solicitud completada exitosamente")

        else:
            doc_status = "✅ Verificado" if validation_result['document_match'] else "❌ No verificado"
            name_status = "✅ Verificado" if validation_result['name_match'] else "❌ No verificado"

            # Intento rechazado (documento/nombre no coinciden): el archivo no sirve para nada más.
            for fp in session["session_data"].get("pending_files", []):
                self._discard_file(fp)
            session["session_data"]["pending_files"] = []

            if current_attempt >= MAX_OCR_ATTEMPTS:
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    f"⚠️ No se pudo validar después de {MAX_OCR_ATTEMPTS} intentos.\n\n"
                    "Vamos a continuar describiendo los medicamentos manualmente.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.sessions.update(telegram_id, SessionSteps.REQ_MED_COUNT, session["session_data"])
                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {MAX_MEDICATIONS} medicamentos.\n\n"
                    "Escribe una cantidad de 1 a 4.\n\n"
                    "Ejemplo: <code>2</code>",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    "⚠️ Por favor corrige o revisa la imagen.\n\n"
                    f"📷 Tienes {MAX_OCR_ATTEMPTS - current_attempt} intento(s) más.\n\n"
                    "¿Qué deseas hacer?",
                    reply_markup=retry_photo_keyboard()
                )
                self.sessions.update(telegram_id, SessionSteps.REQ_PHOTO_VALIDATION, session["session_data"])

    # ── REQ_PHOTO_VALIDATION ──────────────────────────────────────────────
    async def req_photo_validation(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        if "foto" in text_lower or "intentar" in text_lower or "otra" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_PHOTO, session["session_data"])
            await update.message.reply_text(
                "📷 Por favor, sube otra foto más clara de la fórmula médica.\n\n"
                "💡 Asegúrate de que:\n"
                "  • La imagen esté bien iluminada\n"
                "  • El texto sea legible\n"
                "  • No esté borrosa\n\n",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
            return
        if "describir" in text_lower or "manual" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_COUNT, {})
            await update.message.reply_text(
                "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                f"Recuerda que puedes solicitar hasta {MAX_MEDICATIONS} medicamentos.\n\n"
                "Escribe una cantidad de 1 a 4.\n\n"
                "Ejemplo: <code>2</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return
        await update.message.reply_text(
            "Por favor selecciona una opción válida.",
            reply_markup=retry_photo_keyboard()
        )

    # ── REQ_PHOTO ─────────────────────────────────────────────────────────
    async def req_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                        telegram_id: int, session: dict, text: str) -> bool:
        """Devuelve False si el mensaje no es foto/documento/texto: en el original
        ese caso caía al bloque de 'PASO INESPERADO' (se preserva ese comportamiento)."""
        if update.message.document or update.message.photo:
            await self.process_multiple_files_with_validation(update, telegram_id, session)
            return True
        elif text:
            text_lower = text.lower()
            if "describir" in text_lower or "manual" in text_lower:
                self.sessions.update(telegram_id, SessionSteps.REQ_MED_COUNT, {})
                await update.message.reply_text(
                    "📝 Entendido. Vamos a describir los medicamentos manualmente.\n\n"
                    "🔢 ¿Cuántos medicamentos vas a solicitar?",
                    reply_markup=ForceReply(selective=True)
                )
                return True
            await update.message.reply_text(
                "📄 Por favor sube una foto o PDF de la fórmula médica.\n\n"
                "⚠️ Recuerda enviarlo como <b>Archivo</b> (📎 adjunto).",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return True
        return False

    # ── REQ_MORE_PHOTOS ───────────────────────────────────────────────────
    async def req_more_photos(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                              telegram_id: int, session: dict, text: str) -> bool:
        """Devuelve False si el mensaje no es foto/documento/texto (ver req_photo)."""
        if update.message.document or update.message.photo:
            file_path = await self.ocr.download_file(update)
            if not file_path:
                await update.message.reply_text(
                    "❌ Error al recibir el archivo. Intenta nuevamente.",
                    reply_markup=ForceReply(selective=True)
                )
                return True

            solicitud_obj = self.requests.commit_full_request(telegram_id, session)
            if not solicitud_obj:
                await update.message.reply_text(
                    "❌ Error al guardar la solicitud. Intenta más tarde.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.sessions.finish(telegram_id, "Error en commit de solicitud (flujo manual)")
                return True

            try:
                texto_extraido = await asyncio.to_thread(self.ocr.extract_text, file_path)
                self.requests.save_formula(solicitud_obj, file_path, texto_extraido)
                if texto_extraido:
                    logger.info(f"[{telegram_id}] OCR interno guardado ({len(texto_extraido)} chars)")
            except Exception as e:
                logger.warning(f"[{telegram_id}] Error guardando archivo en flujo manual: {e}")

            self.sessions.finish(telegram_id, "Flujo manual completado")
            await update.message.reply_html(
                f"✅ ¡Gracias! Hemos recibido todos tus archivos y tu solicitud fue registrada con el número <b>#{solicitud_obj.id}</b>.\n"
                f"Te notificaremos cuando esté lista.",
                reply_markup=ReplyKeyboardRemove()
            )
            return True
        elif text:
            await update.message.reply_text(
                "📄 Por favor sube la foto o PDF de la fórmula médica.\n\n"
                "⚠️ Recuerda enviarlo como <b>Archivo</b> (📎 adjunto).",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return True
        return False
