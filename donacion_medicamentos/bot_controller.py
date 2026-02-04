import logging
import os
import re
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from django.conf import settings
from django.core import files as django_files
from django.db.models import Count

from stock import models as stock_models
from telegram import ForceReply, Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import pytesseract
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
from PIL import Image

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


class SessionSteps:
    """Constantes para los pasos de la sesión"""
    NEW_USER = "NEW_USER"
    REQ_DOCUMENT = "REQUEST_DOCUMENT"
    REQ_NAME = "REQUEST_NAME"
    REQ_ADDRESS = "REQUEST_ADDRESS"
    REQ_AGE = "REQUEST_AGE"
    KNOWN_USER = "KNOWN_USER"
    REQ_MEDICATIONS = "REQUEST_MEDICATIONS"
    REQ_MED_COUNT = "REQUEST_MED_COUNT"
    REQ_MED_DESCRIPTION = "REQUEST_MED_DESCRIPTION"
    REQ_MED_FIRST_LETTER = "REQUEST_MED_FIRST_LETTER"
    REQ_MED_LIST_CHOSEN = "REQUEST_MED_LIST_CHOSEN"
    REQ_MED_QUANTITY = "REQUEST_MED_QUANTITY"
    REQ_PHOTO = "REQUEST_PHOTO"
    REQ_PHOTO_VALIDATION = "REQUEST_PHOTO_VALIDATION"
    REQ_MORE_PHOTOS = "REQUEST_MORE_PHOTOS"
    END = "END"


class OCRProcessor:
    """Procesador de OCR para imágenes y PDFs"""

    @staticmethod
    def extract_text_from_image(image_path: str) -> Optional[str]:
        """Extrae texto de una imagen usando Tesseract OCR"""
        try:
            image = Image.open(image_path)
            # Configuración para español
            text = pytesseract.image_to_string(image, lang='spa')
            logger.info(f"Texto extraído de imagen: {len(text)} caracteres")
            return text.strip()
        except Exception as e:
            logger.error(f"Error en OCR de imagen: {e}")
            return None

    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
        """Extrae texto de un PDF usando PyPDF2 y OCR si es necesario"""
        try:
            text = ""
            
            # Intentar extracción directa de texto
            try:
                reader = PdfReader(pdf_path)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            except Exception as e:
                logger.warning(f"No se pudo extraer texto directamente del PDF: {e}")
            
            # Si no hay texto o es muy poco, usar OCR
            if len(text.strip()) < 50:
                logger.info("Texto insuficiente, usando OCR en PDF...")
                images = convert_from_path(pdf_path)
                for i, image in enumerate(images):
                    page_text = pytesseract.image_to_string(image, lang='spa')
                    text += page_text + "\n"
                    logger.info(f"Página {i+1} procesada con OCR")
            
            logger.info(f"Texto extraído de PDF: {len(text)} caracteres")
            return text.strip()
        except Exception as e:
            logger.error(f"Error en extracción de PDF: {e}")
            return None

    @staticmethod
    def extract_text_from_file(file_path: str) -> Optional[str]:
        """Extrae texto de un archivo (imagen o PDF)"""
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext == '.pdf':
            return OCRProcessor.extract_text_from_pdf(file_path)
        elif file_ext in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
            return OCRProcessor.extract_text_from_image(file_path)
        else:
            logger.warning(f"Formato de archivo no soportado: {file_ext}")
            return None


