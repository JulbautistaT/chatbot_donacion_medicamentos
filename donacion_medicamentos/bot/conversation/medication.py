"""Flujo manual de medicamentos con búsqueda difusa (fuzzy search).

El usuario escribe el nombre (o parte) del medicamento; el sistema normaliza,
busca coincidencias parciales y, si no hay, aplica búsqueda difusa. Las opciones
(máx. 5) se muestran como botones y el ID se resuelve automáticamente.
Tras 2 búsquedas fallidas consecutivas se redirige al envío de la fórmula
(conservando los medicamentos ya agregados) para validación por el administrador.
"""
import logging
import re

from telegram import ForceReply, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from ..constants import MAX_MEDICATIONS, MAX_MED_SEARCH_FAILURES, SessionSteps
from ..keyboards import manual_or_photo_keyboard, medication_options_keyboard, yes_no_keyboard
from ..request import RequestService
from ..session_manager import SessionManager

logger = logging.getLogger(__name__)

# Respuesta del usuario indicando que ninguna de las opciones mostradas corresponde
# al medicamento buscado (se evalúa sobre el texto completo, ya limpio de espacios).
NONE_OF_ABOVE_PATTERN = re.compile(
    r'^(ninguno|ninguna|no\s+est[aá]|no\s+es|no\s+aparece|no)[\s.,!]*$',
    re.IGNORECASE
)


