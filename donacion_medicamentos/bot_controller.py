import logging
import os
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from django.conf import settings
from django.core import files as django_files
from django.db.models import Count

from stock import models as stock_models
from donacion_medicamentos.ocr import OCRProcessor
from telegram import ForceReply, Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


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
    REQ_PHONE = "REQUEST_PHONE"
    REQ_ADDRESS = "REQUEST_ADDRESS"
    REQ_AGE = "REQUEST_AGE"
    REQ_CONFIRM_DATA = "REQUEST_CONFIRM_DATA"
    KNOWN_USER = "KNOWN_USER"
    REQ_MEDICATIONS = "REQUEST_MEDICATIONS"
    REQ_MED_COUNT = "REQUEST_MED_COUNT"
    REQ_MED_DESCRIPTION = "REQUEST_MED_DESCRIPTION"
    REQ_MED_FIRST_LETTER = "REQUEST_MED_FIRST_LETTER"
    REQ_MED_LIST_CHOSEN = "REQUEST_MED_LIST_CHOSEN"
    REQ_PHOTO = "REQUEST_PHOTO"
    REQ_PHOTO_VALIDATION = "REQUEST_PHOTO_VALIDATION"
    REQ_MORE_PHOTOS = "REQUEST_MORE_PHOTOS"
    REQ_RELINK_CONFIRM = "REQUEST_RELINK_CONFIRM"
    REQ_RELINK_DOCUMENT = "REQUEST_RELINK_DOCUMENT"
    END = "END"


class FormulaValidator:
    """Validador de fórmulas médicas con validación flexible de nombres"""

    @staticmethod
    def normalize_text(text: str) -> str:
        if not text:
            return ""
        text = text.lower()
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ñ': 'n', 'ü': 'u'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def extract_document_number(text: str) -> List[str]:
        text_collapsed = re.sub(r'(?<=\d) (?=\d)', '', text)
        texts_to_search = [text, text_collapsed]
        patterns = [
            r'\b(\d{6,12})\b',
            r'(?:c\.?c\.?|cedula|documento|identificacion|identif)[^0-9]{0,10}(\d[\d ]{4,11}\d)',
        ]
        found_documents = []
        for search_text in texts_to_search:
            for pattern in patterns:
                matches = re.finditer(pattern, search_text, re.IGNORECASE)
                for match in matches:
                    doc = match.group(1) if match.lastindex else match.group(0)
                    doc = re.sub(r'\D', '', doc)
                    if 6 <= len(doc) <= 12:
                        found_documents.append(doc)
        unique_docs = list(set(found_documents))
        logger.info(f"🆔 Documentos encontrados: {unique_docs}")
        return unique_docs

    @staticmethod
    def validate_name_flexible(text_normalized: str, expected_name_normalized: str) -> Dict[str, Any]:
        result = {'matched': False, 'matched_words': [], 'strategy': None, 'confidence': 0.0}
        expected_words = [w for w in expected_name_normalized.split() if len(w) >= 3]
        if not expected_words:
            logger.warning("⚠️ No hay palabras válidas en el nombre esperado")
            return result

        logger.info(f"🔍 Buscando palabras: {expected_words}")

        matched_full = []
        for word in expected_words:
            if re.search(r'\b' + re.escape(word) + r'\b', text_normalized):
                matched_full.append(word)
        if len(matched_full) >= len(expected_words) * 0.5:
            result.update({'matched': True, 'matched_words': matched_full,
                           'strategy': 'palabras_completas',
                           'confidence': len(matched_full) / len(expected_words)})
            logger.info(f"✅ Nombre validado (palabras completas): {matched_full}")
            return result

        matched_partial = []
        for word in expected_words:
            if len(word) >= 4 and (word[:4] in text_normalized or word[-4:] in text_normalized):
                matched_partial.append(word)
        if len(matched_partial) >= len(expected_words) * 0.5:
            result.update({'matched': True, 'matched_words': matched_partial,
                           'strategy': 'palabras_parciales',
                           'confidence': len(matched_partial) / len(expected_words)})
            logger.info(f"✅ Nombre validado (parcial): {matched_partial}")
            return result

        all_letters_name = ''.join(expected_words)
        all_letters_text = text_normalized.replace(' ', '')
        matched_chars, text_idx = 0, 0
        for char in all_letters_name:
            found_idx = all_letters_text.find(char, text_idx)
            if found_idx != -1:
                matched_chars += 1
                text_idx = found_idx + 1
        char_match_ratio = matched_chars / len(all_letters_name) if all_letters_name else 0
        if char_match_ratio >= 0.7:
            result.update({'matched': True, 'matched_words': expected_words,
                           'strategy': 'secuencia_letras', 'confidence': char_match_ratio})
            logger.info(f"✅ Nombre validado (secuencia letras): {char_match_ratio:.1%}")
            return result

        apellidos = [w for w in expected_words if len(w) >= 4][-2:]
        if apellidos:
            matched_apellidos = [w for w in apellidos if w in text_normalized]
            if matched_apellidos:
                result.update({'matched': True, 'matched_words': matched_apellidos,
                               'strategy': 'apellidos',
                               'confidence': len(matched_apellidos) / len(apellidos)})
                logger.info(f"✅ Nombre validado (apellidos): {matched_apellidos}")
                return result

        logger.warning(f"❌ Nombre NO validado.")
        return result

    @staticmethod
    def validate_formula(text: str, expected_document: str, expected_name: str) -> Dict[str, Any]:
        result = {'is_valid': False, 'document_match': False, 'name_match': False,
                  'errors': [], 'debug_info': {}}

        if not text or len(text) < 50:
            result['errors'].append("Texto insuficiente o no se pudo leer el documento")
            logger.warning(f"⚠️ Validación fallida: texto muy corto ({len(text)} caracteres)")
            return result

        text_normalized = FormulaValidator.normalize_text(text)
        expected_name_normalized = FormulaValidator.normalize_text(expected_name)
        result['debug_info']['text_length'] = len(text)
        result['debug_info']['text_preview'] = text[:300]

        found_documents = FormulaValidator.extract_document_number(text)
        document_matched = expected_document in found_documents
        if not document_matched:
            for found in found_documents:
                if expected_document in found or found in expected_document:
                    document_matched = True
                    break

        if document_matched:
            result['document_match'] = True
        else:
            result['errors'].append("documento")
        result['debug_info']['found_documents'] = found_documents

        name_validation = FormulaValidator.validate_name_flexible(text_normalized, expected_name_normalized)
        result['name_match'] = name_validation['matched']
        result['debug_info']['name_validation'] = name_validation
        if not result['name_match']:
            result['errors'].append("nombre")

        result['is_valid'] = result['document_match'] and result['name_match']
        logger.info(f"📊 Resultado: doc={result['document_match']}, "
                    f"nombre={result['name_match']}, válido={result['is_valid']}")
        return result


