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
