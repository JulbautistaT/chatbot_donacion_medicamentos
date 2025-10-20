import logging
import os
from django.conf import settings
from django.core import files as django_files
from django.db.models import Count
from pathlib import Path
from stock import models as stock_models
from telegram import ForceReply, Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from datetime import datetime

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)



class BotController:
    
    def get_or_create_session(self, telegram_id):
        """GET OR CREATE session for the user by telegram_id only."""
        return self.__get_or_create_session(telegram_id)
    
    STEP_NEW_USER = "NEW_USER"
    STEP_REQ_DOCUMENT = "REQUEST_DOCUMENT"
    STEP_REQ_NAME = "REQUEST_NAME"
    STEP_REQ_ADDRESS = "REQUEST_ADDRESS"
    STEP_REQ_AGE = "REQUEST_AGE"
    STEP_KNOWN_USER = "KNOWN_USER"
    STEP_REQ_MEDICATIONS = "REQUEST_MEDICATIONS"
    STEP_REQ_MED_DESCRIPTION = "REQUEST_MED_DESCRIPTION"
    STEP_REQ_MED_FIST_LETTER = "REQUEST_MED_FIRST_LETTER"
    STEP_REQ_MED_LIST_CHOSEN = "STEP_REQ_MED_LIST_CHOSEN"
    STEP_REQ_MED_QUANTITY = "REQUEST_MED_QUANTITY"
    STEP_REQ_MED_COUNT = "REQUEST_MED_COUNT"
    STEP_REQ_PHOTO = "REQUEST_PHOTO"
    STEP_REQ_INFO_REQUESTS = "REQUEST_INFO"
    STEP_END = "END"



    def __init__(self,):
        self.__application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        self.__sessions = []
        
    def __get_or_create_session(self, telegram_id, documento=None):
        session = next((s for s in self.__sessions if s["telegram_id"] == telegram_id and s["is_active"]), None)
        if not session:
            session = {
                "telegram_id": telegram_id,
                "documento": documento,  # aquí guardamos el doc si lo pasan
                "session_data": {
                    "documento": documento,
                    "nombre": None,
                    "direccion_beneficiario": None,
                    "edad": None,
                    "medication_count": 0,
                },
                "step": 0,
                "is_active": True,
                "is_completed": False,
                "is_cancelled": False,
                "is_error": False,
                "error_message": None,
                "last_activity": datetime.now(),
            }
            self.__sessions.append(session)
        return session


    def __find_active_session_for_telegram(self, telegram_id):
        """Devuelve la sesión activa de un telegram_id (si existe)."""
        return next(
            (s for s in self.__sessions 
            if s["telegram_id"] == telegram_id and s["is_active"]), 
            None
        )


    def __update_last_activity(self, telegram_id):
        """Update last activity timestamp for the user session."""
        session = self.__find_active_session_for_telegram(telegram_id)
        if session:
            session["last_activity"] = datetime.now()
        else:
            logger.warning(f"No session found to update last_activity for telegram={telegram_id}")

    def __is_session_expired(self, telegram_id, hours=12):
        """Check if the session has expired due to inactivity"""
        session = self.__find_active_session_for_telegram(telegram_id)
        if session and session.get("last_activity"):
            elapsed = datetime.now() - session["last_activity"]
            elapsed_seconds = elapsed.total_seconds()
            
            logger.info(f"[{telegram_id}] Verificando expiración: {elapsed_seconds:.2f} segundos transcurridos (límite: {hours * 3600:.2f})")
            
            if elapsed_seconds > hours * 3600:
                logger.info(f"[{telegram_id}] ⏰ Sesión EXPIRADA - cerrando...")
                self.__end_session(telegram_id, error_message="Sesión cerrada por inactividad")
                return True
        return False
    

    def get_user(self, telegram_id):
        """Retrieve the user from the database by Telegram ID."""
        try:
            solicitante_obj = stock_models.Solicitante.objects.get(telegram_id=str(telegram_id))
            return solicitante_obj
        except stock_models.Solicitante.DoesNotExist:
            return None
        
    def get_user_by_document(self, document):
        """Retrieve the user from the database by document number."""
        try:
            solicitante_obj = stock_models.Solicitante.objects.get(documento=document)
            return solicitante_obj
        except stock_models.Solicitante.DoesNotExist:
            return None


    def create_user(self, telegram_id, session_data):
        """Create a new user in the database."""
        solicitante_obj = stock_models.Solicitante(
            nombre=session_data.get("nombre"),
            documento=session_data.get("documento"),
            telegram_id=str(telegram_id),
            telefono=None,  # Optional, can be set later
            direccion_beneficiario=session_data.get("direccion_beneficiario"),
            edad=session_data.get("edad"),
        )
        solicitante_obj.save()
        return solicitante_obj


    def create_request(self, telegram_id, medication_count):
        """Create a new Solicitud in the DB for the document linked to the current session."""
        session = self.__find_active_session_for_telegram(telegram_id)
        if not session:
            logger.error(f"No session found for telegram {telegram_id} when creating request.")
            return None
        documento = session.get("documento")
        if not documento:
            logger.error("Cannot create request: documento not set in session.")
            return None

        solicitante_obj = self.get_user_by_document(documento)
        if not solicitante_obj:
            logger.error(f"User with documento {documento} not found in DB when creating request.")
            return None

        solicitud_obj = stock_models.Solicitud(
            solicitante=solicitante_obj,
            solicitud_propia=True,
            estado=stock_models.Solicitud.Estado.PENDIENTE,
        )
        solicitud_obj.save()
        return solicitud_obj
    

    def get_available_medications(self, first_letter):
        """Get a list of available medications starting with the given first letter."""
        medicamento_donado_query = stock_models.MedicamentoDonado.objects.filter(
            medicamento__nombre_comercial__istartswith=first_letter,
            estado=stock_models.MedicamentoDonado.Estado.DISPONIBLE
        )

        if not medicamento_donado_query.exists():
            logger.warning(f"No medications found starting with '{first_letter}'.")
            return None
        
        medication_list = [
            f"{medicamento_donado.id}. {medicamento_donado.medicamento.nombre_comercial} - "
            f"{medicamento_donado.medicamento.concentracion}"
            for medicamento_donado in medicamento_donado_query
        ]
        medication_list_text = "\n".join(medication_list)

        logger.info(f"Available medications starting with '{first_letter}':\n"
                    f"{medication_list_text}")
        return medication_list_text if medication_list else None


    def create_detail_request(self, telegram_id, session):
        """Create a detail request for the selected medication."""
        selected_medication_id = session["session_data"].get("selected_medication_id")
        quantity = session["session_data"].get("quantity")

        if not selected_medication_id or not quantity:
            logger.error("Selected medication ID or quantity is missing in the session data.")
            return None

        medicamento_donado_obj = stock_models.MedicamentoDonado.objects.get(id=selected_medication_id)

        detalle_solicitud_obj = stock_models.DetalleSolicitud(
            solicitud=session["session_data"].get("solicitud_obj"),
            medicamento=medicamento_donado_obj.medicamento,
            cantidad_solicitada=quantity,
            cantidad_entregada=0,
        )
        detalle_solicitud_obj.save()
        logger.info(f"Detail request created for telegram {telegram_id} with medication ID {selected_medication_id} and quantity {quantity}.")
        return detalle_solicitud_obj



    def __update_session(self, telegram_id, step, session_data):
        session = self.__find_active_session_for_telegram(telegram_id)
        if not session:
            session = self.__get_or_create_session(telegram_id)
        session["step"] = step
        if session_data:
            if "session_data" not in session:
                session["session_data"] = {}
            session["session_data"].update(session_data)
            # Si el usuario ya ingresó el documento, lo asignamos
            if "documento" in session_data and session_data["documento"]:
                session["documento"] = session_data["documento"]
        
        return session

    def __end_session(self, telegram_id, documento=None, error_message=None):
        """Finaliza y elimina una sesión activa."""
        session = next(
            (s for s in self.__sessions 
            if s["telegram_id"] == telegram_id 
            and (documento is None or s["session_data"]["documento"] == documento)
            and s["is_active"]), 
            None
        )

        if session:
            session["is_active"] = False
            session["is_completed"] = False
            session["is_cancelled"] = True
            session["is_error"] = False
            session["error_message"] = None
            session["last_activity"] = None
            logger.info(f"[{telegram_id}] Sesión finalizada. Reason: {error_message or 'Usuario cerró sesión'}")


    def get_request_info(self, session, telegram_id) -> str:
        """Get information about the user's requests (uses documento associated to session)."""
        documento = session.get("documento") if session else None
        if not documento:
            return "No tienes solicitudes pendientes."

        solicitante_obj = self.get_user_by_document(documento)
        if not solicitante_obj:
            return "No tienes solicitudes pendientes."

        solicitud_query = stock_models.Solicitud.objects.filter(solicitante=solicitante_obj)
        if not solicitud_query.exists():
            return "No tienes solicitudes pendientes."

        
        # make the next message with the requests information
        # ----------------------
        # Tienes 4 solicitudes:
        # - 1 pendiente
        # - 1 rechazada
        # - 2 aceptadas
        # La ultima solicitud del 3 de Julio de 2025 está en estado Pendiente.
        # ----------------------
        estado_emojis = {
            stock_models.Solicitud.Estado.PENDIENTE: "⏳",
            stock_models.Solicitud.Estado.RECHAZADA: "❌",
            stock_models.Solicitud.Estado.ACEPTADA: "✅",
        }

        request_info = f"📋 Tienes <b>{solicitud_query.count()}</b> solicitudes:\n"
        solicitud_ant = solicitud_query.values('estado').annotate(count=Count('estado'))
        for solicitud in solicitud_ant:
            emoji = estado_emojis.get(solicitud['estado'], "")
            estado = solicitud['estado'].capitalize()
            request_info += f"- {emoji} <b>{solicitud['count']}</b> {estado}\n"

        solicitud_obj_last = solicitud_query.order_by('-fecha').first()
        if solicitud_obj_last:
            emoji = estado_emojis.get(solicitud_obj_last.estado, "")
            request_info += (
                f"\n🕓 La última solicitud del <b>{solicitud_obj_last.fecha.strftime('%d de %B de %Y')}</b> "
                f"está en estado {emoji} <b>{solicitud_obj_last.estado.capitalize()}</b>."
            )

        return request_info


    def save_photo_to_request(self, telegram_id, solicitud_obj, photo_path_tmp: str) -> stock_models.Formula:
        """Save the photo to the request."""
        if not solicitud_obj:
            logger.error(f"No request found for user {telegram_id}. Cannot save photo.")
            return stock_models.Formula.objects.none()

        # Create a Django File object from the photo path
        photo_path = Path(photo_path_tmp)
        with photo_path.open('rb') as photo_file:
            django_file = django_files.File(photo_file, name=photo_path.name)

            # Assuming you have a field in Solicitud to store the photo
            formula_obj = stock_models.Formula.objects.create(
                solicitud=solicitud_obj,
                archivo_formula=django_file,  # Assuming you have a FileField or ImageField for the photo
            )
            logger.info(f"Photo saved for request {solicitud_obj.id} by user {telegram_id}.")

        return formula_obj


    async def end_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando para que el usuario cierre manualmente su sesión (/salir)."""
        telegram_id = update.effective_user.id

        # Buscar la sesión activa para este telegram_id
        session = self.__find_active_session_for_telegram(telegram_id)
        documento = session.get("session_data", {}).get("documento") if session else None

        self.__end_session(telegram_id, documento, error_message="Sesión finalizada por el usuario con /salir")

        await update.message.reply_text(
            "✅ Tu sesión ha sido cerrada correctamente.\n"
            "Puedes iniciar una nueva con /iniciar."
        )


    async def request_session_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Controla el flujo paso a paso de la sesión del usuario."""
        telegram_id = update.effective_user.id
        message = update.message
        text = message.text.strip() if message.text else ""

        # Buscar sesión activa
        session = self.__find_active_session_for_telegram(telegram_id)
        if not session:
            await update.message.reply_text("⚠️ No tienes ninguna sesión activa. Usa /iniciar para comenzar.")
            return
        
        if session.get("last_activity"):
            elapsed = datetime.now() - session["last_activity"]
            logger.info(f"[{telegram_id}] DEBUG - last_activity: {session['last_activity']}, elapsed: {elapsed.total_seconds():.2f}s")
    
        
        if self.__is_session_expired(telegram_id, hours=12):
            await update.message.reply_text(
                "⏰ Tu sesión ha expirado por inactividad.\n" 
                "Por favor, inicia una nueva sesión con /iniciar."
                )
            return

        self.__update_last_activity(telegram_id)
        
        logger.info(f"[{telegram_id}] DEBUG - last_activity actualizado a: {session['last_activity']}")

        
        step = session.get("step")

        # -------------------------------
        # STEP: Política de datos
        # -------------------------------
        
        if step == self.STEP_NEW_USER:
            # Pedir documento siempre después de aceptación de política (o al iniciar)
            logger.info(f"[{telegram_id}] STEP_NEW_USER -> solicitando documento")
            session = self.__update_session(telegram_id, self.STEP_REQ_DOCUMENT, {"documento": None})
            
            await update.message.reply_text(
                "📝 Por favor, escribe el <b>número de documento</b> de la persona que necesita los medicamentos.\n\n"
                "Ejemplo: <code>123456789</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return

        # -------------- Documento --------------
        if step == self.STEP_REQ_DOCUMENT:
            document_number = text
            if not document_number:
                await update.message.reply_text(
                    "Por favor escribe un número de documento válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"[{telegram_id}] Documento recibido: {document_number}")


            solicitante_obj = self.get_user_by_document(document_number)
            if solicitante_obj:
                # Usuario existente: cargar datos y pedir confirmación
                session = self.__update_session(telegram_id, self.STEP_KNOWN_USER, {
                    "documento": solicitante_obj.documento,
                    "nombre": solicitante_obj.nombre,
                    "direccion_beneficiario": solicitante_obj.direccion_beneficiario,
                    "edad": solicitante_obj.edad,
                })
               
                first_name = solicitante_obj.nombre.split()[0] if solicitante_obj.nombre else "Usuario"
                await update.message.reply_html(
                    f"👋 ¡Hola {first_name}! He encontrado un registro con el documento {document_number}.\n"
                    "¿Los siguientes datos están correctos?. \n"
                    f"Edad: {solicitante_obj.edad}.\n"
                    f"Dirección: {solicitante_obj.direccion_beneficiario}.\n"
                    "Si todo está correcto, presiona <b>Sí, correcto ✅</b> para continuar.\n",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("Sí, correcto ✅"), KeyboardButton("No, corregir ✏️")]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
            else:
                # No existe: pedimos nombre (creación de nuevo usuario)
                session = self.__update_session(telegram_id, self.STEP_REQ_NAME, {"documento": document_number})
                await update.message.reply_text(
                    "🙋‍♂️ ¡Gracias! Ahora, por favor escribe el nombre completo de la persona que necesita los medicamentos. 📝 \n\n"
                    "Ejemplo: <code>Juan Pérez</code>",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
            return

       # Name
        if step == self.STEP_REQ_NAME:
            try:
                name = text
                if not name:
                    raise ValueError("El nombre no puede estar vacío.")
            except (ValueError, AttributeError):
                await update.message.reply_text(
                    "Por favor, escribe un nombre válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"[{telegram_id}] Nombre recibido: {name}")
            session = self.__update_session(telegram_id, self.STEP_REQ_AGE, {"nombre": name})
            await update.message.reply_text(
                "🎂  ¡Perfecto! Ahora, por favor escribe la <b>edad</b> de la persona que necesita los medicamentos. 👶🧓",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return

        #Age
        if step == self.STEP_REQ_AGE:
            age_text = text
            if not age_text.isdigit():
                await update.message.reply_text(
                    "Por favor escribe una edad válida (número entero).",
                    reply_markup=ForceReply(selective=True),
                )
                return
            age = int(age_text)
            logger.info(f"[{telegram_id}] Edad recibida: {age}")
            session = self.__update_session(telegram_id, self.STEP_REQ_ADDRESS, {"edad": age})
            await update.message.reply_text(
                "🏠 ¡Genial! Ahora, por favor escribe la dirección de la persona que necesita los medicamentos. 📍 \n\n"
                "Ejemplo: <code>Calle 123 #45-67, Barrio Centro</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            return

        # Address
        if step == self.STEP_REQ_ADDRESS:
            address = text
            if not address:
                await update.message.reply_text(
                    "Por favor esscribe una dirección válida.",
                    reply_markup=ForceReply(selective=True),
                )
                return
            logger.info(f"[{telegram_id}] Dirección recibida: {address}")

            # Actualizar sesión y crear/actualizar solicitante en BD
            session = self.__update_session(telegram_id, self.STEP_KNOWN_USER, {"direccion_beneficiario": address})
            documento = session["session_data"].get("documento")
            solicitante_obj = self.get_user_by_document(documento)
            if not solicitante_obj:
                # Crear usuario nuevo
                solicitante_obj = self.create_user(telegram_id, session["session_data"])
                logger.info(f"[{telegram_id}] Solicitante creado: {solicitante_obj.id}")
            else:
                # Actualizar campos modificados (except documento)
                changed = False
                for field in ("nombre", "direccion_beneficiario", "edad"):
                    val = session["session_data"].get(field)
                    if val is not None and getattr(solicitante_obj, field) != val:
                        setattr(solicitante_obj, field, val)
                        changed = True
                if changed:
                    solicitante_obj.save()
                    logger.info(f"[{telegram_id}] Solicitante {solicitante_obj.id} actualizado.")

            # Registro completado, mostrar menú principal
            await update.message.reply_text(
                f"✅ ¡Registro completado!\n\n"
                f"🙋‍♂️ <b>Nombre:</b> {solicitante_obj.nombre}\n"
                f"🆔 <b>Documento:</b> {solicitante_obj.documento}\n"
                f"🏠 <b>Dirección:</b> {solicitante_obj.direccion_beneficiario}\n"
                f"🎂 <b>Edad:</b> {solicitante_obj.edad}\n\n"
                "¿Qué deseas hacer ahora?\n"
                "Selecciona una opción:",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar el estado de una solicitud")]
                    ],
                    one_time_keyboard=True,
                    selective=True,
                ),
                parse_mode="HTML",

            )
            return

        # -------------- Usuario conocido (confirmación) --------------
        if step == self.STEP_KNOWN_USER:
            # Usar 'text' en lugar de 'user_response'
            text_lower = text.lower()
            
            if "solicitar" in text_lower:
                self.__update_session(telegram_id, self.STEP_REQ_MEDICATIONS, {})
                await update.message.reply_text(
                    "💊 ¿Quieres describir la lista de medicamentos o vas a subir una foto de la receta?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("Sí ✅"), KeyboardButton("No, subiré una foto de la receta médica 📷")]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
                return

            if "consultar" in text_lower:
                # show request info for the documento in session
                session = self.__find_active_session_for_telegram(telegram_id)
                info = self.get_request_info(session, telegram_id)
                await update.message.reply_html(info, reply_markup=ForceReply(selective=True))
                return

            # Confirm user data correctness
            if text_lower.startswith("sí") or text_lower.startswith("si") or "correcto" in text_lower:
                # data accepted: present same menu (in case confirm came from DB check)
                await update.message.reply_text(
                    "Perfecto. ¿Qué deseas hacer ahora?",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar el estado de una solicitud")]],
                        one_time_keyboard=True,
                        selective=True
                    )
                )
                return

            if text_lower.startswith("no") or "corregir" in text_lower:
                self.__update_session(telegram_id, self.STEP_REQ_AGE, {})
                await update.message.reply_text(
                    "Entendido. Vamos a actualizar tu información. 🔄\n\n"
                    "🎂 Por favor escribe la <b>edad</b> de la persona que necesita los medicamentos. 👶🧓",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML"
                )
                return


            await update.message.reply_text(
                "No entendí tu respuesta. Selecciona una opción del menú.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar el estado de una solicitud")]],
                    one_time_keyboard=True,
                    resize_keyboard=True,
                    selective=True
                )
            )
            return
        # -------------- Solicitud de medicamentos --------------
        if step == self.STEP_REQ_MEDICATIONS:
            text_lower = text.lower()
            
            if "sí" in text_lower or text_lower.startswith("si"):
                # pedir cuántos medicamentos
                session = self.__update_session(telegram_id, self.STEP_REQ_MED_COUNT, {})
                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar? (máx. 10)",
                    reply_markup=ForceReply(selective=True)
                )
                return

            if "foto" in text_lower or "subir" in text_lower:
                # pedir foto de la receta (skip descripción)
                session = self.__update_session(telegram_id, self.STEP_REQ_PHOTO, {})
                await update.message.reply_text(
                    "📄 Por favor, sube el documento en PDF o una imagen de la fórmula médica.",
                    reply_markup=ForceReply(selective=True)
                )
                return

            # no entendido
            await update.message.reply_text(
                "No entendí tu respuesta. ¿Deseas describir los medicamentos o subir una foto?",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Sí ✅"), KeyboardButton("No, subiré una foto de la receta médica 📷")]],
                    one_time_keyboard=True,
                    resize_keyboard=True,
                    selective=True
                )
            )
            return
        
        
        # -------------- Cantidad de medicamentos --------------
        if step == self.STEP_REQ_MED_COUNT:
            count_text = text
            if not count_text.isdigit():
                await update.message.reply_text("Por favor escribe un número entero válido.", reply_markup=ForceReply(selective=True))
                return
            count = int(count_text)
            max_count = 10
            if count <= 0 or count > max_count:
                await update.message.reply_text(f"El número debe estar entre 1 y {max_count}.", reply_markup=ForceReply(selective=True))
                return

            # Crear solicitud en BD
            solicitud_obj = self.create_request(telegram_id, count)
            if not solicitud_obj:
                await update.message.reply_text("No se pudo crear la solicitud. Intenta más tarde.", reply_markup=ForceReply(selective=True))
                return

            session = self.__update_session(telegram_id, self.STEP_REQ_MED_DESCRIPTION, {
                "medication_count": count,
                "solicitud_obj": solicitud_obj,
            })

            await update.message.reply_text(
                "📝 Ahora vamos a solicitar los medicamentos uno por uno. Cuando estés listo presiona 'Continuar'.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Continuar ▶️"), KeyboardButton("Cancelar ❌")]],
                    one_time_keyboard=True,
                    selective=True
                )
            )
            return

        # -------------- Empezar a describir medicamentos --------------
        if step == self.STEP_REQ_MED_DESCRIPTION:
            text_lower = text.lower()
            
            if "continuar" in text_lower:
                session = self.__update_session(telegram_id, self.STEP_REQ_MED_FIST_LETTER, {})
                await update.message.reply_text(
                    "🔤 Escribe la primera letra del medicamento 1 que necesitas (ej: 'A' para Acetaminofén).",
                    reply_markup=ForceReply(selective=True)
                )
                return

            if "cancel" in text_lower or "cancelar" in text_lower:
                # cancelar solicitud: marcar o eliminar solicitud_obj
                solicitud_obj = session["session_data"].get("solicitud_obj")
                if solicitud_obj:
                    try:
                        solicitud_obj.estado = stock_models.Solicitud.Estado.RECHAZADA if hasattr(stock_models.Solicitud.Estado, 'RECHAZADA') else stock_models.Solicitud.Estado.PENDIENTE
                        solicitud_obj.observaciones = f"Solicitud cancelada por el usuario (telegram {telegram_id})."
                        solicitud_obj.save()
                    except Exception as e:
                        logger.error(f"Error al marcar solicitud como cancelada: {e}")
                # cerrar sesión
                self.__end_session(telegram_id, session.get("documento"), "Session cancelled by user")
                await update.message.reply_text("La sesión ha sido cancelada. Puedes iniciar una nueva sesión con /iniciar.")
                return

            await update.message.reply_text("Por favor presiona 'Continuar' cuando estés listo.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Continuar ▶️"), KeyboardButton("Cancelar ❌")]], one_time_keyboard=True, resize_keyboard=True, selective=True))
            return


        # -------------- Primera letra --------------
        if step == self.STEP_REQ_MED_FIST_LETTER:
            first_letter = text.upper()
            if not first_letter.isalpha() or len(first_letter) != 1:
                await update.message.reply_text("Por favor escribe una única letra válida.", reply_markup=ForceReply(selective=True))
                return

            meds_text = self.get_available_medications(first_letter)
            if not meds_text:
                await update.message.reply_text(f"No se encontraron medicamentos que comiencen con '{first_letter}'. Prueba otra letra.", reply_markup=ForceReply(selective=True))
                return

            session = self.__update_session(telegram_id, self.STEP_REQ_MED_LIST_CHOSEN, {"first_letter": first_letter})
            await update.message.reply_text(
                f"💊 Medicamentos con '{first_letter}':\n{meds_text}\n\nEscribe el ID del medicamento que deseas solicitar.",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML"
            )
            return

        # -------------- Selección de medicamento por ID --------------
        if step == self.STEP_REQ_MED_LIST_CHOSEN:
            try:
                selected_id = int(text)
            except (ValueError, TypeError):
                await update.message.reply_text("Por favor escribe un ID válido (número).", reply_markup=ForceReply(selective=True))
                return

            first_letter = session["session_data"].get("first_letter")
            medicamento_donado_qs = stock_models.MedicamentoDonado.objects.filter(
                id=selected_id,
                estado=stock_models.MedicamentoDonado.Estado.DISPONIBLE,
                medicamento__nombre_comercial__istartswith=first_letter
            )
            if not medicamento_donado_qs.exists():
                await update.message.reply_text("ID de medicamento no válido o no disponible. Intenta otro ID.", reply_markup=ForceReply(selective=True))
                return

            session = self.__update_session(telegram_id, self.STEP_REQ_MED_QUANTITY, {"selected_medication_id": selected_id})
            await update.message.reply_text("¿Cuántas unidades de este medicamento necesitas?", reply_markup=ForceReply(selective=True))
            return

        # -------------- Cantidad para medicamento seleccionado --------------
        if step == self.STEP_REQ_MED_QUANTITY:
            quantity_text = text
            if not quantity_text.isdigit():
                await update.message.reply_text("Por favor escribe una cantidad válida (número entero).", reply_markup=ForceReply(selective=True))
                return
            quantity = int(quantity_text)
            if quantity <= 0:
                await update.message.reply_text("La cantidad debe ser mayor que cero.", reply_markup=ForceReply(selective=True))
                return

            selected_med_id = session["session_data"].get("selected_medication_id")
            # actualizar sesión y crear detalle
            session = self.__update_session(telegram_id, self.STEP_REQ_PHOTO, {"selected_medication_id": selected_med_id, "quantity": quantity})
            detalle = self.create_detail_request(telegram_id, session)
            if detalle:
                # disminuir contador
                session["session_data"]["medication_count"] = session["session_data"].get("medication_count", 0) - 1
                remaining = session["session_data"].get("medication_count", 0)
                if remaining > 0:
                    # pedir siguiente medicamento
                    self.__update_session(telegram_id, self.STEP_REQ_MED_FIST_LETTER, {})
                    await update.message.reply_text(
                        f"🔤 Ahora escribe la primera letra del siguiente medicamento (quedan {remaining}).",
                        reply_markup=ForceReply(selective=True)
                    )
                    return
                else:
                    # pedir foto final
                    await update.message.reply_text(
                        "✅ Ya registramos todos los medicamentos. Por favor sube la foto o PDF de la receta para completar.",
                        reply_markup=ForceReply(selective=True)
                    )
                    return
            else:
                await update.message.reply_text("Hubo un error al crear el detalle. Intenta de nuevo más tarde.", reply_markup=ForceReply(selective=True))
                return

        # -------------- Subida de foto (final) --------------
        if step == self.STEP_REQ_PHOTO or step == self.STEP_END:
            solicitud_obj = session["session_data"].get("solicitud_obj")
            photo_path_tmp = None

            # Document
            if update.message.document:
                doc = update.message.document
                photo_file = await doc.get_file()
                ext = os.path.splitext(doc.file_name)[1] or ".jpg"
                photo_dir = f"{settings.BASE_DIR}/photos"
                os.makedirs(photo_dir, exist_ok=True)
                photo_path_tmp = f"{photo_dir}/{doc.file_unique_id}{ext}"
                await photo_file.download_to_drive(photo_path_tmp)

            # Photo
            elif update.message.photo:
                photo = update.message.photo[-1]
                photo_file = await photo.get_file()
                photo_dir = f"{settings.BASE_DIR}/photos"
                os.makedirs(photo_dir, exist_ok=True)
                photo_path_tmp = f"{photo_dir}/{photo.file_unique_id}.jpg"
                await photo_file.download_to_drive(photo_path_tmp)

            else:
                # No file received
                await update.message.reply_text("Por favor sube una foto o PDF de la receta médica.", reply_markup=ForceReply(selective=True))
                return

            # Guardar archivo asociado a la solicitud (si existe)
            if solicitud_obj and photo_path_tmp:
                try:
                    self.save_photo_to_request(telegram_id, solicitud_obj, photo_path_tmp)
                except Exception as e:
                    logger.error(f"Error guardando foto para solicitud: {e}")

            # Finalizar sesión exitosamente
            documento = session.get("documento")
            self.__end_session(telegram_id, documento, "Flujo completado")
            await update.message.reply_text(
                "✅ ¡Gracias! Hemos recibido tu foto/PDF y tu solicitud fue registrada. Te notificaremos cuando esté lista."
            )
            return

        if step == self.STEP_REQ_INFO_REQUESTS:
            # mostrar info y luego cerrar o volver a menu
            info = self.get_request_info(session, telegram_id)
            await update.message.reply_html(info, reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Volver al menú")]], one_time_keyboard=True, resize_keyboard=True, selective=True))
            # dejar en KNOWN_USER para siguientes pasos
            self.__update_session(telegram_id, self.STEP_KNOWN_USER, {})
            return

        # -------------- Si llegamos aquí: paso inesperado --------------
        logger.error(f"[{telegram_id}] Unexpected step in session: {step}")
        documento = session.get("documento")
        self.__end_session(telegram_id, documento, f"Unexpected step: {step}")
        await update.message.reply_text(
            "Ocurrió un error con la sesión. Por favor inicia de nuevo con /iniciar.",
            reply_markup=ForceReply(selective=True),
        )

    async def wellcome_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Muestra mensaje de bienvenida cuando se usa /iniciar."""
        logger.info("Welcome user command received.")

        telegram_id = update.effective_user.id

        # Verificar si ya hay una sesión activa para este telegram_id
        session = self.__find_active_session_for_telegram(telegram_id)
        if session:
            await update.message.reply_text(
                "👋 Ya tienes una sesión activa. Por favor, completa la sesión actual o usa /salir para cerrarla."
            )
            return

        # Si no hay sesión, siempre empezamos con la política de datos
        session = self.__get_or_create_session(telegram_id, documento=None)
        session["step"] = self.STEP_NEW_USER  # Step 0 = política de datos
        session["is_active"] = True
        session["is_completed"] = False
        session["is_cancelled"] = False
        session["last_activity"] = datetime.now()
        session["session_data"] = {
            "documento": None,
            "nombre": None,
            "direccion_beneficiario": None,
            "edad": None,
            "medication_count": 0,
        }

        logger.info(f"New session started for telegram_id={telegram_id}")
    
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


    def run(self):
        """Start the bot."""
        # Starts the bot and registers handlers
        self.__application.add_handler(CommandHandler("iniciar", self.wellcome_user))
        self.__application.add_handler(CommandHandler("salir", self.end_session_command))

        # Register the message handler for the request session step
        self.__application.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL | filters.PHOTO, self.request_session_step))

        # Start the Bot
        self.__application.run_polling(allowed_updates=Update.ALL_TYPES)