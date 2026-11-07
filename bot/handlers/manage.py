"""⚙️ Gestisci: riorganizzare l'archivio da Telegram.

Tutto avviene solo su disco, sotto archive_dir. Gli utenti vedono le modifiche
dopo /reindex.
"""

import logging
import os
import shutil
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import archive, keyboards
from bot.db import inbox
from bot.filters import IsAdmin
from bot.handlers import submit
from bot.texts import inbox as T

if TYPE_CHECKING:
    from bot.config import Settings

log = logging.getLogger(__name__)
router = Router(name="manage")

COMMANDS: list[BotCommand] = []
ADMIN_COMMANDS = [BotCommand(command="annulla", description="Annulla l'operazione di Gestisci")]

PRICES = (5, 10, 20)


class ManageError(Exception):
    """Errore da mostrare all'admin (messaggio già in italiano)."""


class NeedPrice(ManageError):
    """Lo spostamento in EXCLUSIVE richiede un prezzo."""


# --- operazioni su disco (sincrone, testabili) ---------------------------------

def _abs(settings: "Settings", rel: str) -> Path:
    p = submit.resolve_inside(settings.archive_dir, rel)
    if p is None:
        raise ManageError(T.M_PROTECTED)
    return p


def _root(settings: "Settings") -> Path:
    return settings.archive_dir.resolve()


def _rel(settings: "Settings", p: Path) -> str:
    return p.relative_to(_root(settings)).as_posix()


def _check_node(settings: "Settings", path: str) -> Path:
    """Percorso assoluto del nodo; vietato toccare EXCLUSIVE stesso e la radice."""
    if not path or path == archive.EXCLUSIVE:
        raise ManageError(T.M_PROTECTED)
    p = _abs(settings, path)
    if p == _root(settings):
        raise ManageError(T.M_PROTECTED)
    if not (p.exists() or p.is_symlink()):
        raise ManageError(T.M_NOT_FOUND)
    return p


def clean_name(raw: str) -> str:
    """Nome scritto dall'admin -> nome sicuro; errore se non contiene nulla di utile."""
    if not any(c.isalnum() for c in raw):
        raise ManageError(T.M_BAD_NAME)
    return submit.sanitize_filename(raw)


def op_mkdir(settings: "Settings", parent_rel: str, name: str) -> str:
    """Crea parent_rel/name ('' = radice dell'archivio). Ritorna il percorso relativo."""
    name = clean_name(name)
    parent = _abs(settings, parent_rel) if parent_rel else _root(settings)
    if not parent.is_dir():
        raise ManageError(T.M_NOT_FOUND)
    target = parent / name
    if target.exists() or target.is_symlink():
        raise ManageError(T.M_CONFLICT)
    target.mkdir()
    return _rel(settings, target)


def op_rename(settings: "Settings", path: str, is_dir: bool, price: int, new_name: str) -> str:
    """Rinomina. Sotto EXCLUSIVE un file riceve di nuovo il prefisso prezzo."""
    src = _check_node(settings, path)
    name = clean_name(new_name)
    if not is_dir and submit.is_exclusive_path(path):
        name = submit.with_price(price, name)
    dst = src.parent / name
    if dst == src:
        return path
    if dst.exists() or dst.is_symlink():
        raise ManageError(T.M_CONFLICT)
    os.rename(src, dst)
    return _rel(settings, dst)


def op_move(settings: "Settings", path: str, is_dir: bool, dest_folder_rel: str,
            price: int | None = None) -> str:
    """Sposta in dest_folder_rel ('' = radice). Entrando in EXCLUSIVE un file
    richiede `price`; uscendone perde il prefisso prezzo."""
    src = _check_node(settings, path)
    dest = _abs(settings, dest_folder_rel) if dest_folder_rel else _root(settings)
    if not dest.is_dir():
        raise ManageError(T.M_NOT_FOUND)
    if is_dir and (dest == src or dest.is_relative_to(src)):
        raise ManageError(T.M_DEST_INSIDE)
    src_ex = submit.is_exclusive_path(path)
    dst_ex = bool(dest_folder_rel) and submit.is_exclusive_path(dest_folder_rel)
    name = src.name
    if src_ex != dst_ex:
        if is_dir:
            raise ManageError(T.M_EXCL_FOLDER)
        if dst_ex:
            if price is None:
                raise NeedPrice(T.M_ASK_PRICE_MOVE)
            name = submit.with_price(price, name)
        else:
            name = submit.strip_price(name)
    target = dest / name
    if target.exists() or target.is_symlink():
        raise ManageError(T.M_CONFLICT)
    shutil.move(str(src), str(target))
    return _rel(settings, target)