class MedicationFlow:
    """Pasos REQ_MEDICATIONS, REQ_MED_COUNT, REQ_MED_DESCRIPTION,
    REQ_MED_SEARCH y REQ_MED_SELECT."""

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
                f"Recuerda que puedes solicitar hasta {MAX_MEDICATIONS} medicamentos.\n\n"
                "Escribe una cantidad de 1 a 4.\n\n"
                "Ejemplo: <code>2</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
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
                "⚠️ <b>Para enviarla: </b> Da click en el icono📎y selecciona el archivo o la imagen de la fórmula médica. \n\n"
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
            "med_candidates": [],
            "med_search_failures": 0,
        })
        await update.message.reply_text(
            "📝 Ahora vamos a solicitar los medicamentos uno por uno.\n\n"
            "💊 Por cada medicamento te pediremos:\n"
            "1️⃣ El nombre (o parte del nombre) del medicamento\n"
            "2️⃣ Selección entre las opciones encontradas\n\n"
            "Cuando estés listo, presiona 'Continuar'.",
            reply_markup=yes_no_keyboard("Continuar ▶️", "Cancelar ❌")
        )

    # ── REQ_MED_DESCRIPTION ───────────────────────────────────────────────
    async def req_med_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        if "continuar" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_SEARCH, {})
            await update.message.reply_text(
                "💊 Por favor, escribe el <b>nombre</b> del medicamento <b>1</b> "
                "(o una parte del nombre).\n\n"
                "💡 Ejemplo: <code>acetaminofen</code>",
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

    # ── REQ_MED_SEARCH ────────────────────────────────────────────────────
    async def req_med_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                             telegram_id: int, session: dict, text: str) -> None:
        if not text:
            await update.message.reply_text(
                "Por favor escribe el nombre del medicamento.",
                reply_markup=ForceReply(selective=True)
            )
            return
        await self.__search_and_reply(update, telegram_id, session, text)

    # ── REQ_FORMULA ────────────────────────────────────────────────────   
    async def __request_formula(self, update: Update, telegram_id: int, session: dict) -> None:
        """"Solicitud de formula médica"""

        self.sessions.update(telegram_id, SessionSteps.REQ_MORE_PHOTOS, {})

        requires_validation = session["session_data"].get(
            "requires_formula_validation", False
        )

        if requires_validation:
            mensaje = (
                "✅ ¡Perfecto! Hemos registrado todos los medicamentos que fue posible identificar.\n\n"
                "📄 Ahora, por favor <b>sube una foto o un PDF de la fórmula médica</b>\n\n"
                "<b>Sigue estos pasos:</b>\n\n"
                "1️⃣ Pulsa el icono del clip 📎 para adjuntar un archivo.\n\n"
                "2️⃣ Si vas a enviar una <b>foto</b>:\n"
                "   • Selecciona <b>Galería</b> o <b>Fotos</b>.\n"
                "   • Busca y elige la imagen de la fórmula. 🖼️\n\n"
                "3️⃣ Si vas a enviar un <b>archivo PDF</b>:\n"
                "   • Pulsa la opción <b>Documento</b> 📄.\n"
                "   • Busca el archivo PDF de la fórmula y selecciónalo.\n\n"
                "📌 Espera unos segundos mientras se carga el archivo. No cierres el chat hasta que termine el envío."
                )
        else:
            mensaje = (
                "✅ ¡Perfecto! Ya hemos registrado todos los medicamentos.\n\n"
                "📄 Ahora, por favor <b>sube una foto o un PDF de la fórmula médica</b>\n\n"
                "<b>Sigue estos pasos:</b>\n\n"
                "1️⃣ Pulsa el icono del clip 📎 para adjuntar un archivo.\n\n"
                "2️⃣ Si vas a enviar una <b>foto</b>:\n"
                "   • Selecciona <b>Galería</b> o <b>Fotos</b>.\n"
                "   • Busca y elige la imagen de la fórmula. 🖼️\n\n"
                "3️⃣ Si vas a enviar un <b>archivo PDF</b>:\n"
                "   • Pulsa la opción <b>Documento</b> 📄.\n"
                "   • Busca el archivo PDF de la fórmula y selecciónalo.\n\n"
                "📌 Espera unos segundos mientras se carga el archivo. No cierres el chat hasta que termine el envío."
                )

        await update.message.reply_text(
            mensaje,
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )


    # ── REQ_MED_SELECT ────────────────────────────────────────────────────
    async def req_med_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                             telegram_id: int, session: dict, text: str) -> None:
        candidates = session["session_data"].get("med_candidates", [])
        chosen = next((c for c in candidates if c["label"] == text), None)

        if chosen is None:
            if NONE_OF_ABOVE_PATTERN.match(text.strip()):
                # El usuario indica que ninguna opción mostrada corresponde: se da por
                # no identificado este medicamento (se validará con la fórmula médica).
                query = session["session_data"].get("last_med_query", text)
                await self.__mark_medication_unidentified(update, telegram_id, session, query)
                return
            # El texto no coincide con ningún botón: se trata como una nueva búsqueda
            # para no dejar al usuario atrapado si ninguna opción era la correcta.
            await self.__search_and_reply(update, telegram_id, session, text)
            return

        # Selección válida: se resuelve el ID automáticamente
        session["session_data"].setdefault("pending_medications", []).append({
            "medication_id": chosen["id"],
        })
        session["session_data"]["medication_count"] -= 1
        session["session_data"]["med_candidates"] = []
        session["session_data"]["med_search_failures"] = 0
        remaining = session["session_data"]["medication_count"]
        logger.info(
            f"[{telegram_id}] Medicamento acumulado: id={chosen['id']} "
            f"({chosen['label']}) | restantes={remaining}"
        )

        if remaining > 0:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_SEARCH, {})
            await update.message.reply_text(
                f"✅ Medicamento agregado: {chosen['label']}.\n\n"
                f"💊 Ahora escribe el nombre del siguiente medicamento (quedan {remaining}).",
                reply_markup=ForceReply(selective=True)
            )
        else:
            await self.__request_formula(update, telegram_id, session)

    # ── Lógica compartida de búsqueda ─────────────────────────────────────
    async def __search_and_reply(self, update: Update, telegram_id: int,
                                 session: dict, query: str) -> None:
        status, candidates = self.requests.search_medications(query)

        if status in ("ok", "fuzzy"):
            session["session_data"]["med_search_failures"] = 0
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_SELECT, {
                "med_candidates": candidates,
                "last_med_query": query,
            })
            header = (
                "💊 Encontré estos medicamentos:\n\n"
                if status == "ok"
                else "💊 No encontré una coincidencia exacta, pero estos medicamentos son similares:"
            )
            await update.message.reply_text(
                f"{header} Selecciona una opción.\n\n"
                "❓ Si tu medicamento <b>no aparece</b> en la lista, escribe <code>ninguno</code>",
                reply_markup=medication_options_keyboard([c["label"] for c in candidates]),
                parse_mode="HTML",
            )
            return

        if status == "too_many":
            # No cuenta como fallo: es una guía hacia una búsqueda más precisa
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_SEARCH, {})
            await update.message.reply_text(
                "Se encontraron muchos medicamentos con ese nombre. "
                "Por favor escribe un poco más del nombre para ayudarte a encontrar el medicamento correcto.",
                reply_markup=ForceReply(selective=True)
            )
            return

        # status == "none": fallo de identificación
        failures = session["session_data"].get("med_search_failures", 0) + 1
        session["session_data"]["med_search_failures"] = failures

        if failures >= MAX_MED_SEARCH_FAILURES:
            await self.__mark_medication_unidentified(update, telegram_id, session, query)
            return

        self.sessions.update(telegram_id, SessionSteps.REQ_MED_SEARCH, {})
        await update.message.reply_text(
            "No pude identificar el medicamento. "
            "Intenta escribir el nombre como aparece en la fórmula médica.",
            reply_markup=ForceReply(selective=True)
        )

    # ── Medicamento no identificado (fallos agotados o rechazo explícito) ──
    async def __mark_medication_unidentified(self, update: Update, telegram_id: int,
                                              session: dict, query: str) -> None:
        """Da por no identificado el medicamento actual: se validará con la fórmula
        médica. Usado tanto al agotar los intentos de búsqueda como cuando el usuario
        indica explícitamente que ninguna opción mostrada corresponde."""
        session["session_data"]["med_search_failures"] = 0
        session["session_data"]["med_candidates"] = []

        # Registrar que este medicamento será validado con la fórmula
        session["session_data"].setdefault("pending_formula_validation", []).append(query)

        # Marcar que la fórmula deberá revisarse
        session["session_data"]["requires_formula_validation"] = True

        # Descontar un medicamento pendiente
        session["session_data"]["medication_count"] -= 1
        remaining = session["session_data"]["medication_count"]

        if remaining > 0:
            self.sessions.update(telegram_id, SessionSteps.REQ_MED_SEARCH, {})
            await update.message.reply_text(
                "😊 No te preocupes. No pude identificar este medicamento, "
                "pero lo validaremos cuando recibamos la fórmula médica.\n\n"
                f"💊 Ahora escribe el nombre del siguiente medicamento (quedan {remaining}).",
                reply_markup=ForceReply(selective=True)
            )
        else:
            await self.__request_formula(update, telegram_id, session)
