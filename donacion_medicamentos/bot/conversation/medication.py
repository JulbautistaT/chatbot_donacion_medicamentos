"""Flujo manual de medicamentos.

NOTA: se conserva la lógica existente; luego se hará una búsqueda difusa
sobre medicamentos (indicación del propietario del proyecto).
"""
import logging

from telegram import ForceReply, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from ..constants import MAX_MEDICATIONS, SessionSteps
from ..keyboards import manual_or_photo_keyboard, yes_no_keyboard
from ..request import RequestService
from ..session_manager import SessionManager

logger = logging.getLogger(__name__)


class MedicationFlow:
    """Pasos REQ_MEDICATIONS, REQ_MED_COUNT, REQ_MED_DESCRIPTION,
    REQ_MED_FIRST_LETTER y REQ_MED_LIST_CHOSEN (antes en request_session_step)."""

    def __init__(self, session_manager: SessionManager, request_service: RequestService) -> None:
        self.sessions = session_manager
        self.requests = request_service

    # ── REQ_MEDICATIONS ───────────────────────────────────────────────────
    async def req_medications(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                              telegram_id: int, session: dict, text: str) -> None:
        text_clean = "".join(c for c in text.lower() if c.isalnum() or c.isspace())
        if "describir" in text_clean or "manual" in text_clean:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_COUNT, {})
            await update.message.reply_text(
                "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                f"Recuerda que puedes solicitar hasta {MAX_MEDICATIONS} medicamentos.",
                reply_markup=ForceReply(selective=True)
            )
            return
        if "subir" in text_clean or "receta" in text_clean or "foto" in text_clean:
            self.sessions.update(telegram_id, SessionSteps.REQ_PHOTO, {
                "pending_medications": [], "pending_files": [],
            })
            await update.message.reply_text(
                "📄 Por favor, sube el documento en <b>PDF</b> o una <b>imagen clara</b> de la fórmula médica.\n\n"
                "💡 <b>Asegúrate de que se vean claramente:</b>\n"
                "  • Nombre del paciente\n"
                "  • Número de documento\n"
                "  • Lista de medicamentos\n\n"
                "⚠️ <b>IMPORTANTE:</b> Envía la imagen como <b>Archivo</b> (📎 adjunto), "
                "<b>NO como foto</b>. Telegram comprime las fotos y el texto puede quedar ilegible.\n\n"
                "🔍 El sistema validará automáticamente la información.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
            return
        await update.message.reply_text(
            "No entendí tu respuesta. ¿Deseas describir los medicamentos o subir una receta?",
            reply_markup=manual_or_photo_keyboard()
        )

    # ── REQ_MED_COUNT ─────────────────────────────────────────────────────
    async def req_med_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                            telegram_id: int, session: dict, text: str) -> None:
        if not text.isdigit():
            await update.message.reply_text(
                "Por favor escribe un número entero válido.",
                reply_markup=ForceReply(selective=True)
            )
            return
        count = int(text)
        if count <= 0 or count > MAX_MEDICATIONS:
            await update.message.reply_text(
                f"El número debe estar entre 1 y {MAX_MEDICATIONS}.",
                reply_markup=ForceReply(selective=True)
            )
            return
        self.sessions.update(telegram_id, SessionSteps.REQ_MED_DESCRIPTION, {
            "medication_count": count,
            "pending_medications": [],
        })
        await update.message.reply_text(
            "📝 Ahora vamos a solicitar los medicamentos uno por uno.\n\n"
            "💊 Por cada medicamento te pediremos:\n"
            "1️⃣ Primera letra del nombre\n"
            "2️⃣ Selección del medicamento\n\n"
            "Cuando estés listo, presiona 'Continuar'.",
            reply_markup=yes_no_keyboard("Continuar ▶️", "Cancelar ❌")
        )

    # ── REQ_MED_DESCRIPTION ───────────────────────────────────────────────
    async def req_med_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        if "continuar" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_FIRST_LETTER, {})
            await update.message.reply_text(
                "🔤 Por favor, escribe la <b>primera letra</b> del medicamento <b>1</b>.\n\n"
                "💡 Ejemplo: Si buscas 'Acetaminofén', escribe <b>A</b>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return
        if "cancel" in text_lower or "cancelar" in text_lower:
            self.sessions.finish(telegram_id, "Cancelado por usuario")
            await update.message.reply_text(
                "❌ Solicitud cancelada. Puedes iniciar una nueva con /iniciar o Hola.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        await update.message.reply_text(
            "Por favor presiona 'Continuar' cuando estés listo.",
            reply_markup=yes_no_keyboard("Continuar ▶️", "Cancelar ❌")
        )

    # ── REQ_MED_FIRST_LETTER ──────────────────────────────────────────────
    async def req_med_first_letter(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   telegram_id: int, session: dict, text: str) -> None:
        first_letter = text.upper()
        if not first_letter.isalpha() or len(first_letter) != 1:
            await update.message.reply_text(
                "Por favor escribe una única letra válida.",
                reply_markup=ForceReply(selective=True)
            )
            return
        meds_text = self.requests.get_available_medications(first_letter)
        if not meds_text:
            await update.message.reply_text(
                f"😕 No se encontraron medicamentos que comiencen con '{first_letter}'.\n\n"
                "🔄 Por favor, intenta con otra letra.",
                reply_markup=ForceReply(selective=True)
            )
            return
        self.sessions.update(telegram_id, SessionSteps.REQ_MED_LIST_CHOSEN, {"first_letter": first_letter})
        await update.message.reply_text(
            f"💊 Medicamentos disponibles con '{first_letter}':\n\n{meds_text}\n\n"
            "Escribe el <b>ID</b> del medicamento que deseas solicitar.",
            reply_markup=ForceReply(selective=True),
            parse_mode="HTML"
        )

    # ── REQ_MED_LIST_CHOSEN ───────────────────────────────────────────────
    async def req_med_list_chosen(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  telegram_id: int, session: dict, text: str) -> None:
        try:
            selected_id = int(text)
        except (ValueError, TypeError):
            await update.message.reply_text(
                "Por favor escribe un ID válido (número).",
                reply_markup=ForceReply(selective=True)
            )
            return

        first_letter = session["session_data"].get("first_letter")
        if not self.requests.medication_exists(selected_id, first_letter):
            await update.message.reply_text(
                "❌ ID de medicamento no válido o no disponible. Intenta otro ID.",
                reply_markup=ForceReply(selective=True)
            )
            return

        # Acumular medicamento en sesión (cantidad fija = 1 por selección)
        session["session_data"].setdefault("pending_medications", []).append({
            "medication_id": selected_id,
        })
        session["session_data"]["medication_count"] -= 1
        remaining = session["session_data"]["medication_count"]
        logger.info(
            f"[{telegram_id}] Medicamento acumulado: id={selected_id} | restantes={remaining}"
        )

        if remaining > 0:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_FIRST_LETTER, {})
            await update.message.reply_text(
                f"✅ Medicamento agregado.\n\n"
                f"🔤 Ahora escribe la primera letra del siguiente medicamento (quedan {remaining}).",
                reply_markup=ForceReply(selective=True)
            )
        else:
            self.sessions.update(telegram_id, SessionSteps.REQ_MORE_PHOTOS, {})
            await update.message.reply_text(
                "✅ ¡Perfecto! Ya hemos registrado todos los medicamentos.\n\n"
                "📸 Ahora, por favor <b>sube una foto o PDF de la receta médica</b> para completar tu solicitud.\n\n"
                "🩺💊 Este paso es <b>obligatorio</b>. La solicitud se guardará al recibirla.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