def op_price(settings: "Settings", path: str, is_dir: bool, price: int) -> str:
    """Riscrive il prefisso prezzo di un file sotto EXCLUSIVE."""
    if is_dir or not submit.is_exclusive_path(path):
        raise ManageError(T.M_PRICE_ONLY_EXCL)
    if not 1 <= price <= 10_000:
        raise ManageError(T.M_BAD_NAME)
    src = _check_node(settings, path)
    dst = src.parent / submit.with_price(price, submit.strip_price(src.name))
    if dst == src:
        return path
    if dst.exists() or dst.is_symlink():
        raise ManageError(T.M_CONFLICT)
    os.rename(src, dst)
    return _rel(settings, dst)


def op_delete(settings: "Settings", path: str, today: date | None = None) -> str:
    """Sposta nel cestino trash/<AAAA-MM-GG>/<percorso originale>. Mai cancellazione."""
    src = _check_node(settings, path)
    day = (today or date.today()).isoformat()
    trash_root = settings.trash_dir.resolve()
    target = trash_root / day / path
    if not target.resolve().is_relative_to(trash_root):
        raise ManageError(T.M_PROTECTED)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = submit.unique_path(target.parent, target.name)
    shutil.move(str(src), str(target))
    return target.relative_to(trash_root).as_posix()


# --- tastiere ------------------------------------------------------------------

def _reindex_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=T.M_BTN_REINDEX, callback_data="rx:start")]


