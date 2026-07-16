"""Entradas de Telegram: /iniciar, /salir, texto, foto, documento.

No consulta la BD ni hace OCR: valida la sesión y delega en el dispatcher
o en los flujos de conversation/.
"""
import logging
import re

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from .dispatcher import Dispatcher
from .session_manager import SessionManager

logger = logging.getLogger(__name__)


class TelegramHandlers:
    """Puntos de entrada registrados en la Application (antes métodos de BotController)."""

    def __init__(self, session_manager: SessionManager, dispatcher: Dispatcher,
                 onboarding_flow) -> None:
        self.sessions = session_manager
        self.dispatcher = dispatcher
        self.onboarding = onboarding_flow

    async def wellcome_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Antes: BotController.wellcome_user (/iniciar)."""
        telegram_id = update.effective_user.id
        session = self.sessions.get(telegram_id)
        if session and session.get("is_active"):
            await update.message.reply_html(
                "👋 Ya tienes una sesión activa. Completa la sesión actual o usa salir para cerrarla."
            )
            return
        # La creación de sesión y la consulta de la política viven en el flujo de onboarding
        await self.onboarding.send_welcome(update, telegram_id)

    async def end_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Antes: BotController.end_session_command (/salir)."""
        telegram_id = update.effective_user.id
        session = self.sessions.get(telegram_id)
        if not session:
            await update.message.reply_text("No tienes ninguna sesión activa.")
            return
        self.sessions.finish(telegram_id, "Sesión cerrada por el usuario")
        await update.message.reply_text(
            "✅ Tu sesión ha sido cerrada correctamente.\n"
            "Puedes iniciar una nueva con /iniciar o escribiendo Hola."
        )

    async def request_session_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Antes: BotController.request_session_step (texto, foto, documento)."""
        telegram_id = update.effective_user.id
        message = update.message
        text = message.text.strip() if message.text else ""

        session = self.sessions.get(telegram_id)
        if not session:
            await update.message.reply_text(
                "⚠️ No tienes ninguna sesión activa. Usa /iniciar o escribe Hola para comenzar."
            )
            return

        if self.sessions.expire(telegram_id):
            await update.message.reply_text(
                "⏰ Tu sesión ha expirado por inactividad.\n"
                "Por favor, inicia una nueva sesión con /iniciar o Hola."
            )
            return

        self.sessions.update_last_activity(telegram_id)
        step = session.get("step")

        if self.dispatcher.knows(step):
            handled = await self.dispatcher.dispatch(step, update, context, telegram_id, session, text)
            if handled is not False:
                return
            # handled is False: el mensaje no era foto/documento/texto en un paso de fotos;
            # en el original caía al bloque de PASO INESPERADO. Se preserva.

        # ── PASO INESPERADO ───────────────────────────────────────────────
        logger.error(f"[{telegram_id}] Paso inesperado: {step}")
        self.sessions.finish(telegram_id, f"Paso inesperado: {step}")
        await update.message.reply_text(
            "❌ Ocurrió un error con la sesión. Por favor inicia de nuevo con /iniciar o Hola.",
            reply_markup=ReplyKeyboardRemove(),
        )

    async def handle_plain_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Antes: BotController.handle_plain_text (saludos y salir)."""
        msg = update.effective_message
        if not msg or not msg.text:
            return
        text = msg.text.strip()
        text_lower = text.lower()
        telegram_id = update.effective_user.id

        if re.search(r'\b(salir|cerrar|finalizar)\b', text_lower, re.IGNORECASE):
            await self.end_session_command(update, context)
            return

        session = self.sessions.get(telegram_id)
        is_active = bool(session and session.get("is_active"))

        if re.search(
            r'\b(hola|hi|buenas|buenos\s+días|buenos\s+dias|buenas\s+tardes|buenas\s+noches|buen\s+dia)\b',
            text_lower, re.IGNORECASE
        ):
            if not is_active:
                await self.wellcome_user(update, context)
            else:
                await msg.reply_text(
                    "👋 Ya tienes una sesión activa. Completa la sesión o usa salir para cerrarla."
                )
            return

        await self.request_session_step(update, context)

    async def handle_unsupported(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Responde a tipos de mensaje que no coinciden con ningún otro handler
        (sticker, nota de voz, video, ubicación, contacto, GIF, encuesta, etc.).

        Antes, estos mensajes no calzaban con ningún filtro registrado
        (solo se manejan texto, foto y documento) y el usuario se quedaba
        esperando una respuesta que nunca llegaba. Debe registrarse último,
        después de todos los MessageHandler de texto/foto/documento.
        """
        message = update.effective_message
        if message is None:
            return
        await message.reply_text(
            "🙏 Por ahora solo puedo leer mensajes de <b>texto</b>, <b>fotos</b> o "
            "<b>documentos PDF</b>.\n\n"
            "Por favor escribe tu mensaje o adjunta la fórmula médica como foto o PDF.\n"
            "Si necesitas reiniciar, escribe /iniciar o Hola.",
            parse_mode="HTML",
        )

    async def global_error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Red de seguridad global (registrado con Application.add_error_handler).

        Se dispara ante cualquier excepción no controlada dentro de un handler
        (fallo de base de datos, de red, etc.). Antes de este handler, esas
        excepciones solo se registraban en el log del servidor y el usuario
        se quedaba sin ninguna respuesta ni explicación. Aquí se le avisa,
        se cierra su sesión por seguridad (su estado interno puede haber
        quedado a medio actualizar) y se le indica cómo continuar.
        """
        logger.error(f"Excepción no controlada procesando un update: {update!r}", exc_info=context.error)

        if not isinstance(update, Update):
            return

        telegram_id = update.effective_user.id if update.effective_user else None
        if telegram_id is not None:
            self.sessions.finish(telegram_id, f"Error no controlado: {context.error}")

        message = update.effective_message
        if message is None:
            return
        try:
            await message.reply_text(
                "⚠️ Ocurrió un problema inesperado y no pudimos continuar con tu solicitud.\n\n"
                "Por seguridad reiniciamos tu sesión. Por favor intenta de nuevo escribiendo "
                "/iniciar o Hola.\n\n"
                "Si el problema se repite, espera unos minutos e inténtalo otra vez.",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:
            logger.exception(f"[{telegram_id}] No se pudo notificar al usuario del error")