class BotController:
    """Controlador principal del bot de Telegram"""

    SESSION_EXPIRY_HOURS = 12
    MAX_MEDICATIONS = 4
    MAX_OCR_ATTEMPTS = 2
    MAX_DOC_ATTEMPTS = 5

    def __init__(self):
        self.__application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self.__sessions: List[Dict[str, Any]] = []
        logger.info("🔧 Verificando configuración de OCR...")
        OCRProcessor.test_ocr_setup()

    # ========== GESTIÓN DE SESIONES ==========

    def __create_session(self, telegram_id: int, documento: Optional[str] = None) -> Dict[str, Any]:
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
                "doc_attempts": 0,
                "relink_ocr_attempts": 0,
                "pending_medications": [],
                "pending_files": [],
                "documento_relink": None,
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
        return next(
            (s for s in self.__sessions if s["telegram_id"] == telegram_id and s["is_active"]),
            None
        )

    def __update_session(self, telegram_id: int, step: str,
                         session_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        session = self.__find_active_session(telegram_id)
        if session:
            session["last_activity"] = datetime.now()

    def __is_session_expired(self, telegram_id: int) -> bool:
        session = self.__find_active_session(telegram_id)
        if not session or not session.get("last_activity"):
            return False
        elapsed = datetime.now() - session["last_activity"]
        if elapsed.total_seconds() / 3600 > self.SESSION_EXPIRY_HOURS:
            logger.info(f"[{telegram_id}] ⏰ Sesión expirada")
            self.__end_session(telegram_id, error_message="Sesión cerrada por inactividad")
            return True
        return False

    def __end_session(self, telegram_id: int, error_message: Optional[str] = None) -> None:
        session = self.__find_active_session(telegram_id)
        if session:
            session["is_active"] = False
            session["is_cancelled"] = True
            session["error_message"] = error_message
            session["last_activity"] = None
            logger.info(f"[{telegram_id}] Sesión finalizada: {error_message or 'Usuario cerró sesión'}")

    # ========== GESTIÓN DE USUARIOS ==========

    def get_user_by_document(self, document: str) -> Optional[stock_models.Solicitante]:
        try:
            return stock_models.Solicitante.objects.get(documento=document)
        except stock_models.Solicitante.DoesNotExist:
            return None

    def get_user_secure(
        self, telegram_id: int, document_number: str
    ) -> Tuple[Optional[stock_models.Solicitante], str]:
        user_by_doc = self.get_user_by_document(document_number)
        if not user_by_doc:
            return None, 'not_found'
        if user_by_doc.telegram_id == str(telegram_id):
            return user_by_doc, 'owner'
        logger.warning(f"[{telegram_id}] 🔒 Intento de acceso a documento ajeno: {document_number}")
        return None, 'forbidden'

    def create_user(self, telegram_id: int, session_data: Dict[str, Any]) -> stock_models.Solicitante:
        solicitante = stock_models.Solicitante(
            nombre=session_data.get("nombre"),
            documento=session_data.get("documento"),
            telegram_id=str(telegram_id),
            telefono=session_data.get("telefono"),
            direccion_beneficiario=session_data.get("direccion_beneficiario"),
            edad=session_data.get("edad"),
        )
        solicitante.save()
        logger.info(f"[{telegram_id}] Usuario creado: {solicitante.id}")
        return solicitante

    def update_user(self, solicitante: stock_models.Solicitante, session_data: Dict[str, Any]) -> bool:
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

    def relink_telegram_id(
        self, solicitante: stock_models.Solicitante, new_telegram_id: int
    ) -> None:
        old_id = solicitante.telegram_id
        solicitante.telegram_id = str(new_telegram_id)
        solicitante.save(update_fields=["telegram_id"])
        logger.info(
            f"[{new_telegram_id}] 🔗 telegram_id revinculado: {old_id} -> {new_telegram_id} "
            f"para documento {solicitante.documento}"
        )

    # ========== GESTIÓN DE SOLICITUDES ==========

    def _commit_full_request(
        self, telegram_id: int, session: Dict[str, Any]
    ) -> Optional[stock_models.Solicitud]:
        documento = session["session_data"].get("documento")
        if not documento:
            logger.error(f"[{telegram_id}] Commit fallido: no hay documento en sesión")
            return None
        solicitante = self.get_user_by_document(documento)
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
        for item in solicitudes.values('estado').annotate(count=Count('estado')):
            emoji = estado_emojis.get(item['estado'], "")
            request_info += f"- {emoji} <b>{item['count']}</b> {item['estado'].capitalize()}\n"
        ultima = solicitudes.order_by('-fecha').first()
        if ultima:
            emoji = estado_emojis.get(ultima.estado, "")
            request_info += (
                f"\n🕓 La última solicitud <b>#{ultima.id}</b> del <b>{ultima.fecha.strftime('%d de %B de %Y')}</b> "
                f"está en estado {emoji} <b>{ultima.estado.capitalize()}</b>."
            )        

        return request_info

    # ========== GESTIÓN DE MEDICAMENTOS ==========

    def get_available_medications(self, first_letter: str) -> Optional[str]:
        medicamentos = stock_models.Medicamento.objects.filter(
            nombre_comercial__istartswith=first_letter
        )
        if not medicamentos.exists():
            return None
        return "\n".join(
            f"{med.id}. {med.nombre_comercial} - {med.concentracion}"
            for med in medicamentos
        )

    # ========== GESTIÓN DE ARCHIVOS Y OCR ==========

    async def download_file_only(self, update: Update) -> Optional[str]:
        try:
            photo_path_tmp = None
            if update.message.document:
                doc = update.message.document
                photo_file = await doc.get_file()
                ext = os.path.splitext(doc.file_name)[1] or ".jpg"
                photo_dir = Path(settings.BASE_DIR) / "photos"
                photo_dir.mkdir(exist_ok=True)
                photo_path_tmp = str(photo_dir / f"{doc.file_unique_id}{ext}")
                await photo_file.download_to_drive(photo_path_tmp)
            elif update.message.photo:
                photo = update.message.photo[-1]
                photo_file = await photo.get_file()
                photo_dir = Path(settings.BASE_DIR) / "photos"
                photo_dir.mkdir(exist_ok=True)
                photo_path_tmp = str(photo_dir / f"{photo.file_unique_id}.jpg")
                await photo_file.download_to_drive(photo_path_tmp)
            return photo_path_tmp
        except Exception as e:
            logger.exception(f"Error descargando archivo: {e}")
            return None

    async def process_multiple_files_with_validation(
        self, update: Update, telegram_id: int, session: Dict[str, Any]
    ) -> None:
        file_path = await self.download_file_only(update)
        if not file_path:
            await update.message.reply_text("❌ Error al recibir el archivo. Intenta nuevamente.")
            return

        session["session_data"].setdefault("pending_files", []).append(file_path)
        session["session_data"]["photos_uploaded"] = session["session_data"].get("photos_uploaded", 0) + 1

        await asyncio.sleep(1.5)
        await update.message.reply_text(
            "🔍 Analizando documento(s), por favor espera...\n"
            "Este proceso puede tardar unos minutos, te notificaremos cuando terminemos de analizarlo.",
            reply_markup=ReplyKeyboardRemove()
        )

        combined_text = ""
        for fp in session["session_data"].get("pending_files", []):
            extracted = OCRProcessor.extract_text_from_file(fp)
            if extracted:
                combined_text += extracted + "\n\n"

        session["session_data"]["ocr_attempts"] = session["session_data"].get("ocr_attempts", 0) + 1
        current_attempt = session["session_data"]["ocr_attempts"]

        if not combined_text or len(combined_text) < 50:
            if current_attempt >= self.MAX_OCR_ATTEMPTS:
                await update.message.reply_text(
                    "❌ No se pudo leer el texto del documento después de 2 intentos.\n\n"
                    "Vamos a continuar describiendo los medicamentos manualmente.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, session["session_data"])
                await update.message.reply_text(
                    f"🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
            else:
                await update.message.reply_text(
                    "❌ No se pudo leer el texto del documento. La imagen puede estar borrosa o en mal estado.\n\n"
                    f"📷 Tienes {self.MAX_OCR_ATTEMPTS - current_attempt} intento(s) más.\n\n"
                    "¿Qué deseas hacer?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("📷 Intentar con otra foto"),
                          KeyboardButton("📝 Describir medicamentos manualmente")]],
                        one_time_keyboard=True, selective=True
                    )
                )
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO_VALIDATION, session["session_data"])
            return

        expected_document = session["session_data"].get("documento")
        expected_name = session["session_data"].get("nombre")
        validation_result = FormulaValidator.validate_formula(combined_text, expected_document, expected_name)
        logger.info(f"[{telegram_id}] Validación OCR intento {current_attempt}: {validation_result}")

        if validation_result['is_valid']:
            solicitud_obj = self._commit_full_request(telegram_id, session)
            if not solicitud_obj:
                await update.message.reply_text(
                    "❌ Error al guardar la solicitud. Intenta más tarde.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.__end_session(telegram_id, "Error en commit de solicitud")
                return

            for fp in session["session_data"].get("pending_files", []):
                try:
                    photo_path = Path(fp)
                    with photo_path.open('rb') as pf:
                        formula_obj = stock_models.Formula.objects.create(
                            solicitud=solicitud_obj,
                            archivo_formula=django_files.File(pf, name=photo_path.name),
                        )
                        texto_extraido = OCRProcessor.extract_text_from_file(fp)
                        if texto_extraido:
                            formula_obj.texto_ocr = texto_extraido
                            formula_obj.save(update_fields=["texto_ocr"])
                except Exception as e:
                    logger.warning(f"[{telegram_id}] Error guardando archivo en commit: {e}")

            try:
                solicitante = self.get_user_by_document(expected_document)
                if solicitante and not solicitante.verificado:
                    solicitante.verificado = True
                    solicitante.save(update_fields=["verificado"])
            except Exception as e:
                logger.warning(f"[{telegram_id}] Error actualizando 'verificado': {e}")

            await update.message.reply_html(
                "📋 Documento: Verificado\n"
                "👤 Nombre: Verificado\n\n"
                "✅ ¡Gracias! Hemos recibido todos tus archivos y tu solicitud fue registrada con el número <b>#{solicitud_obj.id}</b>.\n"
                "Te notificaremos cuando esté lista.",
                reply_markup=ReplyKeyboardRemove()
            )
            self.__end_session(telegram_id, "Solicitud completada exitosamente")

        else:
            doc_status = "✅ Verificado" if validation_result['document_match'] else "❌ No verificado"
            name_status = "✅ Verificado" if validation_result['name_match'] else "❌ No verificado"

            if current_attempt >= self.MAX_OCR_ATTEMPTS:
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    f"⚠️ No se pudo validar después de {self.MAX_OCR_ATTEMPTS} intentos.\n\n"
                    "Vamos a continuar describiendo los medicamentos manualmente.",
                    reply_markup=ReplyKeyboardRemove()
                )
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, session["session_data"])
                await update.message.reply_text(
                    f"🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
            else:
                await update.message.reply_html(
                    f"📋 Documento: {doc_status}\n"
                    f"👤 Nombre: {name_status}\n\n"
                    "⚠️ Por favor corrige o revisa la imagen.\n\n"
                    f"📷 Tienes {self.MAX_OCR_ATTEMPTS - current_attempt} intento(s) más.\n\n"
                    "¿Qué deseas hacer?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("📷 Intentar con otra foto"),
                          KeyboardButton("📝 Describir medicamentos manualmente")]],
                        one_time_keyboard=True, selective=True
                    )
                )
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO_VALIDATION, session["session_data"])

    # ========== COMANDOS Y HANDLERS ==========

    async def wellcome_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        telegram_id = update.effective_user.id
        session = self.__find_active_session(telegram_id)
        if session and session.get("is_active"):
            await update.message.reply_html(
                "👋 Ya tienes una sesión activa. Completa la sesión actual o usa salir para cerrarla."
            )
            return

        self.__create_session(telegram_id)

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
            f"Antes de continuar, por favor acepta nuestra <b>Política de Tratamiento de Datos</b> 📄🔒.\n"
            f"📋 <strong>Versión {version}</strong>\n"
            f"🔗 <a href='{url}'>Leer política</a>\n\n"
            f"Si estás de acuerdo, presiona el botón <b>Acepto</b> para continuar. ✅",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton('Acepto ✅')]],
                one_time_keyboard=True,
                selective=True,
            ),
        )

    async def handle_acepto(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    async def end_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        telegram_id = update.effective_user.id
        message = update.message
        text = message.text.strip() if message.text else ""

        session = self.__find_active_session(telegram_id)
        if not session:
            await update.message.reply_text(
                "⚠️ No tienes ninguna sesión activa. Usa /iniciar o escribe Hola para comenzar."
            )
            return

        if self.__is_session_expired(telegram_id):
            await update.message.reply_text(
                "⏰ Tu sesión ha expirado por inactividad.\n"
                "Por favor, inicia una nueva sesión con /iniciar o Hola."
            )
            return

        self.__update_last_activity(telegram_id)
        step = session.get("step")

        # ── NEW_USER ──────────────────────────────────────────────────────────
        if step == SessionSteps.NEW_USER:
            text_lower = text.lower()
            acepto = (
                "acepto" in text_lower
                or "acept" in text_lower
                or "✅" in text
                or "si" in text_lower
            )

            if not acepto:
                self.__end_session(telegram_id, "Usuario no aceptó política de datos")
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
            self.__update_session(telegram_id, SessionSteps.REQ_DOCUMENT, {"documento": None})
            await update.message.reply_text(
                "📝 Por favor, escribe el <b>número de documento</b> de la persona que necesita los medicamentos.\n\n"
                "Ejemplo: <code>123456789</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return

        # ── REQ_DOCUMENT ──────────────────────────────────────────────────────
        if step == SessionSteps.REQ_DOCUMENT:
            if not text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe un número de documento válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            document_number = text
            attempts = session["session_data"].get("doc_attempts", 0) + 1
            session["session_data"]["doc_attempts"] = attempts
            if attempts > self.MAX_DOC_ATTEMPTS:
                self.__end_session(telegram_id, "Demasiados intentos de documento")
                await update.message.reply_text(
                    "⚠️ Demasiados intentos. La sesión fue cerrada por seguridad.",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return

            logger.info(f"[{telegram_id}] Documento recibido: {document_number} (intento {attempts})")
            solicitante, status = self.get_user_secure(telegram_id, document_number)

            if status == 'owner':
                self.__update_session(telegram_id, SessionSteps.KNOWN_USER, {
                    "documento": solicitante.documento,
                    "nombre": solicitante.nombre,
                    "direccion_beneficiario": solicitante.direccion_beneficiario,
                    "edad": solicitante.edad,
                })
                first_name = solicitante.nombre.split()[0] if solicitante.nombre else "Usuario"
                await update.message.reply_html(
                    f"👋 ¡Hola {first_name}! He verificado tu documento {document_number}.\n\n"
                    "¿Los siguientes datos están correctos?\n"
                    f"<b>Edad:</b> {solicitante.edad}\n"
                    f"<b>Dirección:</b> {solicitante.direccion_beneficiario}\n\n"
                    "Si todo está correcto, presiona <b>Sí, correcto ✅</b> para continuar.",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("Sí, correcto ✅"), KeyboardButton("No, corregir ✏️")]],
                        one_time_keyboard=True, selective=True
                    )
                )

            elif status == 'not_found':
                self.__update_session(telegram_id, SessionSteps.REQ_NAME, {"documento": document_number})
                await update.message.reply_text(
                    "🙋‍♂️ ¡Gracias! Ahora, por favor escribe el <b>nombre completo</b> de la persona que necesita los medicamentos.\n\n"
                    "Ejemplo: <code>Juan Pérez</code>",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )

            else:  # forbidden
                self.__update_session(
                    telegram_id, SessionSteps.REQ_RELINK_CONFIRM,
                    {"documento_relink": document_number}
                )
                await update.message.reply_html(
                    f"⚠️ El documento <b>{document_number}</b> ya tiene una cuenta asociada.\n\n"
                    "¿Confirmas que este es tu número de documento?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("Sí, es el mío ✅"), KeyboardButton("No, corregir ✏️")]],
                        one_time_keyboard=True, selective=True
                    )
                )
            return

        # ── REQ_RELINK_CONFIRM ────────────────────────────────────────────────
        if step == SessionSteps.REQ_RELINK_CONFIRM:
            text_lower = text.lower()
            if "no" in text_lower or "corregir" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_DOCUMENT, {"documento_relink": None})
                await update.message.reply_text(
                    "Entendido. Por favor escribe nuevamente tu número de documento.",
                    reply_markup=ForceReply(selective=True)
                )
                return
            if "sí" in text_lower or "si" in text_lower or "mío" in text_lower or "mio" in text_lower:
                documento_relink = session["session_data"].get("documento_relink")
                self.__update_session(
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
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Sí, es el mío ✅"), KeyboardButton("No, corregir ✏️")]],
                    one_time_keyboard=True, selective=True
                )
            )
            return

        # ── REQ_RELINK_DOCUMENT ───────────────────────────────────────────────
        if step == SessionSteps.REQ_RELINK_DOCUMENT:
            if not (update.message.document or update.message.photo):
                await update.message.reply_text(
                    "📄 Por favor sube una foto o PDF de tu documento de identidad.\n\n"
                    "⚠️ Recuerda enviarlo como <b>Archivo</b> (📎 adjunto).",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return

            file_path = await self.download_file_only(update)
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
            solicitante = self.get_user_by_document(documento_relink)
            if not solicitante:
                self.__end_session(telegram_id, "Solicitante no encontrado en revinculación")
                await update.message.reply_text(
                    "❌ Ocurrió un error inesperado. Por favor inicia de nuevo con /iniciar o Hola.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return

            extracted_text = OCRProcessor.extract_text_from_file(file_path)
            validation_result = FormulaValidator.validate_formula(
                extracted_text or "", documento_relink, solicitante.nombre
            )
            logger.info(
                f"[{telegram_id}] Revinculación OCR intento {relink_attempt}: "
                f"doc={validation_result['document_match']} nombre={validation_result['name_match']}"
            )

            if validation_result['is_valid']:
                self.relink_telegram_id(solicitante, telegram_id)
                self.__update_session(telegram_id, SessionSteps.KNOWN_USER, {
                    "documento": solicitante.documento,
                    "nombre": solicitante.nombre,
                    "direccion_beneficiario": solicitante.direccion_beneficiario,
                    "edad": solicitante.edad,
                    "documento_relink": None,
                })
                first_name = solicitante.nombre.split()[0] if solicitante.nombre else "Usuario"
                await update.message.reply_html(
                    f"✅ ¡Identidad verificada! Bienvenido de nuevo, <b>{first_name}</b>.\n\n"
                    "Tu cuenta ha sido revinculada correctamente. ¿Qué deseas hacer ahora?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar solicitudes")]],
                        one_time_keyboard=True, selective=True
                    )
                )
            else:
                doc_status = "✅ Verificado" if validation_result['document_match'] else "❌ No verificado"
                name_status = "✅ Verificado" if validation_result['name_match'] else "❌ No verificado"
                if relink_attempt >= self.MAX_OCR_ATTEMPTS:
                    logger.warning(
                        f"[{telegram_id}] 🔒 Revinculación fallida tras {relink_attempt} intentos "
                        f"para documento {documento_relink}"
                    )
                    self.__end_session(telegram_id, "Revinculación fallida: intentos agotados")
                    await update.message.reply_text(
                        "❌ No fue posible verificar tu identidad.\n\n"
                        "Si necesitas ayuda, contacta a un administrador.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                else:
                    remaining = self.MAX_OCR_ATTEMPTS - relink_attempt
                    await update.message.reply_html(
                        f"📋 Documento: {doc_status}\n"
                        f"👤 Nombre: {name_status}\n\n"
                        f"⚠️ No se pudo verificar la identidad. Tienes {remaining} intento(s) más.\n\n"
                        "Por favor sube una imagen más clara de tu documento.",
                        reply_markup=ReplyKeyboardRemove()
                    )
            return

        # ── REQ_NAME ──────────────────────────────────────────────────────────
        if step == SessionSteps.REQ_NAME:
            if not text:
                await update.message.reply_text(
                    "Por favor, escribe un nombre válido.", reply_markup=ForceReply(selective=True)
                )
                return
            logger.info(f"[{telegram_id}] Nombre recibido: {text}")
            documento = session["session_data"].get("documento")
            self.__update_session(telegram_id, SessionSteps.REQ_CONFIRM_DATA, {"nombre": text})
            await update.message.reply_html(
                f"📋 Por favor confirma los datos:\n\n"
                f"🆔 <b>Documento:</b> {documento}\n"
                f"👤 <b>Nombre:</b> {text}\n\n"
                "¿Los datos son correctos?",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Sí, continuar ✅"), KeyboardButton("No, corregir ✏️")]],
                    one_time_keyboard=True, selective=True
                )
            )
            return

        # ── REQ_CONFIRM_DATA ──────────────────────────────────────────────────
        if step == SessionSteps.REQ_CONFIRM_DATA:
            text_lower = text.lower()
            if "sí" in text_lower or "si" in text_lower or "continuar" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_PHONE, {})
                await update.message.reply_text(
                    "📱 ¡Perfecto! Ahora escribe el <b>número de teléfono</b> de contacto.\n\n"
                    "Ejemplo: <code>3001234567</code>",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
                return
            if "no" in text_lower or "corregir" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_DOCUMENT, {"nombre": None})
                await update.message.reply_text(
                    "Entendido. Por favor escribe nuevamente el <b>número de documento</b>.",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
                return
            await update.message.reply_text(
                "Por favor selecciona una opción válida.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Corregir ✏️"), KeyboardButton("Sí, continuar ✅")]],
                    one_time_keyboard=True, selective=True
                )
            )
            return


        # REQ_PHONE ────────────────────────────────────
        if step == SessionSteps.REQ_PHONE:
            phone_clean = re.sub(r'\D', '', text)   # deja solo dígitos
            if not phone_clean or not (7 <= len(phone_clean) <= 15):
                await update.message.reply_text(
                    "Por favor escribe un número de teléfono válido (7–15 dígitos).",
                    reply_markup=ForceReply(selective=True),
                )
                return
            logger.info(f"[{telegram_id}] Teléfono recibido: {phone_clean}")
            self.__update_session(telegram_id, SessionSteps.REQ_AGE, {"telefono": phone_clean})
            await update.message.reply_text(
                "🎂 ¡Genial! Ahora escribe la <b>edad</b> de la persona que necesita los medicamentos.",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return        

        # ── REQ_AGE ───
        if step == SessionSteps.REQ_AGE:
            if not text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe una edad válida (número entero).",
                    reply_markup=ForceReply(selective=True)
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

        # ── REQ_ADDRESS ───────────────────────────────────────────────────────
        if step == SessionSteps.REQ_ADDRESS:
            if not text:
                await update.message.reply_text(
                    "Por favor escribe una dirección válida.", reply_markup=ForceReply(selective=True)
                )
                return
            logger.info(f"[{telegram_id}] Dirección recibida: {text}")
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
                    [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar solicitudes")]],
                    one_time_keyboard=True, selective=True,
                ),
                parse_mode="HTML",
            )
            return

        # ── KNOWN_USER ────────────────────────────────────────────────────────
        if step == SessionSteps.KNOWN_USER:
            text_lower = text.lower()
            if "solicitar" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_MEDICATIONS, {})
                await update.message.reply_text(
                    "💊 ¿Cómo deseas solicitar los medicamentos?\n\n"
                    "Puedes describirlos uno por uno o subir una foto/PDF de la receta médica.",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("📝 Describir medicamentos"), KeyboardButton("📷 Subir receta médica")]],
                        one_time_keyboard=True, selective=True,
                    ),
                    parse_mode="HTML"
                )
                return
            if "consultar" in text_lower:
                info = self.get_request_info(session)
                await update.message.reply_html(info)
                self.__end_session(telegram_id, "Consulta completada")

                return
            if text_lower.startswith(("sí", "si")) or "correcto" in text_lower:
                await update.message.reply_text(
                    "Perfecto. ¿Qué deseas hacer ahora?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar solicitudes")]],
                        one_time_keyboard=True, selective=True
                    )
                )
                return
            if text_lower.startswith("no") or "corregir" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_AGE, {})
                await update.message.reply_text(
                    "Entendido. Vamos a actualizar tu información. 🔄\n\n"
                    "🎂 Por favor escribe la <b>edad</b> de la persona que necesita los medicamentos.",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return
            await update.message.reply_text(
                "No entendí tu respuesta. Selecciona una opción del menú.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar solicitudes")]],
                    one_time_keyboard=True, selective=True
                )
            )
            return

        # ── REQ_MEDICATIONS ───────────────────────────────────────────────────
        if step == SessionSteps.REQ_MEDICATIONS:
            text_clean = "".join(c for c in text.lower() if c.isalnum() or c.isspace())
            if "describir" in text_clean or "manual" in text_clean:
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, {})
                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
                return
            if "subir" in text_clean or "receta" in text_clean or "foto" in text_clean:
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO, {
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
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("📝 Describir medicamentos"), KeyboardButton("📷 Subir receta médica")]],
                    one_time_keyboard=True, selective=True
                )
            )
            return

        # ── REQ_MED_COUNT ─────────────────────────────────────────────────────
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
            self.__update_session(telegram_id, SessionSteps.REQ_MED_DESCRIPTION, {
                "medication_count": count,
                "pending_medications": [],
            })
            await update.message.reply_text(
                "📝 Ahora vamos a solicitar los medicamentos uno por uno.\n\n"
                "💊 Por cada medicamento te pediremos:\n"
                "1️⃣ Primera letra del nombre\n"
                "2️⃣ Selección del medicamento\n\n"
                "Cuando estés listo, presiona 'Continuar'.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Continuar ▶️"), KeyboardButton("Cancelar ❌")]],
                    one_time_keyboard=True, selective=True,
                )
            )
            return

        # ── REQ_MED_DESCRIPTION ───────────────────────────────────────────────
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
                    one_time_keyboard=True, selective=True
                )
            )
            return

        # ── REQ_MED_FIRST_LETTER ──────────────────────────────────────────────
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

        # ── REQ_MED_LIST_CHOSEN ───────────────────────────────────────────────
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
            medicamento_exists = stock_models.Medicamento.objects.filter(
                id=selected_id,
                nombre_comercial__istartswith=first_letter
            ).exists()
            if not medicamento_exists:
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
                self.__update_session(telegram_id, SessionSteps.REQ_MED_FIRST_LETTER, {})
                await update.message.reply_text(
                    f"✅ Medicamento agregado.\n\n"
                    f"🔤 Ahora escribe la primera letra del siguiente medicamento (quedan {remaining}).",
                    reply_markup=ForceReply(selective=True)
                )
            else:
                self.__update_session(telegram_id, SessionSteps.REQ_MORE_PHOTOS, {})
                await update.message.reply_text(
                    "✅ ¡Perfecto! Ya hemos registrado todos los medicamentos.\n\n"
                    "📸 Ahora, por favor <b>sube una foto o PDF de la receta médica</b> para completar tu solicitud.\n\n"
                    "🩺💊 Este paso es <b>obligatorio</b>. La solicitud se guardará al recibirla.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML",
                )
            return

        # ── REQ_PHOTO_VALIDATION ──────────────────────────────────────────────
        if step == SessionSteps.REQ_PHOTO_VALIDATION:
            text_lower = text.lower()
            if "foto" in text_lower or "intentar" in text_lower or "otra" in text_lower:
                self.__update_session(telegram_id, SessionSteps.REQ_PHOTO, session["session_data"])
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
                self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, {})
                await update.message.reply_text(
                    "📝 Entendido. Vamos a describir los medicamentos manualmente.\n\n"
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n"
                    f"Recuerda que puedes solicitar hasta {self.MAX_MEDICATIONS} medicamentos.",
                    reply_markup=ForceReply(selective=True)
                )
                return
            await update.message.reply_text(
                "Por favor selecciona una opción válida.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("📷 Intentar con otra foto"),
                      KeyboardButton("📝 Describir medicamentos manualmente")]],
                    one_time_keyboard=True, selective=True
                )
            )
            return

        # ── REQ_PHOTO ─────────────────────────────────────────────────────────
        if step == SessionSteps.REQ_PHOTO:
            if update.message.document or update.message.photo:
                await self.process_multiple_files_with_validation(update, telegram_id, session)
                return
            elif text:
                text_lower = text.lower()
                if "describir" in text_lower or "manual" in text_lower:
                    self.__update_session(telegram_id, SessionSteps.REQ_MED_COUNT, {})
                    await update.message.reply_text(
                        "📝 Entendido. Vamos a describir los medicamentos manualmente.\n\n"
                        "🔢 ¿Cuántos medicamentos vas a solicitar?",
                        reply_markup=ForceReply(selective=True)
                    )
                    return
                await update.message.reply_text(
                    "📄 Por favor sube una foto o PDF de la fórmula médica.\n\n"
                    "⚠️ Recuerda enviarlo como <b>Archivo</b> (📎 adjunto).",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return

        # ── REQ_MORE_PHOTOS ───────────────────────────────────────────────────
        if step == SessionSteps.REQ_MORE_PHOTOS:
            if update.message.document or update.message.photo:
                file_path = await self.download_file_only(update)
                if not file_path:
                    await update.message.reply_text(
                        "❌ Error al recibir el archivo. Intenta nuevamente.",
                        reply_markup=ForceReply(selective=True)
                    )
                    return

                solicitud_obj = self._commit_full_request(telegram_id, session)
                if not solicitud_obj:
                    await update.message.reply_text(
                        "❌ Error al guardar la solicitud. Intenta más tarde.",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    self.__end_session(telegram_id, "Error en commit de solicitud (flujo manual)")
                    return

                try:
                    photo_path = Path(file_path)
                    with photo_path.open('rb') as pf:
                        formula_obj = stock_models.Formula.objects.create(
                            solicitud=solicitud_obj,
                            archivo_formula=django_files.File(pf, name=photo_path.name),
                        )
                        texto_extraido = OCRProcessor.extract_text_from_file(file_path)
                        if texto_extraido:
                            formula_obj.texto_ocr = texto_extraido
                            formula_obj.save(update_fields=["texto_ocr"])
                            logger.info(f"[{telegram_id}] OCR interno guardado ({len(texto_extraido)} chars)")
                except Exception as e:
                    logger.warning(f"[{telegram_id}] Error guardando archivo en flujo manual: {e}")

                self.__end_session(telegram_id, "Flujo manual completado")
                await update.message.reply_text(
                    "✅ ¡Gracias! Hemos recibido todos tus archivos y tu solicitud fue registrada con el número <b>#{solicitud_obj.id}</b>.\n. "
                    "Te notificaremos cuando esté lista.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            elif text:
                await update.message.reply_text(
                    "📄 Por favor sube la foto o PDF de la receta médica.\n\n"
                    "⚠️ Recuerda enviarlo como <b>Archivo</b> (📎 adjunto).",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return

        # ── PASO INESPERADO ───────────────────────────────────────────────────
        logger.error(f"[{telegram_id}] Paso inesperado: {step}")
        self.__end_session(telegram_id, f"Paso inesperado: {step}")
        await update.message.reply_text(
            "❌ Ocurrió un error con la sesión. Por favor inicia de nuevo con /iniciar o Hola.",
            reply_markup=ReplyKeyboardRemove(),
        )

    async def handle_plain_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if not msg or not msg.text:
            return
        text = msg.text.strip()
        text_lower = text.lower()
        telegram_id = update.effective_user.id

        if re.search(r'\b(salir|cerrar|finalizar)\b', text_lower, re.IGNORECASE):
            await self.end_session_command(update, context)
            return

        session = self.__find_active_session(telegram_id)
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

    def run(self) -> None:
        self.__application.add_handler(CommandHandler("iniciar", self.wellcome_user))
        self.__application.add_handler(CommandHandler("salir", self.end_session_command))

        fin_pattern = re.compile(r'\b(salir|cerrar|finalizar)\b', flags=re.IGNORECASE)
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
        self.__application.add_handler(
            MessageHandler(
                filters.TEXT | filters.Document.ALL | filters.PHOTO,
                self.request_session_step
            )
        )
        logger.info("🤖 Bot iniciado: seguridad por ownership, revinculación por OCR, commit diferido")
        self.__application.run_polling(allowed_updates=Update.ALL_TYPES)