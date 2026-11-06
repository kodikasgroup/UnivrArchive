"""Gruppi dei corsi: /collega, /scollega e /materiale (messaggi effimeri)."""

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardMarkup, Message

from bot import archive, keyboards
from bot.config import Settings
from bot.db import content
from bot.handlers import files
from bot.texts import browse as T

log = logging.getLogger(__name__)

router = Router(name="groups")

# /materiale è un comando effimero: nel gruppo non resta nessun messaggio visibile.
COMMANDS: list[BotCommand] = [
    BotCommand(command="materiale", description="Il materiale del corso", is_ephemeral=True),
]
ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="collega", description="Collega questo gruppo a una cartella"),
    BotCommand(command="scollega", description="Scollega questo gruppo"),
]

_IN_GROUP = F.chat.type.in_({"group", "supergroup"})


def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return user_id is not None and user_id in settings.admin_ids


def linked_node(chat_id: int) -> archive.Node | None:
    """Cartella collegata al gruppo; se è stata rimossa, la più vicina ancora visibile.
    None = nessun collegamento oppure si ricade sulla HOME."""
    node_id = content.get_group_folder(chat_id)
    if node_id is None:
        return None
    return archive.tree.get(node_id) or archive.tree.nearest_visible(node_id)


# --- /collega e /scollega (solo admin; in gruppi non collegati tutto il resto tace) ------------


@router.message(Command("collega"), _IN_GROUP)
async def on_link(message: Message, settings: Settings) -> None:
    if not _is_admin(message.from_user and message.from_user.id, settings):
        return
    text, kb = keyboards.folder(None, mode="group")
    await message.answer(text, reply_markup=kb)


@router.message(Command("scollega"), _IN_GROUP)
async def on_unlink(message: Message, settings: Settings) -> None:
    if not _is_admin(message.from_user and message.from_user.id, settings):
        return
    if content.get_group_folder(message.chat.id) is None:
        return  # gruppo non collegato: il bot non risponde
    content.delete_group_folder(message.chat.id)
    await message.answer(T.GROUP_UNLINKED)


@router.callback_query(F.data.startswith("grp:"))
async def on_group_pick(q: CallbackQuery, bot: Bot, settings: Settings) -> None:
    if not _is_admin(q.from_user.id, settings):
        await q.answer(T.ONLY_ADMIN, show_alert=True)
        return
    parts = q.data.split(":")
    try:
        node_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 and parts[2] != "ok" else 0
    except (IndexError, ValueError):
        await q.answer()
        return
    confirmed = len(parts) > 2 and parts[2] == "ok"
    node = archive.tree.get(node_id) if node_id else None
    if confirmed:
        if node is None or not node.is_dir or q.message is None:
            await q.answer(T.GROUP_PICK_FIRST, show_alert=True)
            return
        content.set_group_folder(q.message.chat.id, node.id, q.from_user.id)
        await q.answer()
        await files.show_view(bot, q, T.GROUP_LINKED.format(name=html.escape(node.name)),
                              InlineKeyboardMarkup(inline_keyboard=[]))
        return
    await q.answer()
    text, kb = keyboards.folder(node.id if node else None, page, mode="group")
    await files.show_view(bot, q, text, kb)


# --- /materiale ---------------------------------------------------------------------------------


@router.message(Command("materiale"), _IN_GROUP)
async def on_material(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user is None or content.get_group_folder(message.chat.id) is None:
        return  # gruppo non collegato: il bot non risponde
    await files.ensure_username(bot)
    node = linked_node(message.chat.id)
    text, kb = keyboards.folder(node.id if node else None, mode="browse")
    await files.send_ephemeral(bot, message.chat.id, user.id, text, kb)


@router.message(Command("materiale"), F.chat.type == "private")
async def on_material_private(message: Message) -> None:
    await message.answer(T.MATERIALE_PRIVATE)