def _done_markup(back_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [_reindex_row()]
    if back_id is not None:
        rows.append([InlineKeyboardButton(text=T.M_BTN_BACK, callback_data=f"adm:menu:{back_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _panel(node) -> tuple[str, InlineKeyboardMarkup]:
    if node is None:
        where = T.M_HOME
        rows = [[InlineKeyboardButton(text=T.M_BTN_MKDIR, callback_data="adm:mkdir:0")]]
    else:
        where = submit.display_path(node.path)
        rows = []
        if node.is_dir:
            rows.append([InlineKeyboardButton(text=T.M_BTN_MKDIR, callback_data=f"adm:mkdir:{node.id}")])
        rows.append([InlineKeyboardButton(text=T.M_BTN_RENAME, callback_data=f"adm:ren:{node.id}"),
                     InlineKeyboardButton(text=T.M_BTN_MOVE, callback_data=f"adm:mv:{node.id}")])
        if not node.is_dir and submit.is_exclusive_path(node.path):
            rows.append([InlineKeyboardButton(text=T.M_BTN_PRICE, callback_data=f"adm:price:{node.id}")])
        rows.append([InlineKeyboardButton(text=T.M_BTN_DELETE, callback_data=f"adm:del:{node.id}")])
    rows.append(_reindex_row())
    back = node.id if node is not None and node.is_dir else (node.parent_id if node else None)
    if back is not None:
        rows.append([InlineKeyboardButton(text=T.M_BTN_BACK, callback_data=f"n:{back}")])
    return T.M_PANEL.format(where=where), InlineKeyboardMarkup(inline_keyboard=rows)


def _prices_markup(prefix: str, cancel: str, settings: "Settings") -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=f"{p} crediti", callback_data=f"{prefix}:{p}")
           for p in PRICES if p <= settings.price_max]
    return InlineKeyboardMarkup(inline_keyboard=[
        row, [InlineKeyboardButton(text=T.M_BTN_CANCEL, callback_data=cancel)]])


# --- FSM ------------------------------------------------------------------------

def _not_ticket_reply(message: Message, settings: "Settings") -> bool:
    """Le reply alle schede ticket (gruppo staff) vanno a tickets, non al nome cartella."""
    reply = message.reply_to_message
    return (reply is None or message.chat.id != settings.staff_chat_id
            or inbox.get_ticket_by_staff_message(reply.message_id) is None)


class Flow(StatesGroup):
    mkdir = State()
    rename = State()


async def _show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    if isinstance(callback.message, Message):
        await submit.edit_message(callback.message, text, markup)


def _node(node_id: int):
    return archive.tree.get(node_id) if node_id else None


def _log(admin_id: int, op: str, *paths: str) -> None:
    log.info("gestisci: admin=%s op=%s %s", admin_id, op, " -> ".join(paths))


@router.message(Command("annulla"), IsAdmin())
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(T.M_NOTHING)
        return
    await state.clear()
    await message.answer(T.M_CANCELLED)


@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:menu:\d+$"))
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    node_id = int(callback.data.split(":")[2])
    node = _node(node_id)
    if node_id and node is None:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await callback.answer()
    text, kb = _panel(node)
    await _show(callback, text, kb)


# nuova cartella ---------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:mkdir:\d+$"))
async def cb_mkdir(callback: CallbackQuery, state: FSMContext, settings: "Settings") -> None:
    node_id = int(callback.data.split(":")[2])
    node = _node(node_id)
    msg = callback.message
    if (node_id and (node is None or not node.is_dir)) or not isinstance(msg, Message):
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    ctx = submit.context_for_message(msg, settings)
    await state.set_state(Flow.mkdir)
    await state.update_data(parent=node.path if node else "", panel=msg, ctx=ctx, node_id=node_id)
    await callback.answer()
    where = submit.display_path(node.path) if node else T.M_HOME
    await msg.answer(T.M_ASK_MKDIR.format(where=where))


@router.message(Flow.mkdir, IsAdmin(), F.text, ~F.text.startswith("/"), _not_ticket_reply)
async def msg_mkdir(message: Message, state: FSMContext, bot: Bot, settings: "Settings") -> None:
    data = await state.get_data()
    try:
        rel = op_mkdir(settings, data["parent"], message.text)
    except ManageError as e:
        await message.answer(str(e))
        return
    await state.clear()
    _log(message.from_user.id, "mkdir", rel)
    ctx = data.get("ctx")
    sub = inbox.get_submission(ctx) if ctx else None
    if sub is not None and sub.status == "pending":
        # durante la moderazione/invio: la nuova cartella diventa la destinazione
        await submit.set_destination(bot, settings, data["panel"], message.from_user.id, sub, rel)
        await message.answer(T.M_MKDIR_SET)
        return
    await message.answer(T.M_DONE, reply_markup=_done_markup(data.get("node_id") or None))


# rinomina -------------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:ren:\d+$"))
async def cb_rename(callback: CallbackQuery, state: FSMContext) -> None:
    node = _node(int(callback.data.split(":")[2]))
    if node is None or not isinstance(callback.message, Message):
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    await state.set_state(Flow.rename)
    await state.update_data(node_id=node.id)
    await callback.answer()
    await callback.message.answer(T.M_ASK_RENAME.format(name=T.escape(node.name)))


@router.message(Flow.rename, IsAdmin(), F.text, ~F.text.startswith("/"), _not_ticket_reply)
async def msg_rename(message: Message, state: FSMContext, settings: "Settings") -> None:
    data = await state.get_data()
    node = _node(data["node_id"])
    if node is None:
        await state.clear()
        await message.answer(T.M_NOT_FOUND)
        return
    try:
        new = op_rename(settings, node.path, node.is_dir, node.price, message.text)
    except ManageError as e:
        await message.answer(str(e))
        return
    await state.clear()
    _log(message.from_user.id, "rename", node.path, new)
    await message.answer(T.M_DONE, reply_markup=_done_markup())


# sposta ---------------------------------------------------------------------
# La navigazione della destinazione usa keyboards.folder(mode="staff") con
# ctx NEGATIVO = -(id del nodo da spostare): dsn:-<id>:<cartella>, dst:-<id>:<cartella>.

@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:mv:\d+$"))
async def cb_move(callback: CallbackQuery) -> None:
    node = _node(int(callback.data.split(":")[2]))
    if node is None:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    text, kb = keyboards.folder(None, mode="staff", ctx=-node.id, is_admin=True)
    await _show(callback, f"{T.M_ASK_DEST.format(name=T.escape(node.name))}\n\n{text}", kb)


@router.callback_query(IsAdmin(), F.data.regexp(r"^dsn:-\d+:\d+(:\d+)?$"))
async def cb_move_nav(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    node = _node(-int(parts[1]))
    if node is None:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    dest = _node(int(parts[2]))
    page = int(parts[3]) if len(parts) > 3 else 0
    text, kb = keyboards.folder(dest.id if dest else None, page, mode="staff", ctx=-node.id, is_admin=True)
    await callback.answer()
    await _show(callback, f"{T.M_ASK_DEST.format(name=T.escape(node.name))}\n\n{text}", kb)


async def _do_move(callback: CallbackQuery, settings: "Settings", node, dest_id: int,
                   price: int | None) -> None:
    dest = _node(dest_id)
    if dest_id and (dest is None or not dest.is_dir):
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    dest_rel = dest.path if dest else ""
    try:
        new = op_move(settings, node.path, node.is_dir, dest_rel, price)
    except NeedPrice:
        await callback.answer()
        await _show(callback, T.M_ASK_PRICE_MOVE,
                    _prices_markup(f"adm:mvp:{node.id}:{dest_id}", f"adm:menu:{node.id}", settings))
        return
    except ManageError as e:
        await callback.answer(str(e), show_alert=True)
        return
    _log(callback.from_user.id, "move", node.path, new)
    await callback.answer()
    await _show(callback, T.M_DONE, _done_markup())


@router.callback_query(IsAdmin(), F.data.regexp(r"^dst:-\d+:\d+$"))
async def cb_move_dst(callback: CallbackQuery, settings: "Settings") -> None:
    _, ctx, dest_id = callback.data.split(":")
    node = _node(-int(ctx))
    if node is None:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    await _do_move(callback, settings, node, int(dest_id), None)


@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:mvp:\d+:\d+:\d+$"))
async def cb_move_price(callback: CallbackQuery, settings: "Settings") -> None:
    _, _, node_id, dest_id, price = callback.data.split(":")
    node = _node(int(node_id))
    if node is None or int(price) not in PRICES or int(price) > settings.price_max:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    await _do_move(callback, settings, node, int(dest_id), int(price))


# prezzo ---------------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:price:\d+(:\d+)?$"))
async def cb_price(callback: CallbackQuery, settings: "Settings") -> None:
    parts = callback.data.split(":")
    node = _node(int(parts[2]))
    if node is None:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    if node.is_dir or not submit.is_exclusive_path(node.path):
        await callback.answer(T.M_PRICE_ONLY_EXCL, show_alert=True)
        return
    if len(parts) == 3:
        await callback.answer()
        await _show(callback, T.M_ASK_PRICE,
                    _prices_markup(f"adm:price:{node.id}", f"adm:menu:{node.id}", settings))
        return
    price = int(parts[3])
    if price < 1 or price > settings.price_max:
        await callback.answer(T.M_BAD_NAME, show_alert=True)
        return
    try:
        new = op_price(settings, node.path, node.is_dir, price)
    except ManageError as e:
        await callback.answer(str(e), show_alert=True)
        return
    _log(callback.from_user.id, "price", node.path, new)
    await callback.answer()
    await _show(callback, T.M_DONE, _done_markup())


# elimina --------------------------------------------------------------------

@router.callback_query(IsAdmin(), F.data.regexp(r"^adm:del:\d+(:ok)?$"))
async def cb_delete(callback: CallbackQuery, settings: "Settings") -> None:
    parts = callback.data.split(":")
    node = _node(int(parts[2]))
    if node is None:
        await callback.answer(T.M_NOT_FOUND, show_alert=True)
        return
    if len(parts) == 3:
        await callback.answer()
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=T.M_BTN_CONFIRM, callback_data=f"adm:del:{node.id}:ok"),
            InlineKeyboardButton(text=T.M_BTN_CANCEL, callback_data=f"adm:menu:{node.id}"),
        ]])
        await _show(callback, T.M_CONFIRM_DEL.format(name=T.escape(node.name)), kb)
        return
    try:
        trashed = op_delete(settings, node.path)
    except ManageError as e:
        await callback.answer(str(e), show_alert=True)
        return
    _log(callback.from_user.id, "delete", node.path, f"trash/{trashed}")
    await callback.answer()
    await _show(callback, T.M_DONE, _done_markup())
