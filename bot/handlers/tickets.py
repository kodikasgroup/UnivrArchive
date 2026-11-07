"""Ticket: feedback, segnalazioni, richieste di rimozione."""

import logging
import re
import secrets
from typing import TYPE_CHECKING, Literal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReactionTypeEmoji, User

from bot import archive, db
from bot.db import inbox
from bot.filters import IsAdmin, IsPrivate
from bot.texts import inbox as T

if TYPE_CHECKING:
    from bot.config import Settings

log = logging.getLogger(__name__)
router = Router(name="tickets")

COMMANDS = [
    BotCommand(command="feedback", description="Scrivi allo staff"),
    BotCommand(command="rimozione", description="Chiedi la rimozione di un file"),
]
ADMIN_COMMANDS: list[BotCommand] = []

MAX_TEXT = 2000
_NODE_LINK = re.compile(r"f_(\d+)")


def _close_markup(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=T.T_CLOSE_BTN, callback_data=f"tk:{ticket_id}:ok"),
    ]])


def _node_label(node_id: int | None) -> str | None:
    if node_id is None:
        return None
    node = archive.tree.get(node_id)
    return node.path if node else f"nodo #{node_id}"


async def open_ticket(bot: Bot, settings: "Settings", user: User,
                      kind: Literal["feedback", "report", "removal"],
                      text: str | None = None, node_id: int | None = None) -> int:
    """Crea la riga, pubblica la scheda nel gruppo staff, ritorna l'id del ticket."""
    if text:
        text = text[:MAX_TEXT]
    # staff_message_id è NOT NULL e unico: valore temporaneo, poi quello vero
    temp = -secrets.randbits(40) - 1
    ticket_id = inbox.create_ticket(user.id, kind, node_id, text, temp)
    card = T.ticket_card(ticket_id, kind, T.user_label(user.username, user.first_name, user.id),
                         user.id, _node_label(node_id), text)
    try:
        sent = await bot.send_message(settings.staff_chat_id, card,
                                      reply_markup=_close_markup(ticket_id))
    except Exception:
        inbox.delete_ticket(ticket_id)
        raise
    inbox.set_ticket_staff_message(ticket_id, sent.message_id)
    return ticket_id


# --- comandi utente ------------------------------------------------------

@router.message(IsPrivate(), Command("feedback"))
async def cmd_feedback(message: Message, command: CommandObject, bot: Bot, settings: "Settings") -> None:
    text = (command.args or "").strip()
    if not text or message.from_user is None:
        await message.answer(T.T_FEEDBACK_HELP)
        return
    await open_ticket(bot, settings, message.from_user, "feedback", text)
    await message.answer(T.T_THANKS)


@router.message(IsPrivate(), Command("rimozione"))
async def cmd_removal(message: Message, command: CommandObject, bot: Bot, settings: "Settings") -> None:
    text = (command.args or "").strip()
    if not text or message.from_user is None:
        await message.answer(T.T_REMOVAL_HELP)
        return
    node_id = None
    m = _NODE_LINK.search(text)
    if m:
        candidate = int(m.group(1))
        if archive.tree.get(candidate) is not None:
            node_id = candidate
    await open_ticket(bot, settings, message.from_user, "removal", text, node_id)
    await message.answer(T.T_THANKS)


# --- chiusura ------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.regexp(r"^tk:\d+:ok$"))
async def cb_close(callback: CallbackQuery) -> None:
    ticket_id = int(callback.data.split(":")[1])
    if not inbox.close_ticket(ticket_id, callback.from_user.id):
        await callback.answer(T.T_ALREADY_CLOSED)
        return
    await callback.answer(T.T_CLOSED_TOAST)
    msg = callback.message
    if isinstance(msg, Message):
        who = T.user_label(callback.from_user.username, callback.from_user.first_name,
                           callback.from_user.id)
        try:
            await msg.edit_text(T.ticket_closed(msg.html_text, who), reply_markup=None)
        except TelegramAPIError:
            log.warning("scheda ticket %s non modificabile", ticket_id, exc_info=True)


# --- reply dello staff ---------------------------------------------------

async def _is_staff_ticket_reply(message: Message, settings: "Settings") -> bool | dict:
    """Reply di un admin, nel gruppo staff, a una scheda ticket."""
    if message.chat.id != settings.staff_chat_id or message.reply_to_message is None:
        return False
    if message.from_user is None or message.from_user.id not in settings.admin_ids:
        return False
    ticket = inbox.get_ticket_by_staff_message(message.reply_to_message.message_id)
    if ticket is None:
        return False  # scheda di invio o altro: non è un ticket
    return {"ticket": ticket}


@router.message(_is_staff_ticket_reply)
async def staff_reply(message: Message, bot: Bot, ticket: inbox.Ticket) -> None:
    if ticket.status != "open":
        await message.reply(T.T_CLOSED_TOAST)
        return
    try:
        await bot.send_message(ticket.user_id, T.T_REPLY_PREFIX)
        await bot.copy_message(ticket.user_id, message.chat.id, message.message_id)
    except TelegramForbiddenError:
        db.set_blocked(ticket.user_id, True)
        await message.reply(T.T_USER_BLOCKED)
        return
    except TelegramAPIError:
        log.warning("risposta al ticket %s non consegnata", ticket.id, exc_info=True)
        await message.reply(T.T_USER_BLOCKED)
        return
    try:
        await bot.set_message_reaction(message.chat.id, message.message_id,
                                       reaction=[ReactionTypeEmoji(emoji="👍")])
    except TelegramAPIError:
        pass
