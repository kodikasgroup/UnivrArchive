from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from bot.config import Settings


class IsAdmin(Filter):
    """Mittente tra gli ADMIN_IDS (message e callback_query)."""

    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_ids


class IsPrivate(Filter):
    """Chat privata col bot."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if event.message else None)
        return chat is not None and chat.type == "private"
