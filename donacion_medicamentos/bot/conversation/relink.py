"""Flujo de revinculación de cuenta de Telegram por OCR del documento de identidad."""
import asyncio
import logging

from telegram import ForceReply, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from ..constants import MAX_OCR_ATTEMPTS, SessionSteps
from ..keyboards import known_user_keyboard, yes_no_keyboard
from ..ocr import OCRService
from ..session_manager import SessionManager
from ..user import UserService

logger = logging.getLogger(__name__)


class RelinkFlow:
    """Pasos REQ_RELINK_CONFIRM y REQ_RELINK_DOCUMENT (antes en request_session_step)."""

    def __init__(self, session_manager: SessionManager, user_service: UserService,
                 ocr_service: OCRService) -> None:
        self.sessions = session_manager
        self.users = user_service
        self.ocr = ocr_service

    # ── REQ_RELINK_CONFIRM ────────────────────────────────────────────────
    async def req_relink_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        if "no" in text_lower or "corregir" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_DOCUMENT, {"documento_relink": None})
            await update.message.reply_text(
                "Entendido. Por favor escribe nuevamente tu número de documento.",
                reply_markup=ForceReply(selective=True)
            )
            return
        if "sí" in text_lower or "si" in text_lower or "mío" in text_lower or "mio" in text_lower:
            documento_relink = session["session_data"].get("documento_relink")
            self.sessions.update(
                telegram_id, SessionSteps.REQ_RELINK_DOCUMENT,
                {"documento_relink": documento_relink, "relink_ocr_attempts": 0}
            )
            await update.message.reply_text(
                "📷 Para verificar que eres el titular, sube una foto clara "
                "de tu documento de identidad.\n\n"
                "💡 Asegúrate de que se vean claramente:\n"
                "  • Tu nombre completo\n"
                "  • Tu número de documento\n\n"
                "⚠️ Envíalo como <b>Archivo</b> (📎 adjunto), no como foto.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
            return
        await update.message.reply_text(
            "Por favor selecciona una opción válida.",
            reply_markup=yes_no_keyboard("Sí, es el mío ✅", "No, corregir ✏️")
        )

    # ── REQ_RELINK_DOCUMENT ───────────────────────────────────────────────
    async def req_relink_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  telegram_id: int, session: dict, text: str) -> None:
        if not (update.message.document or update.message.photo):
            await update.message.reply_text(
                "📄 Por favor sube una foto o PDF de tu documento de identidad.\n\n"
                "⚠️ Recuerda enviarlo como <b>Archivo</b> (📎 adjunto).",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return

        file_path = await self.ocr.download_file(update)
        if not file_path:
            await update.message.reply_text("❌ Error al recibir el archivo. Intenta nuevamente.")
            return

        await asyncio.sleep(1.5)
        await update.message.reply_text(
            "🔍 Verificando tu documento de identidad, por favor espera...",
            reply_markup=ReplyKeyboardRemove()
        )

        relink_attempt = session["session_data"].get("relink_ocr_attempts", 0) + 1
        session["session_data"]["relink_ocr_attempts"] = relink_attempt

        documento_relink = session["session_data"].get("documento_relink")
        solicitante = self.users.get_user_by_document(documento_relink)
        if not solicitante:
            self.sessions.finish(telegram_id, "Solicitante no encontrado en revinculación")
            await update.message.reply_text(
                "❌ Ocurrió un error inesperado. Por favor inicia de nuevo con /iniciar o Hola.",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        extracted_text = self.ocr.extract_text(file_path)
        validation_result = self.ocr.validate_recipe(
            extracted_text or "", documento_relink, solicitante.nombre
        )
        logger.info(
            f"[{telegram_id}] Revinculación OCR intento {relink_attempt}: "
            f"doc={validation_result['document_match']} nombre={validation_result['name_match']}"
        )

        if validation_result['is_valid']:
            self.users.relink_telegram_id(solicitante, telegram_id)
            self.sessions.update(telegram_id, SessionSteps.KNOWN_USER, {
                "documento": solicitante.documento,
                "nombre": solicitante.nombre,
                "direccion_beneficiario": solicitante.direccion_beneficiario,
                "documento_relink": None,
            })
            first_name = solicitante.nombre.split()[0] if solicitante.nombre else "Usuario"
            await update.message.reply_html(
                f"✅ ¡Identidad verificada! Bienvenido de nuevo, <b>{first_name}</b>.\n\n"
                "Tu cuenta ha sido revinculada correctamente. ¿Qué deseas hacer ahora?",
                reply_markup=known_user_keyboard()
            )
        else:
            doc_status = "✅ Verificado" if validation_result['document_match'] else "❌ No verificado"
            name_status = "✅ Verificado" if validation_result['name_match'] else "❌ No verificado"
            if relink_attempt >= MAX_OCR_ATTEMPTS:
                logger.warning(
                    f"[{telegram_id}] 🔒 Revinculación fallida tras {relink_attempt} intentos "
                    f"para documento {documento_relink}"
                )
                self.sessions.finish(telegram_id, "Revinculación fallida: intentos agotados")
                await update.message.reply_text(
                    "❌ No fue posible verificar tu identidad.\n\n"
                    "Si necesitas ayuda, contacta a un administrador.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                remaining = MAX_OCR_ATTEMPTS - relink_attempt
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    f"⚠️ No se pudo verificar la identidad. Tienes {remaining} intento(s) más.\n\n"
                    "Por favor sube una imagen más clara de tu documento.",
                    reply_markup=ReplyKeyboardRemove()
                )
