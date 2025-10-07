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
    def get_or_create_session(self, user_id):
        """Obtener o crear la sesión del usuario (público)."""
        return self.__get_or_create_session(user_id)
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
        
    def __get_or_create_session(self, user_id):
        session = next((s for s in self.__sessions if s["user_id"] == user_id), None)
        if not session:
            session = {
                "user_id": user_id,
                "session_data": {
                    "documento": None,
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
                "last_activity": None,
            }
            self.__sessions.append(session)
        return session

        
    def __update_last_activity(self, user_id):
        """Update last activity timestamp for the user session."""
        session = self.get_or_create_session(user_id)
        session["last_activity"] = datetime.now()

    def __is_session_expired(self, user_id, hours=12):
        """Check if the session has expired due to inactivity (default 5 hours)."""
        session = self.get_or_create_session(user_id)
        if session and session.get("last_activity"):
            elapsed = datetime.now() - session["last_activity"]
            if elapsed.total_seconds() > hours * 3600:
                # Expirada → cerramos y borramos sesión
                self.__end_session(user_id, "Sesión cerrada por inactividad")
                return True
        return False
    

    def get_user(self, user_id):
        """Retrieve the user from the database by Telegram ID."""
        try:
            solicitante_obj = stock_models.Solicitante.objects.get(telegram_id=str(user_id))
            return solicitante_obj
        except stock_models.Solicitante.DoesNotExist:
            return None


    def create_user(self, user_id, session_data):
        """Create a new user in the database."""
        solicitante_obj = stock_models.Solicitante(
            nombre=session_data.get("nombre"),
            documento=session_data.get("documento"),
            telegram_id=str(user_id),
            telefono=None,  # Optional, can be set later
            direccion_beneficiario=session_data.get("direccion_beneficiario"),
            edad=session_data.get("edad"),
        )
        solicitante_obj.save()
        return solicitante_obj


    def create_request(self, user_id, medication_count):
        """Create a new request in the database."""
        solicitante_obj = self.get_user(user_id)
        if not solicitante_obj:
            logger.error(f"User with ID {user_id} not found in the database.")
            return None

        solicitud_obj = stock_models.Solicitud(
            solicitante=solicitante_obj,
            solicitud_propia=True,  # Assuming this is a boolean field
            estado=stock_models.Solicitud.Estado.PENDIENTE,  # Assuming PENDIENTE is a valid state
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


    def create_detail_request(self, user_id, session):
        """Create a detail request for the selected medication."""
        # 1. Get the selected medication ID and quantity from the session
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
            cantidad_entregada=0,  # Assuming initial quantity delivered is 0
        )
        detalle_solicitud_obj.save()

        logger.info(f"Detail request created for user {user_id} with medication ID {selected_medication_id} and quantity {quantity}.")

        return detalle_solicitud_obj


    def __update_session(self, user_id, step, session_data):
        """Update the session for the user."""
        session = self.get_or_create_session(user_id)
        session["step"] = step
        session["session_data"].update(session_data)
        session["last_activity"] = datetime.now()
        return session

    def __end_session(self, user_id, error_message=None):
        """End and remove the session for the user."""
        session_index = next((i for i, s in enumerate(self.__sessions) if s["user_id"] == user_id), None)
        
        if session_index is not None:
            session = self.__sessions.pop(session_index)  # Elimina la sesión de la lista
            
            # Si la sesión ya tenía una solicitud en la BD
            solicitud_obj = session['session_data'].get('solicitud_obj')    
            if solicitud_obj:
                try:
                    solicitud_obj.delete()
                    logger.info(f"Solicitud asociada al usuario {user_id} fue eliminada.")
                except Exception as e:
                    logger.error(f"Error al eliminar la solicitud asociada al usuario {user_id}: {e}")
                
            logger.info(
                f"Session for user {user_id} removed. "
                f"Error: {error_message if error_message else 'No error'}"
            )
            
        else:
            logger.error(f"No active session found for user {user_id}. Cannot end session.")


    def get_request_info(self, session, user_id) -> str:
        """Get information about the user's requests."""
        solicitante_obj = self.get_user(user_id)
        if not solicitante_obj:
            logger.error(f"User with ID {user_id} not found in the database.")
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


    def save_photo_to_request(self, user_id, solicitud_obj, photo_path_tmp: str) -> stock_models.Formula:
        """Save the photo to the request."""
        if not solicitud_obj:
            logger.error(f"No request found for user {user_id}. Cannot save photo.")
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
            logger.info(f"Photo saved for request {solicitud_obj.id} by user {user_id}.")

        return formula_obj


    async def end_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Close session
        user_id = update.effective_user.id
        self.__end_session(user_id, "Sesión finalizada por el usuario con /salir")

        await update.message.reply_text(
            "✅ Tu sesión ha sido cerrada correctamente.\n"
            "Puedes iniciar una nueva con /iniciar.",            
        )
        
        
    async def request_session_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        
        user_id = update.effective_user.id
        session = next((s for s in self.__sessions if s["user_id"] == user_id), None)
            
        if session and self.__is_session_expired(user_id):
            self.__end_session(user_id, "Sesión cerrada por inactividad")
            await update.message.reply_text(
                "⏳ Tu sesión se cerró por inactividad."
                "Usa /iniciar para comenzar de nuevo.",
            )
            return  
        
        self.__update_last_activity(user_id)          
            

        if session and session["step"] == self.STEP_NEW_USER:

            # Request the document number from the user
            logger.info("Requesting document number from the user.")

            self.__update_session(user_id, self.STEP_REQ_DOCUMENT, {
                "documento": None,
                "nombre": None,
                "direccion_beneficiario": None,
                "edad": None,
            })

            await update.message.reply_text(
                "📝 Por favor, escribe el <b>número de documento</b> de la persona que necesita los medicamentos. "
                "Este dato es necesario para continuar con la solicitud. 🆔\n\n"
                "Ejemplo: <code>123456789</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )

        elif session and session["step"] == self.STEP_REQ_DOCUMENT:
            document_number = update.message.text.strip()
            logger.info(f"Received document number: {document_number}")

            # Update the session with the document number
            self.__update_session(user_id, self.STEP_REQ_NAME, {"documento": document_number})

            await update.message.reply_text(
                "🙋‍♂️ ¡Gracias! Ahora, por favor escribe el <b>nombre completo</b> de la persona que necesita los medicamentos. 📝\n\n"
                "Ejemplo: <code>Juan Pérez</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
        
        elif session and session["step"] == self.STEP_REQ_NAME:
            try:
                name = update.message.text.strip()
                if not name:
                    raise ValueError("El nombre no puede estar vacío.")
            except (ValueError, AttributeError):
                logger.error("Invalid name received.")
                await update.message.reply_text(
                    "Por favor, escribe un nombre válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return
            

            logger.info(f"Received name: {name}")

            # Update the session with the name
            self.__update_session(user_id, self.STEP_REQ_AGE, {"nombre": name})

            await update.message.reply_text(
                "🎂 ¡Perfecto! Ahora, por favor escribe la <b>edad</b> de la persona que necesita los medicamentos. 👶🧓\n\n"
                "Ejemplo: <code>45</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
        
        elif session and session["step"] == self.STEP_REQ_AGE:
            try:
                age_text = update.message.text.strip()
                if not age_text.isdigit():
                    raise ValueError("La edad debe ser un número entero.")
            except AttributeError:
                logger.error("No age text received.")
                await update.message.reply_text(
                    "Por favor, escribe una edad válida (número entero).",
                    reply_markup=ForceReply(selective=True),
                )
                return


            age = int(age_text)
            logger.info(f"Received age: {age}")

            # Update the session with the age
            self.__update_session(user_id, self.STEP_REQ_ADDRESS, {"edad": age})

            await update.message.reply_text(
                "🏠 ¡Genial! Ahora, por favor escribe la <b>dirección</b> de la persona que necesita los medicamentos. 📍\n\n"
                "Ejemplo: <code>Calle 123 #45-67, Barrio Centro</code>",
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
            
        elif session and session["step"] == self.STEP_REQ_ADDRESS:
            try:
                address = update.message.text.strip()
                if not address:
                    raise ValueError("La dirección no puede estar vacía.")
            except (ValueError, AttributeError):
                logger.error("Invalid address received.")
                await update.message.reply_text(
                    "Por favor, escribe una dirección válida.",
                    reply_markup=ForceReply(selective=True),
                )
                return
            logger.info(f"Received address: {address}")

            # Update the session with the address
            self.__update_session(user_id, self.STEP_KNOWN_USER, {"direccion_beneficiario": address})

            # Create or update the user in the database
            solicitante_obj = self.get_user(user_id)
            if not solicitante_obj:
                solicitante_obj = self.create_user(user_id, session["session_data"])


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

        elif session and session["step"] == self.STEP_KNOWN_USER:
            # If the user is known, proceed to request medications
            user_id = update.effective_user.id
            logger.info(f"User {user_id} is known. Proceeding to request medications.")

            # Get text from the message
            user_response = update.message.text.strip().lower()
            if user_response == "💊 solicitar medicamentos":
                # Update the session to request medications
                self.__update_session(user_id, self.STEP_REQ_MEDICATIONS, {})

                await update.message.reply_text(
                    "💊 ¿Quieres <b>describir la lista de medicamentos</b> que necesitas?\n\n"
                    "Selecciona una opción:",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("Sí ✅"), KeyboardButton("No, subiré una foto de la receta médica 📷")]
                        ],
                        one_time_keyboard=True,
                        selective=True,
                    ),
                    parse_mode="HTML"
                )
            elif user_response == "📋 consultar el estado de una solicitud":
                # Update the session to request information about requests
                self.__update_session(user_id, self.STEP_REQ_INFO_REQUESTS, {})

                # TODO: Make message of request information more user-friendly
                # Tienes 4 solicitudes:
                # - 1 pendiente
                # - 1 rechazada
                # - 2 aceptadas
                # La ultima solicitud del 3 de Julio de 2025 está en estado Pendiente.
                # TODO: Get info from the database
                request_info = self.get_request_info(session, user_id)

                logger.info(f"Request information for user {user_id}: {request_info}")

                await update.message.reply_html(
                    request_info,
                    reply_markup=ForceReply(selective=True),
                )
            else:
                # If the user response is not recognized, deactivate the session
                self.__end_session(user_id, "Unexpected user response in STEP_KNOWN_USER.")
                logger.error(f"Unexpected user response in session for user {user_id}: {user_response}")

                await update.message.reply_text(
                    "Lo siento, no reconozco esa opción. Por favor, inicia una nueva sesión con /iniciar.",
                    reply_markup=ForceReply(selective=True),
                )

        elif session and session["step"] == self.STEP_REQ_MEDICATIONS:
            # Handle the request for medications
            user_response = update.message.text.strip().lower()
            if user_response == "sí ✅":
                # Proceed to request medication description
                self.__update_session(user_id, self.STEP_REQ_MED_COUNT, {})

                await update.message.reply_text(
                    "🔢 ¿Cuántos medicamentos vas a solicitar?\n"
                    "Por favor, escribe el número de medicamentos que necesitas solicitar. "
                    "Recuerda que puedes solicitar hasta 10 medicamentos. 💊",
                    reply_markup=ForceReply(selective=True),
                )
            elif user_response == "no, subiré una foto de la receta médica 📷":
                # Proceed to request a photo of the prescription
                self.__update_session(user_id, self.STEP_REQ_PHOTO, {})

                await update.message.reply_text(
                    "📄 Por favor, sube el documento en <b>PDF</b> o <b>Imagen</b> de la fórmula médica. "
                    "Puedes tomar una foto o adjuntar el archivo aquí. 🩺💊",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
            else:
                # If the response is not recognized, deactivate the session
                self.__end_session(user_id, "Unexpected user response in STEP_REQ_MEDICATIONS.")
                logger.error(f"Unexpected user response in session for user {user_id}: {user_response}")

                await update.message.reply_text(
                    "Lo siento, no reconozco esa opción. Por favor, inicia una nueva sesión con /iniciar.",
                    reply_markup=ForceReply(selective=True),
                )

        elif session and session["step"] == self.STEP_REQ_MED_COUNT:
            # Handle the request for medication count
            try:
                count_text = update.message.text.strip()
                if not count_text.isdigit():
                    raise ValueError("El número de medicamentos debe ser un número entero.")
                
                # Maximum count can be set as needed, e.g., 10
                max_count = 10
                if int(count_text) > max_count:
                    raise ValueError(f"El número de medicamentos no puede ser mayor que {max_count}.")
            except ValueError as e:
                logger.error(f"Invalid medication count received: {e}")
                await update.message.reply_text(
                    str(e),
                    reply_markup=ForceReply(selective=True),
                )
                return

            except AttributeError:
                logger.error("Invalid medication count received.")
                await update.message.reply_text(
                    "Por favor, escribe un número válido de medicamentos.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            count = int(count_text)
            logger.info(f"Received medication count: {count}")

            # Create Request object or update session data as needed
            solicitud_obj = self.create_request(user_id, count)

            # Update the session with the medication count
            self.__update_session(
                user_id,
                self.STEP_REQ_MED_DESCRIPTION,
                {
                    "medication_count": count,
                    "solicitud_obj": solicitud_obj,  # Assuming you have a method to create a request object
                }
            )

            await update.message.reply_text(
                "📝 Ahora vamos a solicitar los medicamentos uno por uno.\n"
                "💊 Por cada medicamento, primero te pediremos que escribas la primera letra del nombre, "
                "y luego te pediremos la cantidad que necesitas.\n"
                "⚠️ Por favor, no escribas la cantidad todavía. Cuando estés listo para continuar, presiona el botón 'Continuar'.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("Continuar ▶️"), KeyboardButton("Cancelar ❌")]],
                    one_time_keyboard=True,
                    selective=True,
                )
            )

        elif session and session["step"] == self.STEP_REQ_MED_DESCRIPTION:

            # Handle the request for medication description
            user_response = update.message.text.strip().lower()
            if user_response == "continuar ▶️":
                # Proceed to request the medication name and count
                self.__update_session(user_id, self.STEP_REQ_MED_FIST_LETTER, {})

                await update.message.reply_text(
                    "🔤 Por favor, escribe la <b>primera letra</b> del medicamento <b>1</b> que necesitas solicitar. "
                    "Por ejemplo, si buscas 'Acetaminofén', escribe <b>A</b>.\n"
                    "💡 Esto nos ayudará a mostrarte los medicamentos disponibles.",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
            elif user_response == "cancelar ❌":
                # Change status of solicitud_obj to CANCELED
                session_data = session["session_data"]
                if "solicitud_obj" in session_data:
                    solicitud_obj = session_data["solicitud_obj"]
                    solicitud_obj.estado = stock_models.Solicitud.Estado.CANCELADA
                    solicitud_obj.observaciones = f"Solicitud cancelada por el usuario {user_id}."
                    solicitud_obj.save()
                    logger.info(f"Solicitud {solicitud_obj.id} cancelled by user {user_id}.")

                # Cancel the session
                self.__end_session(user_id, "Session cancelled by user")
                logger.info(f"Session cancelled by user {user_id}.")

                await update.message.reply_text(
                    "La sesión ha sido cancelada. Puedes iniciar una nueva sesión con /iniciar.",
                    reply_markup=ForceReply(selective=True),
                )

        elif session and session["step"] == self.STEP_REQ_MED_FIST_LETTER:
            # Handle the request for the first letter of the medication
            first_letter = update.message.text.strip().upper()
            if not first_letter.isalpha() or len(first_letter) != 1:
                logger.error("Invalid first letter received.")
                await update.message.reply_text(
                    "Por favor, escribe una única letra válida.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"Received first letter: {first_letter}")


            # Query available medications list
            medication_list_text = self.get_available_medications(first_letter)

            if medication_list_text:
                # Update the session with the first letter
                self.__update_session(user_id, self.STEP_REQ_MED_LIST_CHOSEN, {"first_letter": first_letter})

                await update.message.reply_text(
                    f"💊 Medicamentos disponibles que comienzan con '{first_letter}':\n\n"
                    f"{medication_list_text}\n\n"
                    "🆔 Por favor, escribe el <b>ID</b> del medicamento que deseas solicitar.\n",
                    reply_markup=ForceReply(selective=True),
                    parse_mode="HTML",
                )
            
            else:
                await update.message.reply_text(
                    f"😕 No se encontraron medicamentos que comiencen con '{first_letter}'.\n"
                    "🔄 Por favor, intenta con otra letra o revisa si escribiste correctamente.",
                    reply_markup=ForceReply(selective=True),
                )

        elif session and session["step"] == self.STEP_REQ_MED_LIST_CHOSEN:
            
            # Handle the selection of a medication from the list
            user_response = update.message.text.strip()
            try:
                selected_id = int(user_response)

                # Validate the selected ID against available medications in the list
                medicamento_donado_query = stock_models.MedicamentoDonado.objects.filter(
                    id=selected_id,
                    estado=stock_models.MedicamentoDonado.Estado.DISPONIBLE,
                    medicamento__nombre_comercial__istartswith=session["session_data"].get("first_letter")
                )

                # Check if the selected ID is valid
                if not medicamento_donado_query.exists():
                    await update.message.reply_text(
                        "ID de medicamento no válido. Por favor, escribe un ID de medicamento válido.",
                        reply_markup=ForceReply(selective=True),
                    )
                    return
            except (ValueError, AttributeError):
                logger.error("Invalid medication ID received.")
                await update.message.reply_text(
                    "Por favor, escribe un ID de medicamento válido.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"User selected medication ID: {selected_id}")

            # Update the session with the selected medication ID
            self.__update_session(user_id, self.STEP_REQ_MED_QUANTITY, {"selected_medication_id": selected_id})

            await update.message.reply_text(
                "¿Cuántas unidades de este medicamento necesitas?",
                reply_markup=ForceReply(selective=True),
            )

        elif session and session["step"] == self.STEP_REQ_MED_QUANTITY:
            # Handle the request for the quantity of the selected medication
            try:
                quantity_text = update.message.text.strip()
                if not quantity_text.isdigit():
                    raise ValueError("La cantidad debe ser un número entero.")
                
                quantity = int(quantity_text)
                if quantity <= 0:
                    raise ValueError("La cantidad debe ser mayor que cero.")
            except (ValueError, AttributeError):
                logger.error("Invalid medication quantity received.")
                await update.message.reply_text(
                    "Por favor, escribe una cantidad válida de medicamentos.",
                    reply_markup=ForceReply(selective=True),
                )
                return

            logger.info(f"Received medication quantity: {quantity}")

            # Update the session with the medication quantity
            selected_medication_id = session["session_data"].get("selected_medication_id")
            self.__update_session(user_id, self.STEP_REQ_PHOTO, {
                "selected_medication_id": selected_medication_id,
                "quantity": quantity,
            })

            # Crear DetalleSolicitud object
            detalle_solicitud_obj = self.create_detail_request(
                user_id,
                session
            )
            if detalle_solicitud_obj:
                # substact 1 of medication_count
                session["session_data"]["medication_count"] -= 1
                if session["session_data"]["medication_count"] <= 0:
                    
                    await update.message.reply_text(
                        "✅ ¡Listo! Ya hemos registrado todos los medicamentos que solicitaste.\n"
                        "📸 Ahora, por favor <b>sube una foto o PDF de la receta médica</b> para completar tu solicitud.\n"
                        "🩺💊 Este paso es <b>obligatorio</b> para poder procesar tu solicitud.",
                        reply_markup=ForceReply(selective=True),
                        parse_mode="HTML",
                    )

                else:
                    # Proceed to request the medication name and count
                    self.__update_session(user_id, self.STEP_REQ_MED_FIST_LETTER, {})

                    await update.message.reply_text(
                        f"🔤 Por favor, escribe la <b>primera letra</b> del medicamento <b>{session['session_data']['medication_count'] + 1}</b> que necesitas solicitar. "
                        "Por ejemplo, si buscas 'Acetaminofén', escribe <b>A</b>.\n"
                        "💡 Esto nos ayudará a mostrarte los medicamentos disponibles.",
                        reply_markup=ForceReply(selective=True),
                        parse_mode="HTML",
                    )

            else:
                logger.error("Failed to create DetalleSolicitud object.")
                await update.message.reply_text(
                    "Hubo un error al procesar tu solicitud. Por favor, intenta de nuevo más tarde.",
                    reply_markup=ForceReply(selective=True),
                )

        elif session and session["step"] == self.STEP_REQ_PHOTO:
            # Handle the request for a photo of the prescription
            solicitud_obj = session["session_data"].get("solicitud_obj")
            if not solicitud_obj:
                # Create Request object or update session data as needed
                count = 1
                solicitud_obj = self.create_request(user_id, count)

                # Update the session with the medication count
                self.__update_session(
                    user_id,
                    self.STEP_END,
                    {
                        "medication_count": count,
                        "solicitud_obj": solicitud_obj,  # Assuming you have a method to create a request object
                    }
                )
            else:
                self.__update_session(user_id, self.STEP_END, {})

            
            # Update the session with the request object
            session = next((s for s in self.__sessions if s["user_id"] == user_id), None)

            # Handle the request for a photo of the prescription
            if update.message.document:
                # If a photo is sent, save it or process it as needed
                photo_file = await update.message.document.get_file()

                # Ensure the file has a valid extension
                file_name_extension = os.path.splitext(update.message.document.file_name)[1]
                if not file_name_extension:
                    file_name_extension = ".jpg"

                photo_path_tmp = f"{settings.BASE_DIR}/photos/{update.message.document.file_unique_id}{file_name_extension}"
                await photo_file.download_to_drive(photo_path_tmp)

            elif update.message and update.message.photo:
                # If a photo is sent, save it or process it as needed
                photo = update.message.photo[-1]  # Get the highest resolution photo

                photo_file = await photo.get_file()
                photo_dir = f"{settings.BASE_DIR}/photos"
                if not os.path.exists(photo_dir):
                    os.makedirs(photo_dir)
                photo_path_tmp = f"{photo_dir}/{photo.file_unique_id}.jpg"

                # Download the photo using the correct method for python-telegram-bot v20+
                await photo_file.download_to_drive(photo_path_tmp)

            else:
                # If no photo is sent, ask the user to send one again
                self.__update_session(user_id, self.STEP_REQ_PHOTO, {})

                logger.error("No photo received.")
                await update.message.reply_text(
                    "Por favor, sube una foto de la receta médica.",
                    reply_markup=ForceReply(selective=True),
                )
                return
            
            
            formula_obj = self.save_photo_to_request(
                user_id,
                solicitud_obj,
                photo_path_tmp
            )

            # Complete the session
            self.__end_session(user_id)

            await update.message.reply_text(
                "✅ ¡Gracias! Hemos recibido tu foto o PDF de la receta médica. 🩺💊\n"
                "📋 Procesaremos tu solicitud y te notificaremos cuando esté lista.\n"
                "🙏 ¡Gracias por confiar en nuestro sistema de donación de medicamentos!"
            )
            
            # NOTE: Now close the session after the photo is uploaded

        else:
            # If the session is not in a known step, deactivate it
            self.__end_session(user_id, f"Unexpected step in session: {session['step'] if session else 'No session found'}")
            logger.error(f"Unexpected step in session for user {user_id}: {session['step'] if session else 'No session found'}")

            logger.warning(f"Received message in unexpected step: {session['step'] if session else 'No session found'}")
            await update.message.reply_text(
                "Lo siento, no reconozco esa opción. Por favor, inicia una nueva sesión con /iniciar.",
                reply_markup=ForceReply(selective=True),
            )


    async def wellcome_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a welcome message when the command /inicio is issued."""

        logger.info("Welcome user command received.")
        # Get the user ID from the update
        user_id = update.effective_user.id

        # Check if the user has already started a session
        session = next((s for s in self.__sessions if s["user_id"] == user_id), None)
        if session and session["is_active"]:
            logger.info(f"User {user_id} already has an active session.")
            await update.message.reply_text(
                "👋 Ya tienes una sesión activa. Por favor, completa la sesión actual."
                )
            return


        solicitante_obj = self.get_user(user_id)

        if solicitante_obj:

            # Update the session with the user's data
            session_data = {
                "documento": solicitante_obj.documento,
                "nombre": solicitante_obj.nombre,
                "direccion_beneficiario": solicitante_obj.direccion_beneficiario,
                "edad": solicitante_obj.edad,
            }
            
            self.__update_session(user_id, self.STEP_KNOWN_USER, session_data)


            first_name = solicitante_obj.nombre.split(" ")[0]  # Get the first name
            await update.message.reply_html(
                f"👋 ¡Hola {first_name}! Bienvenido de nuevo.\n"
                "¿Qué deseas hacer hoy?\n",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar el estado de una solicitud")]
                    ],
                    one_time_keyboard=True,
                    selective=True,
                )
            )

        else:
            logger.info(f"User with ID {user_id} not found in the database.")
            
            # Start a new session for the user
            self.__update_session(user_id, self.STEP_NEW_USER, {
                "documento": None,
                "nombre": None,
                "direccion_beneficiario": None,
                "edad": None,
            })

            # Send a welcome message to the user
            logger.info("Sending welcome message to the user.")
            
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