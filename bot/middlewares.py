import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot import db

log = logging.getLogger(__name__)
INTERVAL = 3600  # secondi tra due upsert dello stesso utente


class UserMiddleware(BaseMiddleware):
    """Outer middleware sugli Update: registra/aggiorna l'utente al massimo 1 volta/ora
    (sempre al primo update dopo l'avvio). Non blocca mai l'update."""

    def __init__(self) -> None:
        self._seen: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is not None and not user.is_bot:
            now = time.monotonic()
            last = self._seen.get(user.id)
            if last is None or now - last >= INTERVAL:
                try:
                    db.upsert_user(user.id, user.username, user.first_name)
                    self._seen[user.id] = now
                except Exception:
                    log.exception("upsert_user fallito per %s", user.id)
        return await handler(event, data)
