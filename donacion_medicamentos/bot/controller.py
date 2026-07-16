"""Inicializa el bot: crea la Application, arma las dependencias,
registra los handlers y ejecuta run_polling()."""
import logging
import re

from django.conf import settings
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .constants import SessionSteps
from .conversation.medication import MedicationFlow
from .conversation.onboarding import OnboardingFlow
from .conversation.photo import PhotoFlow
from .conversation.relink import RelinkFlow
from .dispatcher import Dispatcher
from .handlers import TelegramHandlers
from .ocr import OCRService
from .ocr_processor import OCRProcessor
from .request import RequestService
from .session_manager import SessionManager
from .user import UserService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


class BotController:
    """Controlador principal del bot de Telegram (solo wiring y arranque)."""

    def __init__(self):
        self.__application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        logger.info("🔧 Verificando configuración de OCR...")
        OCRProcessor.test_ocr_setup()

        # Servicios
        self.session_manager = SessionManager()
        self.user_service = UserService()
        self.request_service = RequestService(self.user_service)
        self.ocr_service = OCRService()

        # Flujos de conversación
        self.onboarding = OnboardingFlow(self.session_manager, self.user_service, self.request_service)
        self.relink = RelinkFlow(self.session_manager, self.user_service, self.ocr_service)
        self.medication = MedicationFlow(self.session_manager, self.request_service)
        self.photo = PhotoFlow(self.session_manager, self.user_service,
                               self.request_service, self.ocr_service)

        # Dispatcher: step -> handler (mismo orden de pasos que el if/elif original)
        self.dispatcher = Dispatcher({
            SessionSteps.NEW_USER: self.onboarding.new_user,
            SessionSteps.REQ_DOCUMENT: self.onboarding.req_document,
            SessionSteps.REQ_RELINK_CONFIRM: self.relink.req_relink_confirm,
            SessionSteps.REQ_RELINK_DOCUMENT: self.relink.req_relink_document,
            SessionSteps.REQ_NAME: self.onboarding.req_name,
            SessionSteps.REQ_CONFIRM_DATA: self.onboarding.req_confirm_data,
            SessionSteps.REQ_PHONE: self.onboarding.req_phone,
            SessionSteps.REQ_ADDRESS: self.onboarding.req_address,
            SessionSteps.KNOWN_USER: self.onboarding.known_user,
            SessionSteps.REQ_MEDICATIONS: self.medication.req_medications,
            SessionSteps.REQ_MED_COUNT: self.medication.req_med_count,
            SessionSteps.REQ_MED_DESCRIPTION: self.medication.req_med_description,
            SessionSteps.REQ_MED_SEARCH: self.medication.req_med_search,
            SessionSteps.REQ_MED_SELECT: self.medication.req_med_select,
            SessionSteps.REQ_PHOTO_VALIDATION: self.photo.req_photo_validation,
            SessionSteps.REQ_PHOTO: self.photo.req_photo,
            SessionSteps.REQ_MORE_PHOTOS: self.photo.req_more_photos,
        })

        # Entradas de Telegram
        self.handlers = TelegramHandlers(self.session_manager, self.dispatcher, self.onboarding)

    def run(self) -> None:
        self.__application.add_handler(CommandHandler("iniciar", self.handlers.wellcome_user))
        self.__application.add_handler(CommandHandler("salir", self.handlers.end_session_command))

        fin_pattern = re.compile(r'\b(salir|cerrar|finalizar)\b', flags=re.IGNORECASE)
        self.__application.add_handler(
            MessageHandler(filters.TEXT & filters.Regex(fin_pattern), self.handlers.handle_plain_text)
        )
        saludos_pattern = re.compile(
            r'\b(hola|hi|buenas|buenos\s+días|buenos\s+dias|buenas\s+tardes|buenas\s+noches|buen\s+dia)\b',
            flags=re.IGNORECASE
        )
        self.__application.add_handler(
            MessageHandler(filters.TEXT & filters.Regex(saludos_pattern), self.handlers.handle_plain_text)
        )
        self.__application.add_handler(
            MessageHandler(
                filters.TEXT | filters.Document.ALL | filters.PHOTO,
                self.handlers.request_session_step
            )
        )
        # Cualquier otro tipo de mensaje (sticker, nota de voz, video, ubicación, contacto,
        # GIF, encuesta, etc.) no calza con ningún filtro anterior: sin este handler el
        # usuario se quedaba sin ninguna respuesta. Debe ir último para no interceptar
        # los mensajes que ya manejan los handlers de arriba.
        self.__application.add_handler(
            MessageHandler(filters.ALL, self.handlers.handle_unsupported)
        )

        # Red de seguridad global: evita que una excepción no controlada dentro de un
        # handler deje al usuario sin respuesta y sin explicación.
        self.__application.add_error_handler(self.handlers.global_error_handler)

        logger.info("🤖 Bot iniciado: seguridad por ownership, revinculación por OCR, commit diferido")
        self.__application.run_polling(allowed_updates=Update.ALL_TYPES)
