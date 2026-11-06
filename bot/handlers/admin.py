"""Comandi admin: /reindex, /stats, /crediti_add, /vip, /pending, /broadcast."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import archive, db, storage
from bot.config import Settings
from bot.db import inbox, stats
from bot.filters import IsAdmin, IsPrivate
from bot.texts import admin as T

log = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(IsAdmin(), IsPrivate())
router.callback_query.filter(IsAdmin())

COMMANDS: list[BotCommand] = []
ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="reindex", description="Scansiona l'archivio e mostra l'anteprima"),
    BotCommand(command="stats", description="Statistiche del bot"),
    BotCommand(command="crediti_add", description="Aggiungi o togli crediti a un utente"),
    BotCommand(command="vip", description="Gestisci il VIP di un utente"),
    BotCommand(command="pending", description="Invii in attesa di moderazione"),
    BotCommand(command="broadcast", description="Invia un messaggio a tutti (in risposta)"),
]

PREVIEW_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✅ Applica", callback_data="rx:ok"),
    InlineKeyboardButton(text="❌ Annulla", callback_data="rx:no"),
]])
BROADCAST_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✅ Invia", callback_data="bc:ok"),
    InlineKeyboardButton(text="❌ Annulla", callback_data="bc:no"),
]])

BROADCAST_RATE_DELAY = 0.04  # ~25 messaggi/s
UPLOAD_EDIT_EVERY = 10
_tasks: set[asyncio.Task] = set()  # riferimenti, altrimenti il GC può cancellare i task


# ── utilità ─────────────────────────────────────────────────────────────────


async def _edit(msg: Message | None, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """edit_text che non solleva (messaggio uguale, cancellato, troppo vecchio…)."""
    if msg is None:
        return
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramAPIError as e:
        log.debug("edit_text ignorato: %s", e)


def _owner_name(owner_id: int) -> str:
    user = db.get_user(owner_id)
    if user and user.username:
        return f"@{user.username}"
    return user.first_name if user and user.first_name else str(owner_id)


# ── /reindex ────────────────────────────────────────────────────────────────


async def _show_preview(msg: Message, preview: archive.Preview, admin_id: int) -> None:
    if preview.is_empty:
        archive.cancel_reindex(admin_id)
        await _edit(msg, T.REINDEX_NONE)
    else:
        await _edit(msg, T.reindex_preview(preview), PREVIEW_KB)


async def _run_reindex(bot: Bot, settings: Settings, chat_id: int, admin_id: int) -> None:
    msg = await bot.send_message(chat_id, T.REINDEX_START)

    async def progress(text: str) -> None:
        await _edit(msg, T.reindex_progress(text))

    try:
        preview = await archive.start_reindex(settings, admin_id, progress)
    except archive.ReindexBusy as e:
        await _edit(msg, T.reindex_busy(_owner_name(e.owner_id)))
        return
    await _show_preview(msg, preview, admin_id)


@router.message(Command("reindex"))
async def cmd_reindex(message: Message, bot: Bot, settings: Settings) -> None:
    await _run_reindex(bot, settings, message.chat.id, message.from_user.id)


@router.callback_query(F.data == "rx:start")
async def cb_reindex_start(call: CallbackQuery, bot: Bot, settings: Settings) -> None:
    await call.answer()
    await _run_reindex(bot, settings, call.from_user.id, call.from_user.id)


@router.callback_query(F.data == "rx:ok")
async def cb_reindex_apply(call: CallbackQuery, bot: Bot, settings: Settings) -> None:
    await call.answer()
    msg, admin_id = call.message, call.from_user.id
    await _edit(msg, T.REINDEX_APPLYING)
    try:
        result = await archive.apply_reindex(admin_id)
    except archive.PreviewExpired:
        await _edit(msg, T.REINDEX_EXPIRED)
        return
    except archive.ReindexBusy as e:   # anteprima vecchia, il lock ora è di un altro admin
        await _edit(msg, T.reindex_busy(_owner_name(e.owner_id)))
        return
    except archive.DiskChanged as e:
        await _show_preview(msg, e.preview, admin_id)
        return
    base = T.reindex_done(result)
    await _edit(msg, base)
    if result.to_upload:
        await _upload_with_progress(bot, settings, msg, base)


async def _upload_with_progress(bot: Bot, settings: Settings, msg: Message | None, base: str) -> None:
    last = 0

    async def progress(done: int, total: int) -> None:
        nonlocal last
        if done >= total or done - last >= UPLOAD_EDIT_EVERY:
            last = done
            await _edit(msg, T.upload_progress(base, done, total))

    task = storage.resume_background_upload(bot, settings, progress)
    if task is not None:
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


@router.callback_query(F.data == "rx:no")
async def cb_reindex_cancel(call: CallbackQuery) -> None:
    await call.answer()
    archive.cancel_reindex(call.from_user.id)
    await _edit(call.message, T.REINDEX_CANCELLED)


async def notify_empty_index(bot: Bot, settings: Settings) -> None:
    """Primo avvio: nodes vuota → ricorda agli admin di lanciare /reindex."""
    if stats.nodes_count() > 0:
        return
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, T.EMPTY_INDEX)
        except TelegramAPIError as e:
            log.warning("notify_empty_index %s: %s", admin_id, e)


# ── /stats ──────────────────────────────────────────────────────────────────


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    o = stats.overview()
    o["pending"] = inbox.count_pending()
    top = []
    for node_id, n in stats.top_files(10):
        node = archive.tree.get(node_id) if archive.tree else None
        top.append((node.name if node else f"(file #{node_id})", n))
    await message.answer(T.stats(o, top))


# ── /crediti_add, /vip ──────────────────────────────────────────────────────


def _resolve(ref: str) -> int | str | None:
    """id utente, oppure il messaggio d'errore da mostrare."""
    uid = db.find_user(ref)
    if uid == "ambiguous":
        return T.USER_AMBIGUOUS
    if uid is None or db.get_user(uid) is None:
        return T.USER_NOT_FOUND
    return uid


