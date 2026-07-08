"""Dispatcher: envía la actualización al handler correspondiente según el paso."""
from typing import Any, Awaitable, Callable, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

# Firma común de los handlers de paso:
# async def handler(update, context, telegram_id, session, text) -> Optional[bool]
StepHandler = Callable[..., Awaitable[Optional[bool]]]


class Dispatcher:
    """Solo hace: handler = handlers[step]; await handler(...)."""

    def __init__(self, handlers: Dict[str, StepHandler]) -> None:
        self.handlers = handlers

    def knows(self, step: str) -> bool:
        return step in self.handlers

    async def dispatch(self, step: str, update: Update, context: ContextTypes.DEFAULT_TYPE,
                       telegram_id: int, session: Dict[str, Any], text: str) -> Optional[bool]:
        """Devuelve el resultado del handler.

        Convención: False explícito = el handler no procesó el mensaje
        (equivale al 'fall-through' del if/elif original hacia PASO INESPERADO).
        None o True = procesado.
        """
        handler = self.handlers[step]
        return await handler(update, context, telegram_id, session, text)
