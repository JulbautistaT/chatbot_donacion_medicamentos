#!/usr/bin/env python
# pylint: disable=unused-argument


# import logging

# from telegram import ForceReply, Update, KeyboardButton, ReplyKeyboardMarkup
# from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# # Enable logging
# logging.basicConfig(
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
# )
# # set higher logging level for httpx to avoid all GET and POST requests being logged
# logging.getLogger("httpx").setLevel(logging.WARNING)

# logger = logging.getLogger(__name__)


# # Define a few command handlers. These usually take the two arguments update and
# # context.
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """Send a message when the command /start is issued."""
#     user = update.effective_user
#     await update.message.reply_html(
#         rf"Hi {user.mention_html()}!",
#         reply_markup=ForceReply(selective=True),
#     )


# async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """Send a message when the command /help is issued."""
#     await update.message.reply_text("Help!")


# async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """Echo the user message."""
    
#     # Get user id
#     user_id = update.effective_user.id
#     logger.info(f"Received message from user ID: {user_id}")

#     # Send a message back to the user
#     await update.message.reply_text(
#         f"You said: {update.message.text}\n"
#         "If you want to share your contact, please click the button below.",
#         reply_markup=ReplyKeyboardMarkup(
#             [[KeyboardButton("Share Contact", request_contact=True)]],
#             one_time_keyboard=True,
#             resize_keyboard=True,
#         ),
#     )



# async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """Handle the contact information sent by the user."""
#     contact = update.message.contact
#     if contact:
#         phone_number = contact.phone_number
#         logger.info(f"Received contact with phone number: {phone_number}")
#         await update.message.reply_text(f"Thank you for sharing your contact: {phone_number}")
#     else:
#         logger.warning("No contact information received.")
#         await update.message.reply_text("No contact information received. Please try again.")


import os
import sys
import django

PATH = os.path.dirname(os.path.abspath(__file__))
PROJECT_PATH = os.path.join(PATH)
os.chdir(PROJECT_PATH)
sys.path.append(PROJECT_PATH)
os.environ['DJANGO_SETTINGS_MODULE'] = "donacion_medicamentos.settings"
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'True'
django.setup()

from donacion_medicamentos import bot_controller


def main() -> None:
    """Start the bot."""
    
    bot_controller_class_obj = bot_controller.BotController()
    bot_controller_class_obj.run()


if __name__ == "__main__":
    main()