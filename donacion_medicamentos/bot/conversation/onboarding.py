"""Flujo de registro: desde NEW_USER hasta KNOWN_USER."""
import logging
import re

from telegram import ForceReply, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from ..constants import MAX_DOC_ATTEMPTS, SessionSteps
from ..keyboards import known_user_keyboard, manual_or_photo_keyboard, yes_no_keyboard, accept_policy_keyboard
from ..request import RequestService
from ..session_manager import SessionManager
from ..user import UserService

logger = logging.getLogger(__name__)


class OnboardingFlow:
    """Registro y menú de usuario conocido (antes en BotController.request_session_step)."""

    def __init__(self, session_manager: SessionManager, user_service: UserService,
                 request_service: RequestService) -> None:
        self.sessions = session_manager
        self.users = user_service
        self.requests = request_service

    async def send_welcome(self, update: Update, telegram_id: int) -> None:
        """Mensaje de bienvenida + política de datos (antes cuerpo de wellcome_user).

        Crea la sesión y consulta la política activa (por eso vive aquí y no en handlers.py).
        """
        self.sessions.create(telegram_id)

        from politicas.models import PoliticaDatos
        try:
            politica_activa = PoliticaDatos.objects.get(es_activa=True)
            version = politica_activa.version
            url = "http://127.0.0.1:8000/politica-de-datos/"
        except PoliticaDatos.DoesNotExist:
            version = "1.0"
            url = "http://127.0.0.1:8000/politica-de-datos/"

        await update.message.reply_html(
            f"👋 ¡Hola! Bienvenido al sistema de donación de medicamentos. 💊🤝\n\n"
            f"Antes de continuar, por favor lee y acepta nuestra <b>Política de Tratamiento de Datos</b>. 📄🔒\n"
            f"📋 <b>Versión {version}</b>\n"
            f"🔗 <a href='{url}'>Leer política</a>\n\n"
            "Al presionar <b>Acepto</b>, autorizas el tratamiento de tus datos personales y "
            "confirmas que la información suministrada es veraz. También entiendes que la Junta "
            "únicamente facilita la donación de medicamentos.\n\n"
            "✅ Presiona <b>Acepto</b> para continuar.",
            reply_markup=accept_policy_keyboard(),
        )

    async def handle_acepto(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """LEGADO: nunca se registra como handler en run() (código muerto en el original).

        Se conserva sin registrar para no romper la lógica actual.
        """
        chat_id = str(update.effective_chat.id)
        from politicas.models import PoliticaDatos, AceptacionPolitica
        from django.utils import timezone
        politica = PoliticaDatos.objects.get(es_activa=True)
        AceptacionPolitica.objects.create(
            telegram_chat_id=chat_id,
            politica=politica,
            fecha_consentimiento=timezone.now().date(),
            hora_consentimiento=timezone.now().time(),
            acepto=True,
        )
        await update.message.reply_html(
            f"✅ <b>Consentimiento registrado</b>\n\n"
            f"📋 v{politica.version}\n"
            f"📅 {timezone.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )

    # ── NEW_USER ──────────────────────────────────────────────────────────
    async def new_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                       telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        acepto = (
            "acepto" in text_lower
            or "acept" in text_lower
            or "✅" in text
            or "si" in text_lower
        )

        if not acepto:
            self.sessions.finish(telegram_id, "Usuario no aceptó política de datos")
            await update.message.reply_html(
                "😊 Entendemos tu decisión.\n\n"
                "Para poder usar este servicio es necesario aceptar la "
                "<b>Política de Tratamiento de Datos</b>.\n\n"
                "Si cambias de opinión, puedes escribir <b>Hola</b> cuando quieras "
                "y te mostraremos la política nuevamente. ¡Estamos aquí para ayudarte! 💊",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        logger.info(f"[{telegram_id}] Política aceptada -> solicitando documento")
        self.sessions.update(telegram_id, SessionSteps.REQ_DOCUMENT, {"documento": None})
        await update.message.reply_text(
            "📝 Por favor, escribe el <b>número de documento</b> de la persona que necesita los medicamentos, sin espacios, puntos ni caracteres especiales. \n\n"
            "Ejemplo: <code>123456789</code>",
            reply_markup=ForceReply(selective=True),
            parse_mode="HTML",
        )

    # ── REQ_DOCUMENT ──────────────────────────────────────────────────────
    async def req_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                           telegram_id: int, session: dict, text: str) -> None:
        attempts = session["session_data"].get("doc_attempts", 0) + 1
        session["session_data"]["doc_attempts"] = attempts
        if attempts > MAX_DOC_ATTEMPTS:
            self.sessions.finish(telegram_id, "Demasiados intentos de documento")
            await update.message.reply_text(
                "⚠️ Demasiados intentos. La sesión fue cerrada por seguridad.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if not text.isdigit():
            await update.message.reply_text(
                "Por favor escribe un número de documento válido.",
                reply_markup=ForceReply(selective=True),
            )
            return

        document_number = text
        logger.info(f"[{telegram_id}] Documento recibido: {document_number} (intento {attempts})")
        solicitante, status = self.users.get_user_secure(telegram_id, document_number)

        if status == 'owner':
            self.sessions.update(telegram_id, SessionSteps.KNOWN_USER, {
                "documento": solicitante.documento,
                "nombre": solicitante.nombre,
                "direccion_beneficiario": solicitante.direccion_beneficiario,
                "telefono": solicitante.telefono,
            })
            first_name = solicitante.nombre.split()[0] if solicitante.nombre else "Usuario"
            await update.message.reply_html(
                f"👋 ¡Hola {first_name}! He verificado tu documento {document_number}.\n\n"
                "¿Los siguientes datos están correctos?\n"
                f"<b>Teléfono:</b> {solicitante.telefono}\n"
                f"<b>Dirección:</b> {solicitante.direccion_beneficiario}\n\n"
                "Si todo está correcto, presiona <b>Sí, correcto ✅</b> para continuar.",
                reply_markup=yes_no_keyboard("Sí, correcto ✅", "No, corregir ✏️")
            )

        elif status == 'not_found':
            self.sessions.update(telegram_id, SessionSteps.REQ_NAME, {"documento": document_number})
            await update.message.reply_text(
                "🙋‍♂️ ¡Gracias! Ahora, por favor escribe el <b>nombre completo</b> de la persona que necesita los medicamentos.\n\n"
                "Ejemplo: <code>Juan Pérez</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )

        else:  # forbidden
            self.sessions.update(
                telegram_id, SessionSteps.REQ_RELINK_CONFIRM,
                {"documento_relink": document_number}
            )
            await update.message.reply_html(
                f"⚠️ El documento <b>{document_number}</b> ya tiene una cuenta asociada.\n\n"
                "¿Confirmas que este es tu número de documento?",
                reply_markup=yes_no_keyboard("Sí, es el mío ✅", "No, corregir ✏️")
            )

    # ── REQ_NAME ──────────────────────────────────────────────────────────
    async def req_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                       telegram_id: int, session: dict, text: str) -> None:
        if not text:
            await update.message.reply_text(
                "Por favor, escribe un nombre válido.", reply_markup=ForceReply(selective=True)
            )
            return
        logger.info(f"[{telegram_id}] Nombre recibido: {text}")
        documento = session["session_data"].get("documento")
        self.sessions.update(telegram_id, SessionSteps.REQ_CONFIRM_DATA, {"nombre": text})
        await update.message.reply_html(
            f"📋 Por favor confirma los datos:\n\n"
            f"🆔 <b>Documento:</b> {documento}\n"
            f"👤 <b>Nombre:</b> {text}\n\n"
            "¿Los datos son correctos?",
            reply_markup=yes_no_keyboard("Corregir ✏️", "Sí, continuar ✅")
        )

    # ── REQ_CONFIRM_DATA ──────────────────────────────────────────────────
    async def req_confirm_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                               telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        if "sí" in text_lower or "si" in text_lower or "continuar" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_PHONE, {})
            await update.message.reply_text(
                "📱 ¡Perfecto! Ahora escribe el <b>número de teléfono</b> de contacto.\n\n"
                "Ejemplo: <code>3001234567</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return
        if "no" in text_lower or "corregir" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_DOCUMENT, {"nombre": None})
            await update.message.reply_text(
                "Entendido. Por favor escribe nuevamente el <b>número de documento</b>.",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return
        await update.message.reply_text(
            "Por favor selecciona una opción válida.",
            reply_markup=yes_no_keyboard("Corregir ✏️", "Sí, continuar ✅")
        )

    # ── REQ_PHONE ─────────────────────────────────────────────────────────
    async def req_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                        telegram_id: int, session: dict, text: str) -> None:
        phone_clean = re.sub(r'\D', '', text)   # deja solo dígitos
        if not phone_clean or not (7 <= len(phone_clean) <= 15):
            await update.message.reply_text(
                "Por favor escribe un número de teléfono válido (7–15 dígitos).",
                reply_markup=ForceReply(selective=True),
            )
            return
        logger.info(f"[{telegram_id}] Teléfono recibido: {phone_clean}")
        self.sessions.update(telegram_id, SessionSteps.REQ_ADDRESS, {"telefono": phone_clean})
        await update.message.reply_text(
            "🏠 ¡Genial! Ahora, por favor escribe la <b>dirección</b> de la persona que necesita los medicamentos.\n\n"
            "Ejemplo: <code>Calle 123 #45-67, Barrio Centro</code>",
            reply_markup=ForceReply(selective=True),
            parse_mode="HTML",
        )

    # ── REQ_ADDRESS ───────────────────────────────────────────────────────
    async def req_address(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                          telegram_id: int, session: dict, text: str) -> None:
        if not text:
            await update.message.reply_text(
                "Por favor escribe una dirección válida.", reply_markup=ForceReply(selective=True)
            )
            return
        logger.info(f"[{telegram_id}] Dirección recibida: {text}")
        self.sessions.update(telegram_id, SessionSteps.KNOWN_USER, {"direccion_beneficiario": text})
        documento = session["session_data"].get("documento")
        solicitante = self.users.get_user_by_document(documento)
        if not solicitante:
            solicitante = self.users.create_user(telegram_id, session["session_data"])
        else:
            self.users.update_user(solicitante, session["session_data"])
        await update.message.reply_text(
            f"✅ ¡Registro completado!\n\n"
            f"🙋‍♂️ <b>Nombre:</b> {solicitante.nombre}\n"
            f"🆔 <b>Documento:</b> {solicitante.documento}\n"
            f"📱 <b>Teléfono:</b> {solicitante.telefono}\n"
            f"🏠 <b>Dirección:</b> {solicitante.direccion_beneficiario}\n"
            "¿Qué deseas hacer ahora?",
            reply_markup=known_user_keyboard(),
            parse_mode="HTML",
        )

    # ── KNOWN_USER ────────────────────────────────────────────────────────
    async def known_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                         telegram_id: int, session: dict, text: str) -> None:
        text_lower = text.lower()
        if "solicitar" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_MEDICATIONS, {})
            await update.message.reply_text(
                "💊 ¿Cómo deseas solicitar los medicamentos?\n\n"
                "Puedes describirlos uno por uno o subir una o varias fotos/PDFs de la fórmula médica.",
                reply_markup=manual_or_photo_keyboard(),
                parse_mode="HTML"
            )
            return
        if "consultar" in text_lower:
            info = self.requests.get_request_info(session)
            await update.message.reply_html(info)
            self.sessions.finish(telegram_id, "Consulta completada")

            return
        if text_lower.startswith(("sí", "si")) or "correcto" in text_lower:
            await update.message.reply_text(
                "Perfecto. ¿Qué deseas hacer ahora?",
                reply_markup=known_user_keyboard()
            )
            return
        if text_lower.startswith("no") or "corregir" in text_lower:
            self.sessions.update(telegram_id, SessionSteps.REQ_PHONE, {})
            await update.message.reply_text(
                "📱 Vamos a actualizar tu información.\n\n"
                "Por favor escribe tu número de teléfono.",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return
        await update.message.reply_text(
            "No entendí tu respuesta. Selecciona una opción del menú.",
            reply_markup=known_user_keyboard()
        )
