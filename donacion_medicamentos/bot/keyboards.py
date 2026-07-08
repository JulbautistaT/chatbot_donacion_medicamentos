"""Todos los teclados ReplyKeyboardMarkup del bot.

Los textos de los botones se mantienen byte a byte iguales al original.
"""
from telegram import KeyboardButton, ReplyKeyboardMarkup


def accept_policy_keyboard() -> ReplyKeyboardMarkup:
    """Teclado de aceptación de la política de datos."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton('Acepto ✅')]],
        one_time_keyboard=True,
        selective=True,
    )


def known_user_keyboard() -> ReplyKeyboardMarkup:
    """Menú principal de usuario conocido."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("💊 Solicitar medicamentos"), KeyboardButton("📋 Consultar solicitudes")]],
        one_time_keyboard=True, selective=True,
    )


def retry_photo_keyboard() -> ReplyKeyboardMarkup:
    """Reintentar foto o pasar a flujo manual."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📷 Intentar con otra foto"),
          KeyboardButton("📝 Describir medicamentos manualmente")]],
        one_time_keyboard=True, selective=True,
    )


def manual_or_photo_keyboard() -> ReplyKeyboardMarkup:
    """Elegir entre describir medicamentos o subir receta."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📝 Describir medicamentos"), KeyboardButton("📷 Subir receta médica")]],
        one_time_keyboard=True, selective=True,
    )


def yes_no_keyboard(left_text: str, right_text: str) -> ReplyKeyboardMarkup:
    """Teclado genérico de dos botones en una fila (el orden lo define el llamador).

    Usos actuales (textos exactos del original):
      - "Sí, correcto ✅" / "No, corregir ✏️"      (datos de usuario conocido)
      - "Sí, es el mío ✅" / "No, corregir ✏️"     (confirmación de revinculación)
      - "Corregir ✏️" / "Sí, continuar ✅"         (confirmar datos de registro)
      - "Continuar ▶️" / "Cancelar ❌"             (inicio de descripción de medicamentos)
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(left_text), KeyboardButton(right_text)]],
        one_time_keyboard=True, selective=True,
    )