CREDITS_MAX_DELTA = 1_000_000


@router.message(Command("crediti_add"))
async def cmd_credits_add(message: Message, command: CommandObject, bot: Bot) -> None:
    parts = (command.args or "").split(maxsplit=2)
    try:
        delta = int(parts[1])
    except (IndexError, ValueError):
        delta = 0
    if len(parts) < 2 or delta == 0:
        await message.answer(T.CREDITS_USAGE)
        return
    if abs(delta) > CREDITS_MAX_DELTA:
        await message.answer(T.credits_too_big(CREDITS_MAX_DELTA))
        return
    uid = _resolve(parts[0])
    if isinstance(uid, str):
        await message.answer(uid)
        return
    motivo = parts[2].strip() if len(parts) > 2 else "manuale"
    if not db.add_credits(uid, delta, f"admin:{message.from_user.id}:{motivo}"):
        await message.answer(T.credits_insufficient(delta))
        return
    balance = db.get_user(uid).credits
    await message.answer(T.credits_done(uid, delta, balance))
    try:
        await bot.send_message(uid, T.credits_notify(delta, balance))
    except TelegramAPIError:
        pass  # best effort


@router.message(Command("vip"))
async def cmd_vip(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer(T.VIP_USAGE)
        return
    what = parts[1].lower()
    if what == "off":
        days = None
    elif what.isdigit():
        days = int(what)
    else:
        await message.answer(T.VIP_USAGE)
        return
    uid = _resolve(parts[0])
    if isinstance(uid, str):
        await message.answer(uid)
        return
    if days is None:
        db.revoke_vip(uid)
        await message.answer(T.vip_revoked(uid))
    else:
        await message.answer(T.vip_granted(uid, db.grant_vip(uid, days)))


# ── /pending ────────────────────────────────────────────────────────────────


def staff_link(staff_chat_id: int, message_id: int) -> str:
    cid = str(staff_chat_id)
    cid = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return f"https://t.me/c/{cid}/{message_id}"


@router.message(Command("pending"))
async def cmd_pending(message: Message, settings: Settings) -> None:
    rows = inbox.list_pending(50)
    if not rows:
        await message.answer(T.PENDING_NONE)
        return
    items = [(name, staff_link(settings.staff_chat_id, mid)) for _sid, mid, name in rows]
    await message.answer(T.pending_list(items, inbox.count_pending() or len(rows)))


# ── /broadcast ──────────────────────────────────────────────────────────────


@dataclass
class BroadcastResult:
    sent: int = 0
    blocked: int = 0
    errors: int = 0


_broadcast_task: asyncio.Task | None = None
_broadcast_pending: dict[int, tuple[int, int]] = {}  # admin_id → (chat_id, message_id)


async def run_broadcast(bot: Bot, recipients: list[int], from_chat_id: int, message_id: int,
                        notify=None, *, sleep=asyncio.sleep,
                        delay: float = BROADCAST_RATE_DELAY) -> BroadcastResult:
    """Copia il messaggio a ogni destinatario, ~25/s. Mai cancella utenti."""
    res = BroadcastResult()
    total = len(recipients)
    for i, uid in enumerate(recipients, 1):
        for _attempt in range(5):
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=message_id)
                res.sent += 1
            except TelegramRetryAfter as e:
                await sleep(e.retry_after)
                continue  # stesso utente
            except TelegramForbiddenError:
                db.set_blocked(uid, True)
                res.blocked += 1
            except Exception as e:  # rete, chat non trovata, … : si prosegue
                log.warning("broadcast %s: %s", uid, e)
                res.errors += 1
            break
        else:
            res.errors += 1  # troppi RetryAfter di fila
        if notify and i % 100 == 0 and i < total:
            await notify(T.broadcast_progress(i, total, res.blocked))
        await sleep(delay)
    if notify:
        await notify(T.broadcast_summary(res.sent, res.blocked, res.errors))
    return res


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot) -> None:
    src = message.reply_to_message
    if src is None:
        await message.answer(T.BROADCAST_USAGE)
        return
    await bot.copy_message(chat_id=message.chat.id, from_chat_id=src.chat.id, message_id=src.message_id)
    _broadcast_pending[message.from_user.id] = (src.chat.id, src.message_id)
    await message.answer(T.broadcast_confirm(len(stats.broadcast_recipients())), reply_markup=BROADCAST_KB)


@router.callback_query(F.data == "bc:ok")
async def cb_broadcast_ok(call: CallbackQuery, bot: Bot) -> None:
    global _broadcast_task
    if _broadcast_task is not None and not _broadcast_task.done():
        await call.answer(T.BROADCAST_BUSY, show_alert=True)
        return
    src = _broadcast_pending.pop(call.from_user.id, None)
    if src is None:
        await call.answer(T.BROADCAST_EXPIRED, show_alert=True)
        return
    msg = call.message

    async def notify(text: str) -> None:
        await _edit(msg, text)

    async def go() -> BroadcastResult:
        await _edit(msg, T.BROADCAST_STARTED)
        return await run_broadcast(bot, stats.broadcast_recipients(), src[0], src[1], notify)

    # il task si crea prima di qualunque await: un secondo click lo vede già in corso
    _broadcast_task = asyncio.create_task(go())
    await call.answer()


@router.callback_query(F.data == "bc:no")
async def cb_broadcast_no(call: CallbackQuery) -> None:
    await call.answer()
    _broadcast_pending.pop(call.from_user.id, None)
    await _edit(call.message, T.BROADCAST_CANCELLED)