class FormulaValidator:
    """Validador de fórmulas médicas"""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normaliza texto para comparación"""
        if not text:
            return ""
        # Convertir a minúsculas, eliminar tildes y caracteres especiales
        text = text.lower()
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ñ': 'n', 'ü': 'u'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        # Eliminar caracteres no alfanuméricos excepto espacios
        text = re.sub(r'[^a-z0-9\s]', '', text)
        return text.strip()

    @staticmethod
    def extract_document_number(text: str) -> List[str]:
        """Extrae posibles números de documento del texto"""
        # Buscar patrones de números de documento (6-10 dígitos)
        patterns = [
            r'\b(\d{6,10})\b',  # Números de 6-10 dígitos
            r'(?:c\.?c\.?|cedula|documento|identificacion)[:\s]*(\d{6,10})',  # Con palabras clave
        ]
        
        found_documents = []
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                doc = match.group(1) if match.lastindex else match.group(0)
                doc = re.sub(r'\D', '', doc)  # Solo dígitos
                if 6 <= len(doc) <= 10:
                    found_documents.append(doc)
        
        return list(set(found_documents))  # Eliminar duplicados

    @staticmethod
    def validate_formula(
        text: str,
        expected_document: str,
        expected_name: str
    ) -> Dict[str, Any]:
        """
        Valida si el texto de la fórmula contiene el documento y nombre esperados
        
        Returns:
            dict con:
                - is_valid: bool
                - document_match: bool
                - name_match: bool
                - errors: list
        """
        result = {
            'is_valid': False,
            'document_match': False,
            'name_match': False,
            'errors': []
        }

        if not text or len(text) < 50:
            result['errors'].append("Texto insuficiente o no se pudo leer el documento")
            return result

        # Normalizar textos para comparación
        text_normalized = FormulaValidator.normalize_text(text)
        expected_name_normalized = FormulaValidator.normalize_text(expected_name)

        # Extraer información
        found_documents = FormulaValidator.extract_document_number(text)

        # Validar documento
        if expected_document in found_documents:
            result['document_match'] = True
        else:
            result['errors'].append("documento")

        # Validar nombre - buscar cada palabra del nombre en el texto completo
        name_words = [word for word in expected_name_normalized.split() if len(word) > 2]
        if name_words:
            # Contar cuántas palabras del nombre se encuentran en el texto
            matches = sum(1 for word in name_words if word in text_normalized)
            # Si encontramos al menos el 60% de las palabras del nombre
            if matches >= len(name_words) * 0.6:
                result['name_match'] = True
            else:
                result['errors'].append("nombre")
        else:
            result['errors'].append("nombre")

        result['is_valid'] = result['document_match'] and result['name_match']

        logger.info(
            f"Validación de fórmula: "
            f"documento={result['document_match']}, "
            f"nombre={result['name_match']}"
        )

        return result


class BotController:
    """Controlador principal del bot de Telegram para gestión de solicitudes de medicamentos"""

    SESSION_EXPIRY_HOURS = 12
    MAX_MEDICATIONS = 10
    MAX_OCR_ATTEMPTS = 2  # Máximo 2 intentos de validación OCR

    def __init__(self):
        self.__application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self.__sessions: List[Dict[str, Any]] = []

    # ========== GESTIÓN DE SESIONES ==========

    def __create_session(self, telegram_id: int, documento: Optional[str] = None) -> Dict[str, Any]:
        """Crea una nueva sesión para el usuario"""
        session = {
            "telegram_id": telegram_id,
            "documento": documento,
            "session_data": {
                "documento": documento,
                "nombre": None,
                "direccion_beneficiario": None,
                "edad": None,
                "medication_count": 0,
                "photos_uploaded": 0,
                "ocr_attempts": 0,
                "pending_files": [],  # Archivos pendientes de procesar
            },
            "step": SessionSteps.NEW_USER,
            "is_active": True,
            "is_completed": False,
            "is_cancelled": False,
            "is_error": False,
            "error_message": None,
            "last_activity": datetime.now(),
        }
        self.__sessions.append(session)
        logger.info(f"[{telegram_id}] Nueva sesión creada")
        return session

    def __find_active_session(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Encuentra la sesión activa de un usuario"""
        return next(
            (s for s in self.__sessions if s["telegram_id"] == telegram_id and s["is_active"]),
            None
        )

    def __update_session(
        self,
        telegram_id: int,
        step: str,
        session_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Actualiza el estado de la sesión"""
        session = self.__find_active_session(telegram_id)
        if not session:
            session = self.__create_session(telegram_id)

        session["step"] = step
        session["last_activity"] = datetime.now()

        if session_data:
            session["session_data"].update(session_data)
            if "documento" in session_data and session_data["documento"]:
                session["documento"] = session_data["documento"]

        logger.info(f"[{telegram_id}] Sesión actualizada -> Step: {step}")
        return session

    def __update_last_activity(self, telegram_id: int) -> None:
        """Actualiza el timestamp de última actividad"""
        session = self.__find_active_session(telegram_id)
        if session:
            session["last_activity"] = datetime.now()

    def __is_session_expired(self, telegram_id: int) -> bool:
        """Verifica si la sesión ha expirado por inactividad"""
        session = self.__find_active_session(telegram_id)
        if not session or not session.get("last_activity"):
            return False

        elapsed = datetime.now() - session["last_activity"]
        elapsed_hours = elapsed.total_seconds() / 3600

        if elapsed_hours > self.SESSION_EXPIRY_HOURS:
            logger.info(f"[{telegram_id}] ⏰ Sesión expirada ({elapsed_hours:.2f}h)")
            self.__end_session(telegram_id, error_message="Sesión cerrada por inactividad")
            return True

        return False

    def __end_session(self, telegram_id: int, error_message: Optional[str] = None) -> None:
        """Finaliza una sesión activa"""
        session = self.__find_active_session(telegram_id)
        if session:
            session["is_active"] = False
            session["is_cancelled"] = True
            session["error_message"] = error_message
            session["last_activity"] = None
            logger.info(f"[{telegram_id}] Sesión finalizada: {error_message or 'Usuario cerró sesión'}")

    # ========== GESTIÓN DE USUARIOS ==========

    def get_user(self, telegram_id: int) -> List[stock_models.Solicitante]:
        """Obtiene usuarios por Telegram ID"""
        return list(stock_models.Solicitante.objects.filter(telegram_id=str(telegram_id)))

    def get_user_by_document(self, document: str) -> Optional[stock_models.Solicitante]:
        """Obtiene usuario por número de documento"""
        try:
            return stock_models.Solicitante.objects.get(documento=document)
        except stock_models.Solicitante.DoesNotExist:
            return None

    def create_user(self, telegram_id: int, session_data: Dict[str, Any]) -> stock_models.Solicitante:
        """Crea un nuevo usuario en la base de datos"""
        solicitante = stock_models.Solicitante(
            nombre=session_data.get("nombre"),
            documento=session_data.get("documento"),
            telegram_id=str(telegram_id),
            telefono=None,
            direccion_beneficiario=session_data.get("direccion_beneficiario"),
            edad=session_data.get("edad"),
        )
        solicitante.save()
        logger.info(f"[{telegram_id}] Usuario creado: {solicitante.id}")
        return solicitante

    def update_user(self, solicitante: stock_models.Solicitante, session_data: Dict[str, Any]) -> bool:
        """Actualiza datos de un usuario existente"""
        changed = False
        for field in ("nombre", "direccion_beneficiario", "edad"):
            val = session_data.get(field)
            if val is not None and getattr(solicitante, field) != val:
                setattr(solicitante, field, val)
                changed = True

        if changed:
            solicitante.save()
            logger.info(f"Usuario {solicitante.id} actualizado")

        return changed

    # ========== GESTIÓN DE SOLICITUDES ==========

    def create_request(self, telegram_id: int) -> Optional[stock_models.Solicitud]:
        """Crea una nueva solicitud en la base de datos"""
        session = self.__find_active_session(telegram_id)
        if not session:
            logger.error(f"[{telegram_id}] No se encontró sesión al crear solicitud")
            return None

        documento = session.get("documento")
        if not documento:
            logger.error(f"[{telegram_id}] Documento no establecido en sesión")
            return None

        solicitante = self.get_user_by_document(documento)
        if not solicitante:
            logger.error(f"[{telegram_id}] Usuario con documento {documento} no encontrado")
            return None

        solicitud = stock_models.Solicitud(
            solicitante=solicitante,
            solicitud_propia=True,
            estado=stock_models.Solicitud.Estado.PENDIENTE,
        )
        solicitud.save()
        logger.info(f"[{telegram_id}] Solicitud creada: {solicitud.id}")
        return solicitud

    def create_detail_request(
        self,
        telegram_id: int,
        session: Dict[str, Any]
    ) -> Optional[stock_models.DetalleSolicitud]:
        """Crea un detalle de solicitud para el medicamento seleccionado"""
        selected_medication_id = session["session_data"].get("selected_medication_id")
        quantity = session["session_data"].get("quantity")
        solicitud_obj = session["session_data"].get("solicitud_obj")

        if not all([selected_medication_id, quantity, solicitud_obj]):
            logger.error(f"[{telegram_id}] Datos incompletos para crear detalle de solicitud")
            return None

        try:
            medicamento_donado = stock_models.MedicamentoDonado.objects.get(id=selected_medication_id)
            detalle = stock_models.DetalleSolicitud(
                solicitud=solicitud_obj,
                medicamento=medicamento_donado.medicamento,
                cantidad_solicitada=quantity,
                cantidad_entregada=0,
            )
            detalle.save()
            logger.info(f"[{telegram_id}] Detalle de solicitud creado: {detalle.id}")
            return detalle
        except stock_models.MedicamentoDonado.DoesNotExist:
            logger.error(f"[{telegram_id}] Medicamento donado {selected_medication_id} no encontrado")
            return None

    def get_request_info(self, session: Dict[str, Any]) -> str:
        """Obtiene información sobre las solicitudes del usuario"""
        documento = session.get("documento") if session else None
        if not documento:
            return "No tienes solicitudes pendientes."

        solicitante = self.get_user_by_document(documento)
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

        # Contar por estado
        solicitud_count = solicitudes.values('estado').annotate(count=Count('estado'))
        for item in solicitud_count:
            emoji = estado_emojis.get(item['estado'], "")
            estado = item['estado'].capitalize()
            request_info += f"- {emoji} <b>{item['count']}</b> {estado}\n"

        # Última solicitud
        ultima = solicitudes.order_by('-fecha').first()
        if ultima:
            emoji = estado_emojis.get(ultima.estado, "")
            request_info += (
                f"\n🕓 La última solicitud del <b>{ultima.fecha.strftime('%d de %B de %Y')}</b> "
                f"está en estado {emoji} <b>{ultima.estado.capitalize()}</b>."
            )

        return request_info

    # ========== GESTIÓN DE MEDICAMENTOS ==========

    def get_available_medications(self, first_letter: str) -> Optional[str]:
        """Obtiene lista de medicamentos disponibles que inician con la letra especificada"""
        medicamentos = stock_models.MedicamentoDonado.objects.filter(
            medicamento__nombre_comercial__istartswith=first_letter,
            estado=stock_models.MedicamentoDonado.Estado.DISPONIBLE
        )

        if not medicamentos.exists():
            logger.warning(f"No se encontraron medicamentos con letra '{first_letter}'")
            return None

        medication_list = [
            f"{med.id}. {med.medicamento.nombre_comercial} - {med.medicamento.concentracion}"
            for med in medicamentos
        ]

        return "\n".join(medication_list)

    def validate_medication_quantity(
        self,
        medication_id: int,
        requested_quantity: int
    ) -> tuple[bool, Optional[int], Optional[str]]:
        """Valida la cantidad solicitada contra la disponible"""
        try:
            medication = stock_models.MedicamentoDonado.objects.get(id=medication_id)
            available = medication.cantidad

            if requested_quantity > available:
                return False, available, (
                    f"No hay suficiente cantidad del medicamento seleccionado. ❌\n\n"
                    f"Solo hay {available} unidades disponibles."
                )

            return True, available, None

        except stock_models.MedicamentoDonado.DoesNotExist:
            return False, None, "El medicamento seleccionado no existe."

    # ========== GESTIÓN DE ARCHIVOS Y OCR ==========

    async def save_file(
        self,
        update: Update,
        solicitud_obj: stock_models.Solicitud
    ) -> Optional[Tuple[stock_models.Formula, str]]:
        """
        Guarda archivo (foto o documento) en la solicitud
        
        Returns:
            Tupla de (Formula object, file_path) o None si falla
        """
        try:
            photo_path_tmp = None

            # Procesar documento
            if update.message.document:
                doc = update.message.document
                photo_file = await doc.get_file()
                ext = os.path.splitext(doc.file_name)[1] or ".jpg"
                photo_dir = Path(settings.BASE_DIR) / "photos"
                photo_dir.mkdir(exist_ok=True)
                photo_path_tmp = str(photo_dir / f"{doc.file_unique_id}{ext}")
                await photo_file.download_to_drive(photo_path_tmp)

            # Procesar foto
            elif update.message.photo:
                photo = update.message.photo[-1]
                photo_file = await photo.get_file()
                photo_dir = Path(settings.BASE_DIR) / "photos"
                photo_dir.mkdir(exist_ok=True)
                photo_path_tmp = str(photo_dir / f"{photo.file_unique_id}.jpg")
                await photo_file.download_to_drive(photo_path_tmp)

            # Guardar en BD
            if photo_path_tmp:
                photo_path = Path(photo_path_tmp)
                with photo_path.open('rb') as photo_file:
                    django_file = django_files.File(photo_file, name=photo_path.name)
                    formula = stock_models.Formula.objects.create(
                        solicitud=solicitud_obj,
                        archivo_formula=django_file,
                    )
                    logger.info(f"Archivo guardado para solicitud {solicitud_obj.id}")
                    return formula, photo_path_tmp

        except Exception as e:
            logger.exception(f"Error guardando archivo: {e}")

        return None

    async def process_multiple_files_with_validation(
        self,
        update: Update,
        telegram_id: int,
        session: Dict[str, Any]
    ) -> None:
        """
        Procesa múltiples archivos (fotos/PDFs) concatenando el texto y validando una sola vez
        """
        solicitud_obj = session["session_data"].get("solicitud_obj")
        if not solicitud_obj:
            await update.message.reply_text("❌ No hay una solicitud activa")
            return

        # Guardar archivo(s) actual(es)
        files_to_process = []
        
        # Guardar archivo actual
        result = await self.save_file(update, solicitud_obj)
        if result:
            formula_obj, file_path = result
            files_to_process.append(file_path)
            session["session_data"]["photos_uploaded"] = session["session_data"].get("photos_uploaded", 0) + 1

        # Esperar un momento por si vienen más archivos
        await asyncio.sleep(1.5)

        # Extraer texto de todos los archivos y concatenar
        await update.message.reply_text(
            "🔍 Analizando documento(s), por favor espera...",
            reply_markup=ReplyKeyboardRemove()
        )

        combined_text = ""
        for file_path in files_to_process:
            extracted_text = OCRProcessor.extract_text_from_file(file_path)
            if extracted_text:
                combined_text += extracted_text + "\n\n"

        # Incrementar contador de intentos
        session["session_data"]["ocr_attempts"] = session["session_data"].get("ocr_attempts", 0) + 1
        current_attempt = session["session_data"]["ocr_attempts"]

        if not combined_text or len(combined_text) < 50:
            # Error en OCR
            if current_attempt >= self.MAX_OCR_ATTEMPTS:
                # Ya agotó los 2 intentos, forzar a descripción manual
                await update.message.reply_text(
                    "❌ No se pudo leer el texto del documento después de 2 intentos.\n\n"
                    "Vamos a continuar describiendo los medicamentos manualmente.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, session["session_data"])
                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
            else:
                # Primer intento fallido, permitir un segundo intento
                await update.message.reply_text(
                    "❌ No se pudo leer el texto del documento. La imagen puede estar borrosa o en mal estado.\n\n"
                    f"📷 Tienes {self.MAX_OCR_ATTEMPTS - current_attempt} intento(s) más.\n\n"
                    "¿Qué deseas hacer?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[
                            KeyboardButton("📷 Intentar con otra foto"),
                            KeyboardButton("📝 Describir medicamentos manualmente")
                        ]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO_VALIDATION, session["session_data"])
            return

        # Validar contenido
        expected_document = session["session_data"].get("documento")
        expected_name = session["session_data"].get("nombre")

        validation_result = FormulaValidator.validate_formula(
            combined_text,
            expected_document,
            expected_name
        )

        logger.info(f"[{telegram_id}] Resultado validación OCR (intento {current_attempt}): {validation_result}")

        # Validación exitosa
        if validation_result['is_valid']:
            await update.message.reply_html(
                f"📋 Documento: Verificado\n"
                f"👤 Nombre: Verificado\n\n"
                f"✅ ¡Gracias! Hemos recibido todos tus archivos y tu solicitud fue registrada. "
                f"Te notificaremos cuando esté lista.",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Finalizar sesión exitosamente
            self.__end_session(telegram_id, "Solicitud completada exitosamente")
            
        else:
            # Validación fallida
            errors = validation_result['errors']
            doc_status = "✅ Verificado" if validation_result['document_match'] else "❌ No verificado"
            name_status = "✅ Verificado" if validation_result['name_match'] else "❌ No verificado"
            
            if current_attempt >= self.MAX_OCR_ATTEMPTS:
                # Ya agotó los 2 intentos, forzar a descripción manual
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    f"⚠️ No se pudo validar después de {self.MAX_OCR_ATTEMPTS} intentos.\n\n"
                    f"Vamos a continuar describiendo los medicamentos manualmente.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, session["session_data"])
                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
            else:
                # Primer intento fallido, permitir un segundo intento
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    f"⚠️ Por favor corrige o revisa la imagen.\n\n"
                    f"📷 Tienes {self.MAX_OCR_ATTEMPTS - current_attempt} intento(s) más.\n\n"
                    f"¿Qué deseas hacer?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[
                            KeyboardButton("📷 Intentar con otra foto"),
                            KeyboardButton("📝 Describir medicamentos manualmente")
                        ]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO_VALIDATION, session["session_data"])

    # ========== COMANDOS Y HANDLERS ==========

    async def wellcome_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Mensaje de bienvenida y inicio de sesión"""
        telegram_id = update.effective_user.id

        # Verificar sesión activa
        session = self.__find_active_session(telegram_id)
        if session and session.get("is_active"):
            await update.message.reply_text(
                "👋 Ya tienes una sesión activa. Completa la sesión actual o usa /salir para cerrarla."
            )
            return

        # Crear nueva sesión
        session = self.__create_session(telegram_id)

        await update.message.reply_html(
            "👋 ¡Hola! Bienvenido al sistema de donación de medicamentos. 💊🤝\n\n"
            "Antes de continuar, por favor acepta nuestra <b>Política de Tratamiento de Datos</b> 📄🔒.\n"
            "🔗 <a href='https://www.donacionmedicamentos.com/politica-de-tratamiento-de-datos'>Leer política</a>\n\n"
            "Si estás de acuerdo, presiona el botón <b>Acepto</b> para continuar. ✅",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("Acepto ✅")]],
                one_time_keyboard=True,
                selective=True,
            ),
        )

    async def end_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Finaliza manualmente la sesión del usuario"""
        telegram_id = update.effective_user.id
        session = self.__find_active_session(telegram_id)

        if not session:
            await update.message.reply_text("No tienes ninguna sesión activa.")
            return

        self.__end_session(telegram_id, "Sesión cerrada por el usuario")

        await update.message.reply_text(
            "✅ Tu sesión ha sido cerrada correctamente.\n"
            "Puedes iniciar una nueva con /iniciar o escribiendo Hola."
        )

    async def request_session_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Controla el flujo de la sesión paso a paso"""
        telegram_id = update.effective_user.id
        message = update.message
        text = message.text.strip() if message.text else ""

        # Verificar sesión activa
        session = self.__find_active_session(telegram_id)
        if not session:
            await update.message.reply_text(
                "⚠️ No tienes ninguna sesión activa. Usa /iniciar o escribe Hola para comenzar."
            )
            return

        # Verificar expiración
        if self.__is_session_expired(telegram_id):
            await update.message.reply_text(
                "⏰ Tu sesión ha expirado por inactividad.\n"
                "Por favor, inicia una nueva sesión con /iniciar o Hola."
            )
            return

        # Actualizar actividad
        self.__update_last_activity(telegram_id)

        step = session.get("step")

        # ========== STEP: NUEVA SESIÓN / POLÍTICA ==========
        if step == SessionSteps.NEW_USER:
            logger.info(f"[{telegram_id}] Política aceptada -> solicitando documento")
            self.__update_session(telegram_id, SessionSteps.REQ_DOCUMENT, {"documento": None})

            await update.message.reply_text(
                "📝 Por favor, escribe el <b>número de documento</b> de la persona que necesita los medicamentos.\n\n"
                "Ejemplo: <code>123456789</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return

        # ========== STEP: DOCUMENTO ==========
        if step == SessionSteps.REQ_DOCUMENT:
            if not text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe un número de documento válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            document_number = text
            logger.info(f"[{telegram_id}] Documento recibido: {document_number}")

            # Verificar usuarios existentes
            user_list = self.get_user(telegram_id)
            user_by_document = self.get_user_by_document(document_number)

            # Buscar coincidencia
            user_match = None
            for u in user_list:
                if user_by_document and u.id == user_by_document.id:
                    user_match = u
                    break

            # Usuario existente
            if user_match:
                self.__update_session(telegram_id, SessionSteps.KNOWN_USER, {
                    "documento": user_match.documento,
                    "nombre": user_match.nombre,
                    "direccion_beneficiario": user_match.direccion_beneficiario,
                    "edad": user_match.edad,
                })

                first_name = user_match.nombre.split()[0] if user_match.nombre else "Usuario"
                await update.message.reply_html(
                    f"👋 ¡Hola {first_name}! He verificado tu documento {document_number}.\n\n"
                    "¿Los siguientes datos están correctos?\n"
                    f"<b>Edad:</b> {user_match.edad}\n"
                    f"<b>Dirección:</b> {user_match.direccion_beneficiario}\n\n"
                    "Si todo está correcto, presiona <b>Sí, correcto ✅</b> para continuar.",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("Sí, correcto ✅"), KeyboardButton("No, corregir ✏️")]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
                return

            # Documento existe con otro telegram_id
            elif user_by_document:
                await update.message.reply_text(
                    "⚠️ Este documento ya está registrado con otro usuario. "
                    "Revisa el número ingresado."
                )
                return

            # Usuario nuevo
            else:
                self.__update_session(telegram_id, SessionSteps.REQ_NAME, {"documento": document_number})
                await update.message.reply_text(
                    "🙋‍♂️ ¡Gracias! Ahora, por favor escribe el <b>nombre completo</b> de la persona que necesita los medicamentos.\n\n"
                    "Ejemplo: <code>Juan Pérez</code>",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
            return

        # ========== STEP: NOMBRE ==========
        if step == SessionSteps.REQ_NAME:
            if not text:
                await update.message.reply_text(
                    "Por favor, escribe un nombre válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"[{telegram_id}] Nombre recibido: {text}")
            self.__update_session(telegram_id, SessionSteps.REQ_AGE, {"nombre": text})

            await update.message.reply_text(
                "🎂 ¡Perfecto! Ahora, por favor escribe la <b>edad</b> de la persona que necesita los medicamentos.",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return

        # ========== STEP: EDAD ==========
        if step == SessionSteps.REQ_AGE:
            if not text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe una edad válida (número entero).",
                    reply_markup=ForceReply(selective=True),
                )
                return

            age = int(text)
            logger.info(f"[{telegram_id}] Edad recibida: {age}")
            self.__update_session(telegram_id, SessionSteps.REQ_ADDRESS, {"edad": age})

            await update.message.reply_text(
                "🏠 ¡Genial! Ahora, por favor escribe la <b>dirección</b> de la persona que necesita los medicamentos.\n\n"
                "Ejemplo: <code>Calle 123 #45-67, Barrio Centro</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return

        # ========== STEP: DIRECCIÓN ==========
        if step == SessionSteps.REQ_ADDRESS:
            if not text:
                await update.message.reply_text(
                    "Por favor escribe una dirección válida.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"[{telegram_id}] Dirección recibida: {text}")

            # Actualizar y crear/actualizar usuario
            self.__update_session(telegram_id, SessionSteps.KNOWN_USER, {"direccion_beneficiario": text})

            documento = session["session_data"].get("documento")
            solicitante = self.get_user_by_document(documento)

            if not solicitante:
                solicitante = self.create_user(telegram_id, session["session_data"])
            else:
                self.update_user(solicitante, session["session_data"])

            await update.message.reply_text(
                f"✅ ¡Registro completado!\n\n"
                f"🙋‍♂️ <b>Nombre:</b> {solicitante.nombre}\n"
                f"🆔 <b>Documento:</b> {solicitante.documento}\n"
                f"🏠 <b>Dirección:</b> {solicitante.direccion_beneficiario}\n"
                f"🎂 <b>Edad:</b> {solicitante.edad}\n\n"
                "¿Qué deseas hacer ahora?",
                reply_markup=ReplyKeyboardMarkup(
                    [[
                        KeyboardButton("💊 Solicitar medicamentos"),
                        KeyboardButton("📋 Consultar solicitudes")
                    ]],
                    one_time_keyboard=True,
                    selective=True,
                ),
                parse_mode="HTML",
            )
            return

        # ========== STEP: USUARIO CONOCIDO ==========
        if step == SessionSteps.KNOWN_USER:
            text_lower = text.lower()

            # Solicitar medicamentos
            if "solicitar" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_MEDICATIONS, {})

                await update.message.reply_text(
                    "💊 ¿Cómo deseas solicitar los medicamentos?\n\n"
                    "Puedes describirlos uno por uno o subir una foto/PDF de la receta médica.",
                    reply_markup=ReplyKeyboardMarkup(
                        [[
                            KeyboardButton("📝 Describir medicamentos"),
                            KeyboardButton("📷 Subir receta médica")
                        ]],
                        one_time_keyboard=True,
                        selective=True,
                    ),
                    parse_mode="HTML"
                )
                return

            # Consultar solicitudes
            if "consultar" in text_lower:
                info = self.get_request_info(session)
                await update.message.reply_html(info)
                return

            # Confirmar datos
            if text_lower.startswith(("sí", "si")) or "correcto" in text_lower:
                await update.message.reply_text(
                    "Perfecto. ¿Qué deseas hacer ahora?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[
                            KeyboardButton("💊 Solicitar medicamentos"),
                            KeyboardButton("📋 Consultar solicitudes")
                        ]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
                return

            # Corregir datos
            if text_lower.startswith("no") or "corregir" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_AGE, {})
                await update.message.reply_text(
                    "Entendido. Vamos a actualizar tu información. 🔄\n\n"
                    "🎂 Por favor escribe la <b>edad</b> de la persona que necesita los medicamentos.",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return

            # Respuesta no válida
            await update.message.reply_text(
                "No entendí tu respuesta. Selecciona una opción del menú.",
                reply_markup=ReplyKeyboardMarkup(
                    [[
                        KeyboardButton("💊 Solicitar medicamentos"),
                        KeyboardButton("📋 Consultar solicitudes")
                    ]],
                    one_time_keyboard=True,
                    selective=True
                )
            )
            return

        # ========== STEP: MÉTODO DE SOLICITUD ==========
        if step == SessionSteps.REQ_MEDICATIONS:
            text_clean = "".join(c for c in text.lower() if c.isalnum() or c.isspace())

            # Opción 1: Describir medicamentos
            if "describir" in text_clean or "manual" in text_clean:
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, {})

                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            # Opción 2: Subir receta médica con OCR
            if "subir" in text_clean or "receta" in text_clean or "foto" in text_clean:
                # Crear solicitud inmediatamente
                solicitud_obj = self.create_request(telegram_id)
                if not solicitud_obj:
                    await update.message.reply_text(
                        "❌ No se pudo crear la solicitud. Intenta más tarde."
                    )
                    return

                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO, {
                    "solicitud_obj": solicitud_obj
                })

                await update.message.reply_text(
                    "📄 Por favor, sube el documento en <b>PDF</b> o una <b>imagen clara</b> de la fórmula médica.\n\n"
                    "💡 <b>Asegúrate de que se vean claramente:</b>\n"
                    "  • Nombre del paciente\n"
                    "  • Número de documento\n"
                    "  • Lista de medicamentos\n\n"
                    "🔍 El sistema validará automáticamente la información.\n\n"
                    "📎 Puedes enviar varias fotos a la vez si lo necesitas.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML"
                )
                return

            # Respuesta no válida
            await update.message.reply_text(
                "No entendí tu respuesta. ¿Deseas describir los medicamentos o subir una receta?",
                reply_markup=ReplyKeyboardMarkup(
                    [[
                        KeyboardButton("📝 Describir medicamentos"),
                        KeyboardButton("📷 Subir receta médica")
                    ]],
                    one_time_keyboard=True,
                    selective=True
                )
            )
            return

        # ========== STEP: CANTIDAD DE MEDICAMENTOS ==========
        if step == SessionSteps.REQ_MED_COUNT:
            if not text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe un número entero válido.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            count = int(text)
            if count <= 0 or count > self.MAX_MEDICATIONS:
                await update.message.reply_text(
                    f"El número debe estar entre 1 y {self.MAX_MEDICATIONS}.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            # Crear solicitud
            solicitud_obj = self.create_request(telegram_id)
            if not solicitud_obj:
                await update.message.reply_text(
                    "❌ No se pudo crear la solicitud. Intenta más tarde."
                )
                return

            self.__update_session(telegram_id, SessionSteps.REQ_MED_DESCRIPTION, {
                "medication_count": count,
                "solicitud_obj": solicitud_obj,
            })

            await update.message.reply_text(
                "📝 Ahora vamos a solicitar los medicamentos uno por uno.\n\n"
                "💊 Por cada medicamento te pediremos:\n"
                "1️⃣ Primera letra del nombre\n"
                "2️⃣ Selección del medicamento\n"
                "3️⃣ Cantidad necesaria\n\n"
                "Cuando estés listo, presiona 'Continuar'.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Continuar ▶️"), KeyboardButton("Cancelar ❌")]],
                    one_time_keyboard=True,
                    selective=True,
                )
            )
            return

        # ========== STEP: DESCRIPCIÓN DE MEDICAMENTOS ==========
        if step == SessionSteps.REQ_MED_DESCRIPTION:
            text_lower = text.lower()

            if "continuar" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_MED_FIRST_LETTER, {})

                await update.message.reply_text(
                    "🔤 Por favor, escribe la <b>primera letra</b> del medicamento <b>1</b>.\n\n"
                    "💡 Ejemplo: Si buscas 'Acetaminofén', escribe <b>A</b>",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return

            if "cancel" in text_lower or "cancelar" in text_lower:
                solicitud_obj = session["session_data"].get("solicitud_obj")
                if solicitud_obj:
                    try:
                        solicitud_obj.estado = stock_models.Solicitud.Estado.RECHAZADA
                        solicitud_obj.observaciones = f"Cancelada por usuario (telegram {telegram_id})"
                        solicitud_obj.save()
                    except Exception as e:
                        logger.error(f"Error al cancelar solicitud: {e}")

                self.__end_session(telegram_id, "Cancelado por usuario")
                await update.message.reply_text(
                    "❌ Solicitud cancelada. Puedes iniciar una nueva con /iniciar o Hola.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return

            await update.message.reply_text(
                "Por favor presiona 'Continuar' cuando estés listo.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Continuar ▶️"), KeyboardButton("Cancelar ❌")]],
                    one_time_keyboard=True,
                    selective=True
                )
            )
            return

        # ========== STEP: PRIMERA LETRA ==========
        if step == SessionSteps.REQ_MED_FIRST_LETTER:
            first_letter = text.upper()
            if not first_letter.isalpha() or len(first_letter) != 1:
                await update.message.reply_text(
                    "Por favor escribe una única letra válida.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            meds_text = self.get_available_medications(first_letter)
            if not meds_text:
                await update.message.reply_text(
                    f"😕 No se encontraron medicamentos que comiencen con '{first_letter}'.\n\n"
                    "🔄 Por favor, intenta con otra letra.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            self.__update_session(telegram_id, SessionSteps.REQ_MED_LIST_CHOSEN, {"first_letter": first_letter})

            await update.message.reply_text(
                f"💊 Medicamentos disponibles con '{first_letter}':\n\n{meds_text}\n\n"
                "Escribe el <b>ID</b> del medicamento que deseas solicitar.",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return

        # ========== STEP: SELECCIÓN DE MEDICAMENTO ==========
        if step == SessionSteps.REQ_MED_LIST_CHOSEN:
            try:
                selected_id = int(text)
            except (ValueError, TypeError):
                await update.message.reply_text(
                    "Por favor escribe un ID válido (número).",
                    reply_markup=ForceReply(selective=True)
                )
                return

            first_letter = session["session_data"].get("first_letter")
            medicamento_exists = stock_models.MedicamentoDonado.objects.filter(
                id=selected_id,
                estado=stock_models.MedicamentoDonado.Estado.DISPONIBLE,
                medicamento__nombre_comercial__istartswith=first_letter
            ).exists()

            if not medicamento_exists:
                await update.message.reply_text(
                    "❌ ID de medicamento no válido o no disponible. Intenta otro ID.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            self.__update_session(telegram_id, SessionSteps.REQ_MED_QUANTITY, {"selected_medication_id": selected_id})

            await update.message.reply_text(
                "🔢 ¿Cuántas unidades de este medicamento necesitas?",
                reply_markup=ForceReply(selective=True)
            )
            return

        # ========== STEP: CANTIDAD ==========
        if step == SessionSteps.REQ_MED_QUANTITY:
            if not text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe una cantidad válida (número entero).",
                    reply_markup=ForceReply(selective=True)
                )
                return

            quantity = int(text)
            if quantity <= 0:
                await update.message.reply_text(
                    "La cantidad debe ser mayor que cero.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            # Validar disponibilidad
            selected_med_id = session["session_data"].get("selected_medication_id")
            is_valid, available, error_msg = self.validate_medication_quantity(selected_med_id, quantity)

            if not is_valid:
                await update.message.reply_text(error_msg, reply_markup=ForceReply(selective=True))
                return

            # Crear detalle
            session["session_data"]["quantity"] = quantity
            detalle = self.create_detail_request(telegram_id, session)

            if not detalle:
                await update.message.reply_text(
                    "❌ Error al crear el detalle. Intenta de nuevo.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            # Decrementar contador
            session["session_data"]["medication_count"] -= 1
            remaining = session["session_data"]["medication_count"]

            if remaining > 0:
                # Pedir siguiente medicamento
                self.__update_session(telegram_id, SessionSteps.REQ_MED_FIRST_LETTER, {})
                await update.message.reply_text(
                    f"✅ Medicamento agregado.\n\n"
                    f"🔤 Ahora escribe la primera letra del siguiente medicamento (quedan {remaining}).",
                    reply_markup=ForceReply(selective=True)
                )
                return
            else:
                # Pedir foto final (obligatoria pero sin validación OCR en flujo manual)
                self.__update_session(telegram_id, SessionSteps.REQ_MORE_PHOTOS, {})
                await update.message.reply_text(
                    "✅ ¡Perfecto! Ya hemos registrado todos los medicamentos.\n\n"
                    "📸 Ahora, por favor <b>sube una foto o PDF de la receta médica</b> para completar tu solicitud.\n\n"
                    "🩺💊 Este paso es <b>obligatorio</b>.\n\n"
                    "📎 Puedes enviar varias fotos a la vez si lo necesitas.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML",
                )
                return

        # ========== STEP: VALIDACIÓN DE FOTO ==========
        if step == SessionSteps.REQ_PHOTO_VALIDATION:
            text_lower = text.lower()
            
            # Intentar con otra foto
            if "foto" in text_lower or "intentar" in text_lower or "otra" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO, session["session_data"])
                await update.message.reply_text(
                    "📷 Por favor, sube otra foto más clara de la fórmula médica.\n\n"
                    "💡 Asegúrate de que:\n"
                    "  • La imagen esté bien iluminada\n"
                    "  • El texto sea legible\n"
                    "  • No esté borrosa\n\n"
                    "📎 Puedes enviar varias fotos a la vez si lo necesitas.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            
            # Cambiar a modo manual
            if "describir" in text_lower or "manual" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, {})
                await update.message.reply_text(
                    "📝 Entendido. Vamos a describir los medicamentos manualmente.\n\n"
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
                return
            
            # Respuesta no válida
            await update.message.reply_text(
                "Por favor selecciona una opción válida.",
                reply_markup=ReplyKeyboardMarkup(
                    [[
                        KeyboardButton("📷 Intentar con otra foto"),
                        KeyboardButton("📝 Describir medicamentos manualmente")
                    ]],
                    one_time_keyboard=True,
                    selective=True
                )
            )
            return

        # ========== STEP: SUBIDA DE FOTO CON OCR ==========
        if step == SessionSteps.REQ_PHOTO:
            # Archivo recibido
            if update.message.document or update.message.photo:
                await self.process_multiple_files_with_validation(update, telegram_id, session)
                return

            # Texto recibido
            elif text:
                text_lower = text.lower()
                
                # Cambiar a modo manual
                if "describir" in text_lower or "manual" in text_lower:
                    self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, {})
                    await update.message.reply_text(
                        "📝 Entendido. Vamos a describir los medicamentos manualmente.\n\n"
                        "🔢 ¿Cuántos medicamentos vas a solicitar?",
                        reply_markup=ForceReply(selective=True)
                    )
                    return

                # Respuesta no válida
                await update.message.reply_text(
                    "📄 Por favor sube una foto o PDF de la fórmula médica.",
                    reply_markup=ForceReply(selective=True)
                )
                return

        # ========== STEP: MÁS FOTOS (FLUJO MANUAL) ==========
        if step == SessionSteps.REQ_MORE_PHOTOS:
            # Archivo recibido - solo guardar sin validar (flujo manual)
            if update.message.document or update.message.photo:
                solicitud_obj = session["session_data"].get("solicitud_obj")
                if solicitud_obj:
                    result = await self.save_file(update, solicitud_obj)
                    if result:
                        session["session_data"]["photos_uploaded"] = session["session_data"].get("photos_uploaded", 0) + 1
                        
                        # Finalizar inmediatamente después de subir foto
                        self.__end_session(telegram_id, "Flujo completado")
                        
                        await update.message.reply_text(
                            "✅ ¡Gracias! Hemos recibido todos tus archivos y tu solicitud fue registrada. "
                            "Te notificaremos cuando esté lista.",
                            reply_markup=ReplyKeyboardRemove()
                        )
                    else:
                        await update.message.reply_text(
                            "❌ Error guardando la foto. Intenta nuevamente.",
                            reply_markup=ForceReply(selective=True)
                        )
                return

            # Texto recibido - no debería llegar aquí en flujo normal
            elif text:
                await update.message.reply_text(
                    "📄 Por favor sube la foto o PDF de la receta médica.",
                    reply_markup=ForceReply(selective=True)
                )
                return

        # ========== PASO INESPERADO ==========
        logger.error(f"[{telegram_id}] Paso inesperado: {step}")
        self.__end_session(telegram_id, f"Paso inesperado: {step}")
        await update.message.reply_text(
            "❌ Ocurrió un error con la sesión. Por favor inicia de nuevo con /iniciar o Hola.",
            reply_markup=ReplyKeyboardRemove(),
        )

    async def handle_plain_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Maneja texto plano: comandos, saludos y flujo general"""
        msg = update.effective_message
        if not msg or not msg.text:
            return

        text = msg.text.strip()
        text_lower = text.lower()
        telegram_id = update.effective_user.id

        # Comandos de salida
        if re.search(r'\b(salir|cerrar)\b', text_lower, re.IGNORECASE):
            await self.end_session_command(update, context)
            return

        # Saludos (solo si no hay sesión activa)
        session = self.__find_active_session(telegram_id)
        is_active = bool(session and session.get("is_active"))

        if re.search(
            r'\b(hola|hi|buenas|buenos\s+días|buenos\s+dias|buenas\s+tardes|buenas\s+noches|buen\s+dia)\b',
            text_lower,
            re.IGNORECASE
        ):
            if not is_active:
                await self.wellcome_user(update, context)
            else:
                await msg.reply_text(
                    "👋 Ya tienes una sesión activa. Completa la sesión o usa /salir para cerrarla."
                )
            return

        # Flujo general de la sesión
        await self.request_session_step(update, context)

    # ========== INICIAR BOT ==========

    def run(self) -> None:
        """Inicia el bot y registra los handlers"""
        # Comandos
        self.__application.add_handler(CommandHandler("iniciar", self.wellcome_user))
        self.__application.add_handler(CommandHandler("salir", self.end_session_command))

        # Patrones de texto
        fin_pattern = re.compile(r'\b(salir|cerrar)\b', flags=re.IGNORECASE)
        self.__application.add_handler(
            MessageHandler(filters.TEXT & filters.Regex(fin_pattern), self.handle_plain_text)
        )

        saludos_pattern = re.compile(
            r'\b(hola|hi|buenas|buenos\s+días|buenos\s+dias|buenas\s+tardes|buenas\s+noches|buen\s+dia)\b',
            flags=re.IGNORECASE
        )
        self.__application.add_handler(
            MessageHandler(filters.TEXT & filters.Regex(saludos_pattern), self.handle_plain_text)
        )

        # Handler general (texto, documentos, fotos)
        self.__application.add_handler(
            MessageHandler(
                filters.TEXT | filters.Document.ALL | filters.PHOTO,
                self.request_session_step
            )
        )

        # Iniciar polling
        logger.info("🤖 Bot iniciado correctamente con OCR optimizado y límite de 2 intentos")
        self.__application.run_polling(allowed_updates=Update.ALL_TYPES)