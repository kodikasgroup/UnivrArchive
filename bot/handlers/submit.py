"""Invii degli utenti e moderazione nel gruppo staff."""

import asyncio
import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, ReactionTypeEmoji)

from bot import archive, db, keyboards, storage
from bot.db import inbox
from bot.filters import IsAdmin, IsPrivate
from bot.texts import inbox as T

if TYPE_CHECKING:
    from bot.config import Settings

log = logging.getLogger(__name__)
router = Router(name="submit")

COMMANDS: list[BotCommand] = []
ADMIN_COMMANDS: list[BotCommand] = []

ALLOWED_EXTENSIONS = frozenset(
    "pdf doc docx ppt pptx xls xlsx odt txt md zip c h java py png jpg".split()
)
ALBUM_WAIT = 2.0          # secondi di attesa per raccogliere un album
PICK_TIMEOUT = 600.0      # 10 minuti: poi "Non so"
MAX_NAME = 120
PARTY_EFFECT = "5046509860389126442"   # effetto messaggio 🎉
PRICE_CHOICES = (5, 10, 20)


# --- nomi e percorsi (sicurezza: file da sconosciuti) ------------------------------------

def sanitize_filename(name: str | None, fallback_ext: str = "") -> str:
    """Nome sicuro da scrivere su disco: mai separatori, '..', caratteri di
    controllo, max MAX_NAME caratteri, mai vuoto."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn"))
    name = re.sub(r'[:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    stem, ext = os.path.splitext(name)
    if len(ext) > 16:
        ext = ext[:16]
    stem = stem[: max(1, MAX_NAME - len(ext))].rstrip(" .")
    if not stem:
        stem = "file"
    if not ext and fallback_ext:
        ext = "." + fallback_ext.lstrip(".")
    return stem + ext


def with_price(price: int, name: str) -> str:
    return f"{price}.{name}"


_PRICE_PREFIX = re.compile(r"^\d+\.?")


def strip_price(raw_name: str) -> str:
    """Toglie il prefisso prezzo (`5.nome` o `10nome`) dal nome su disco."""
    rest = _PRICE_PREFIX.sub("", raw_name, count=1)
    return rest or raw_name


def unique_path(folder: Path, name: str) -> Path:
    """folder/name, oppure `nome (2).ext`, `nome (3).ext`… mai sovrascrivere."""
    candidate = folder / name
    if not (candidate.exists() or candidate.is_symlink()):
        return candidate
    stem, ext = os.path.splitext(name)
    i = 2
    while True:
        candidate = folder / f"{stem} ({i}){ext}"
        if not (candidate.exists() or candidate.is_symlink()):
            return candidate
        i += 1


def resolve_inside(base: Path, rel: str) -> Path | None:
    """base/rel risolto, solo se resta dentro base (None altrimenti)."""
    base_r = base.resolve()
    try:
        p = (base_r / rel).resolve()
    except (OSError, ValueError):
        return None
    return p if (p == base_r or p.is_relative_to(base_r)) else None


def is_exclusive_path(rel: str) -> bool:
    return rel.split("/", 1)[0] == archive.EXCLUSIVE


def display_path(rel: str) -> str:
    return " › ".join(p.replace("_", " ").replace("-", " ") for p in rel.split("/") if p)


def submit_limit_mb(settings: "Settings") -> int:
    """Limite degli invii: SUBMIT_MAX_MB, ma col server di Telegram il bot non scarica oltre 20 MB."""
    return min(settings.submit_max_mb, settings.max_download_bytes // (1024 * 1024))


async def _download_sha256(bot: Bot, file_path: str, dst: Path) -> str:
    """Scarica dal server di Telegram in `dst` e calcola lo sha256; niente copie parziali."""
    try:
        await bot.download_file(file_path, destination=dst, timeout=120)
        return await asyncio.to_thread(_sha256_file, dst)
    except BaseException:
        dst.unlink(missing_ok=True)
        raise


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _sha256_copy(src: Path, dst: Path) -> str:
    """Copia calcolando lo sha256; se fallisce non lascia una copia parziale."""
    h = hashlib.sha256()
    try:
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            while chunk := fin.read(1 << 20):
                h.update(chunk)
                fout.write(chunk)
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return h.hexdigest()


def local_source(settings: "Settings", file_path: str) -> Path:
    """Percorso locale (server Bot API locale) del file scaricato, solo dentro bot_api_dir."""
    p = Path(file_path)
    if not p.is_absolute():
        p = settings.bot_api_dir / p
    base = settings.bot_api_dir.resolve()
    p = p.resolve()
    if not p.is_relative_to(base):
        raise ValueError(f"percorso fuori da bot_api_dir: {file_path}")
    return p


# --- approvazione (sincrona: nessun await tra controllo e scrittura) --------

@dataclass(frozen=True)
class ApproveResult:
    status: str            # ok | already | no_folder | bad_folder | need_price | error
    dest_rel: str | None = None


def approve_submission(settings: "Settings", sub_id: int, admin_id: int, credits: int,
                       price: int | None = None) -> ApproveResult:
    """pending -> approved: sposta inbox -> archivio, assegna i crediti, UNA volta sola."""
    sub = inbox.get_submission(sub_id)
    if sub is None or sub.status != "pending":
        return ApproveResult("already")

    folder_rel = sub.dest_path
    if not folder_rel and sub.hint_node_id is not None:
        node = archive.tree.get(sub.hint_node_id)
        folder_rel = node.path if node and node.is_dir else None
    if not folder_rel:
        return ApproveResult("no_folder")

    archive_root = settings.archive_dir.resolve()
    folder_abs = resolve_inside(settings.archive_dir, folder_rel)
    if folder_abs is None or folder_abs == archive_root or not folder_abs.is_dir():
        return ApproveResult("bad_folder")

    exclusive = is_exclusive_path(folder_rel)
    if exclusive and (price is None or not 1 <= price <= settings.price_max):
        return ApproveResult("need_price")

    src = Path(sub.inbox_path) if sub.inbox_path else None
    if src is None or not src.is_file():
        log.error("invio %s: file in inbox mancante (%s)", sub_id, sub.inbox_path)
        return ApproveResult("error")

    name = sanitize_filename(sub.file_name)
    if exclusive:
        name = with_price(price, name)
    dest = unique_path(folder_abs, name)
    if resolve_inside(settings.archive_dir, dest.relative_to(archive_root).as_posix()) is None:
        return ApproveResult("bad_folder")

    if not inbox.claim_approval(sub_id, admin_id, credits):
        return ApproveResult("already")
    try:
        os.replace(src, dest)
    except OSError:
        log.exception("invio %s: spostamento inbox -> archivio fallito", sub_id)
        inbox.revert_claim(sub_id)
        return ApproveResult("error")

    rel = dest.relative_to(archive_root).as_posix()
    inbox.finalize_approval(sub_id, rel)
    if credits > 0:
        db.add_credits(sub.user_id, credits, f"submission:{sub_id}")
    log.info("invio %s approvato da %s: +%s crediti -> %s", sub_id, admin_id, credits, rel)
    return ApproveResult("ok", rel)


# --- scheda staff ------------------------------------------------------------

def _admin_label(user) -> str:
    return T.user_label(user.username, user.first_name, user.id)


def render_card(sub: inbox.Submission, chosen: bool = False) -> str:
    u = db.get_user(sub.user_id)
    label = T.user_label(u.username if u else None, u.first_name if u else None, sub.user_id)
    suggested = None
    if sub.hint_node_id is not None:
        node = archive.tree.get(sub.hint_node_id)
        suggested = display_path(node.path) if node else None
    chosen_txt = display_path(sub.dest_path) if (chosen and sub.dest_path) else None
    return T.card(sub.file_name, sub.size, label, sub.user_id, suggested, chosen_txt)


def card_markup(sub: inbox.Submission) -> InlineKeyboardMarkup:
    hint = sub.hint_node_id or 0
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T.SC_OK.format(n=n), callback_data=f"sub:{sub.id}:ok:{n}")
         for n in (5, 10, 20)],
        [InlineKeyboardButton(text=T.SC_CHANGE, callback_data=f"dsn:{sub.id}:{hint}"),
         InlineKeyboardButton(text=T.SC_REJECT, callback_data=f"sub:{sub.id}:no")],
    ])


def _reindex_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=T.SC_REINDEX, callback_data="rx:start")]])


def _price_markup(sub_id: int, credits: int, settings: "Settings") -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=f"{p} crediti", callback_data=f"sub:{sub_id}:ok:{credits}:{p}")
           for p in PRICE_CHOICES if p <= settings.price_max]
    return InlineKeyboardMarkup(inline_keyboard=[
        row, [InlineKeyboardButton(text=T.BACK_BTN, callback_data=f"sub:{sub_id}:back")]])


async def edit_message(msg: Message, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Edita testo o didascalia (le schede staff sono documenti)."""
    try:
        if msg.document is not None or msg.caption is not None:
            await msg.edit_caption(caption=text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


async def _react(bot: Bot, chat_id: int, message_id: int | None, emoji: str) -> None:
    if message_id is None:
        return
    try:
        await bot.set_message_reaction(chat_id, message_id, reaction=[ReactionTypeEmoji(emoji=emoji)])
    except TelegramAPIError:
        log.debug("reazione %s non impostata", emoji, exc_info=True)


async def _post_card(bot: Bot, settings: "Settings", sub: inbox.Submission) -> None:
    """Reazione 👀, documento + scheda nel gruppo staff (TelegramAPIError se fallisce)."""
    await _react(bot, sub.user_id, sub.user_message_id, "👀")
    sent = await bot.copy_message(
        settings.staff_chat_id, sub.user_id, sub.user_message_id,
        caption=render_card(sub), reply_markup=card_markup(sub))
    inbox.set_staff_message(sub.id, sent.message_id)


async def dispatch_to_staff(bot: Bot, settings: "Settings", sub_ids: list[int],
                            hint_node_id: int | None) -> None:
    """Passi 6-7: suggerimento salvato, reazione 👀, documento + scheda nel gruppo staff.
    Se la scheda non parte, l'invio resta orfano e lo riprende recover_orphans."""
    for sub_id in sub_ids:
        inbox.set_hint(sub_id, hint_node_id)
        sub = inbox.get_submission(sub_id)
        if sub is None or sub.status != "pending":
            continue
        try:
            await _post_card(bot, settings, sub)
        except TelegramAPIError:
            log.exception("invio %s: scheda staff non pubblicata", sub_id)


async def recover_orphans(bot: Bot, settings: "Settings") -> tuple[int, int]:
    """Invii pending senza scheda staff (scelta cartella persa al riavvio o scheda
    fallita): pubblicati con suggerimento "Non so" (o quello già scelto), oppure
    scartati se il messaggio dell'utente o il file in inbox non ci sono più.
    Ritorna (pubblicati, scartati). Lo chiamano jobs all'avvio e ogni notte."""
    live = {i for sess in _picks.values() for i in sess.sub_ids}
    live |= {i for ids in _admin_by_ctx.values() for i in ids}
    sent = dropped = 0
    for sub in inbox.orphaned_pending():
        if sub.id in live:
            continue
        if sub.user_message_id is None or not (sub.inbox_path and Path(sub.inbox_path).is_file()):
            inbox.reject_orphan(sub.id)
            dropped += 1
            continue
        try:
            await _post_card(bot, settings, sub)
        except TelegramBadRequest as e:
            if "not found" not in str(e).lower():
                log.warning("invio orfano %s: scheda non pubblicata (%s)", sub.id, e)
                continue
            inbox.reject_orphan(sub.id)      # messaggio dell'utente cancellato
            dropped += 1
        except TelegramAPIError as e:
            log.warning("invio orfano %s: scheda non pubblicata (%s), si riprova", sub.id, e)
        else:
            sent += 1
    if sent or dropped:
        log.info("invii orfani: %d pubblicati, %d scartati", sent, dropped)
    return sent, dropped


# --- ricezione --------------------------------------------------------------

@dataclass
class Outcome:
    sub_id: int | None = None
    text: str | None = None


@dataclass
class _Album:
    inflight: int = 0
    outcomes: list = None

    def __post_init__(self) -> None:
        self.outcomes = []


@dataclass
class PickSession:
    user_id: int
    sub_ids: list[int]
    task: asyncio.Task | None = None


_albums: dict[tuple[int, str], _Album] = {}
_picks: dict[tuple[int, int], PickSession] = {}          # (chat_id, message_id)
_admin_msgs: dict[tuple[int, int], int] = {}              # (chat, msg) del pannello admin -> ctx
_admin_by_ctx: dict[int, list[int]] = {}                  # primo id -> tutti gli id dell'album admin


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lstrip(".").lower()


async def ingest(bot: Bot, settings: "Settings", message: Message, is_admin: bool) -> Outcome:
    """Passi 1-4: controlli, dedup veloce, download in inbox, dedup vero."""
    doc = message.document
    user = message.from_user
    name = doc.file_name or ""
    ext = _ext(name)
    if not name:
        return Outcome(text=T.SEND_NO_NAME)
    if ext not in ALLOWED_EXTENSIONS:
        return Outcome(text=T.SEND_BAD_EXT.format(allowed=", ".join(sorted(ALLOWED_EXTENSIONS))))
    max_mb = submit_limit_mb(settings)
    if doc.file_size and doc.file_size > max_mb * 1024 * 1024:
        return Outcome(text=T.SEND_TOO_BIG.format(max_mb=max_mb))
    if not is_admin:
        n = inbox.count_recent_pending(user.id)
        if n >= settings.submit_per_day:
            return Outcome(text=T.SEND_RATE.format(n=n))
    if inbox.seen_unique_id(doc.file_unique_id):
        return Outcome(text=T.SEND_ALREADY)

    sub_id = inbox.create_submission(user.id, doc.file_id, doc.file_unique_id, name,
                                     doc.file_size, message.message_id)
    try:
        tg_file = await bot.get_file(doc.file_id)
        settings.inbox_dir.mkdir(parents=True, exist_ok=True)
        dst = settings.inbox_dir / f"{sub_id}.{ext}"
        if settings.local_api:  # il server locale l'ha già scaricato: si copia dal suo disco
            src = local_source(settings, tg_file.file_path)
            sha = await asyncio.to_thread(_sha256_copy, src, dst)
        else:                   # server di Telegram: download HTTP (max 20 MB)
            sha = await _download_sha256(bot, tg_file.file_path, dst)
    except Exception:
        log.exception("invio %s: download fallito", sub_id)
        inbox.delete_submission(sub_id)
        return Outcome(text=T.SEND_ERROR)
    inbox.set_file_info(sub_id, sha, str(dst))

    existing = archive.tree.find_by_sha256(sha)
    if existing:
        inbox.mark_duplicate(sub_id, existing[0].id)
        username = (await bot.me()).username
        link = f"https://t.me/{username}?start=f_{existing[0].id}"
        return Outcome(text=T.SEND_ALREADY_LINK.format(link=link))
    if inbox.find_pending_by_sha256(sha, sub_id) is not None:
        inbox.mark_duplicate(sub_id, None)
        return Outcome(text=T.SEND_ALREADY)
    return Outcome(sub_id=sub_id)


async def _finalize(bot: Bot, settings: "Settings", message: Message,
                    outcomes: list[Outcome], is_admin: bool) -> None:
    notes = [o.text for o in outcomes if o.text]
    accepted = [o.sub_id for o in outcomes if o.sub_id is not None]
    if notes:
        await message.answer("\n".join(notes))
    if not accepted:
        return
    if is_admin:
        ctx = accepted[0]
        _admin_by_ctx[ctx] = accepted
        text, kb = keyboards.folder(None, mode="staff", ctx=ctx, is_admin=True)
        sent = await message.answer(text, reply_markup=kb)
        _admin_msgs[(sent.chat.id, sent.message_id)] = ctx
        return
    text, kb = keyboards.folder(None, mode="pick")
    sent = await message.answer(f"{T.PICK_PROMPT}\n\n{text}", reply_markup=kb)
    key = (sent.chat.id, sent.message_id)
    session = PickSession(user_id=message.from_user.id, sub_ids=accepted)
    session.task = asyncio.create_task(_pick_timeout(bot, settings, key, sent))
    _picks[key] = session


async def _pick_timeout(bot: Bot, settings: "Settings", key: tuple[int, int], msg: Message) -> None:
    await asyncio.sleep(PICK_TIMEOUT)
    await _pick_finish(bot, settings, key, None, msg, from_timeout=True)


async def _pick_finish(bot: Bot, settings: "Settings", key: tuple[int, int],
                       hint: int | None, msg: Message | None, from_timeout: bool = False) -> None:
    session = _picks.pop(key, None)
    if session is None:
        return
    if session.task and not from_timeout:
        session.task.cancel()
    await dispatch_to_staff(bot, settings, session.sub_ids, hint)
    n = len(session.sub_ids)
    thanks = T.SEND_THANKS if n == 1 else T.SEND_THANKS_N.format(n=n)
    if msg is not None:
        try:
            await msg.edit_text(thanks, reply_markup=None)
        except TelegramAPIError:
            await bot.send_message(key[0], thanks)


@router.message(IsPrivate(), F.document)
async def on_document(message: Message, bot: Bot, settings: "Settings") -> None:
    if message.from_user is None:
        return
    is_admin = message.from_user.id in settings.admin_ids
    gid = message.media_group_id
    if gid is None:
        outcome = await ingest(bot, settings, message, is_admin)
        await _finalize(bot, settings, message, [outcome], is_admin)
        return

    key = (message.from_user.id, gid)
    album = _albums.get(key)
    leader = album is None
    if leader:
        album = _albums[key] = _Album()
    album.inflight += 1
    try:
        outcome = await ingest(bot, settings, message, is_admin)
    except Exception:
        log.exception("album: ingest fallito")
        outcome = Outcome(text=T.SEND_ERROR)
    finally:
        album.inflight -= 1
    album.outcomes.append(outcome)
    if not leader:
        return
    await asyncio.sleep(ALBUM_WAIT)
    while album.inflight:
        await asyncio.sleep(0.1)
    _albums.pop(key, None)
    await _finalize(bot, settings, message, album.outcomes, is_admin)


# --- scelta cartella dell'utente (pick:) --------------------------------------

@router.callback_query(F.data.regexp(r"^pick:\d+(:\d+|:ok)?$"))
async def cb_pick(callback: CallbackQuery, bot: Bot, settings: "Settings") -> None:
    msg = callback.message
    if not isinstance(msg, Message):
        await callback.answer()
        return
    key = (msg.chat.id, msg.message_id)
    session = _picks.get(key)
    if session is None:
        await callback.answer(T.PICK_EXPIRED, show_alert=True)
        return
    if callback.from_user.id != session.user_id:
        await callback.answer(T.PICK_NOT_YOURS, show_alert=True)
        return
    parts = callback.data.split(":")
    node_id = int(parts[1])
    node = archive.tree.get(node_id) if node_id else None
    if node_id and (node is None or node.is_exclusive or node.path.split("/")[0] == archive.EXCLUSIVE):
        await callback.answer(T.STAFF_BAD_FOLDER, show_alert=True)
        return
    if len(parts) > 2 and parts[2] == "ok":
        await callback.answer()
        await _pick_finish(bot, settings, key, node.id if node and node.is_dir else None, msg)
        return
    page = int(parts[2]) if len(parts) > 2 else 0
    text, kb = keyboards.folder(node.id if node else None, page, mode="pick")
    await callback.answer()
    await edit_message(msg, f"{T.PICK_PROMPT}\n\n{text}", kb)


# --- moderazione: navigazione cartella (dsn:/dst:) ---------------------------

def is_direct(sub: inbox.Submission, msg: object, user_id: int) -> bool:
    """Invio di un admin in privato (nessuna scheda staff, nessun credito)."""
    return (sub.staff_message_id is None and sub.user_id == user_id
            and isinstance(msg, Message) and msg.chat.type == "private")


def _is_direct(sub: inbox.Submission, callback: CallbackQuery) -> bool:
    return is_direct(sub, callback.message, callback.from_user.id)


def _chat_ok(sub: inbox.Submission, callback: CallbackQuery, settings: "Settings") -> bool:
    msg = callback.message
    if not isinstance(msg, Message):
        return False
    return _is_direct(sub, callback) or msg.chat.id == settings.staff_chat_id


@router.callback_query(IsAdmin(), F.data.regexp(r"^dsn:\d+:\d+(:\d+)?$"))
async def cb_dsn(callback: CallbackQuery, settings: "Settings") -> None:
    parts = callback.data.split(":")
    sub = inbox.get_submission(int(parts[1]))
    if sub is None or sub.status != "pending" or not _chat_ok(sub, callback, settings):
        await callback.answer(T.STAFF_ALREADY if sub else T.STAFF_WRONG_CHAT, show_alert=True)
        return
    node_id = int(parts[2])
    node = archive.tree.get(node_id) if node_id else None
    page = int(parts[3]) if len(parts) > 3 else 0
    text, kb = keyboards.folder(node.id if node else None, page, mode="staff", ctx=sub.id, is_admin=True)
    if not _is_direct(sub, callback):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            *kb.inline_keyboard,
            [InlineKeyboardButton(text=T.BACK_BTN, callback_data=f"sub:{sub.id}:back")]])
    await callback.answer()
    await edit_message(callback.message, text, kb)


@router.callback_query(IsAdmin(), F.data.regexp(r"^dst:\d+:\d+$"))
async def cb_dst(callback: CallbackQuery, bot: Bot, settings: "Settings") -> None:
    _, ctx, node_id = callback.data.split(":")
    sub = inbox.get_submission(int(ctx))
    if sub is None or sub.status != "pending":
        await callback.answer(T.STAFF_ALREADY, show_alert=True)
        return
    if not _chat_ok(sub, callback, settings):
        await callback.answer(T.STAFF_WRONG_CHAT, show_alert=True)
        return
    node = archive.tree.get(int(node_id)) if int(node_id) else None
    if node is None or not node.is_dir:
        await callback.answer(T.STAFF_BAD_FOLDER, show_alert=True)
        return
    toast = await set_destination(bot, settings, callback.message, callback.from_user.id,
                                  sub, node.path)
    await callback.answer(toast)


async def set_destination(bot: Bot, settings: "Settings", panel: Message, admin_id: int,
                          sub: inbox.Submission, folder_rel: str) -> str | None:
    """Imposta la cartella di destinazione (anche una appena creata con ➕).
    Moderazione: aggiorna la scheda. Invio dell'admin: salva subito.
    Ritorna il testo del toast."""
    direct = is_direct(sub, panel, admin_id)
    ids = _admin_by_ctx.get(sub.id, [sub.id]) if direct else [sub.id]
    for i in ids:
        inbox.set_dest_folder(i, folder_rel)
    if not direct:
        sub = inbox.get_submission(sub.id)
        await edit_message(panel, render_card(sub, chosen=True), card_markup(sub))
        return T.STAFF_DEST_SET
    if is_exclusive_path(folder_rel):
        await edit_message(panel, T.ADMIN_ASK_PRICE, _price_markup(sub.id, 0, settings))
        return None
    await _save_direct(bot, settings, panel, admin_id, ids, None)
    return None


async def _save_direct(bot: Bot, settings: "Settings", panel: Message, admin_id: int,
                       ids: list[int], price: int | None) -> None:
    lines = []
    for i in ids:
        res = approve_submission(settings, i, admin_id, 0, price)
        sub = inbox.get_submission(i)
        if res.status == "ok":
            if sub.sha256:
                storage.remember_file_id(sub.sha256, sub.file_id, sub.file_unique_id)
            lines.append(T.ADMIN_SAVED.format(path=res.dest_rel))
        else:
            lines.append(_error_text(res.status))
    await edit_message(panel, "\n".join(lines), _reindex_markup())


def _error_text(status: str) -> str:
    return {"already": T.STAFF_ALREADY, "no_folder": T.STAFF_NEED_FOLDER,
            "bad_folder": T.STAFF_BAD_FOLDER, "need_price": T.ADMIN_ASK_PRICE,
            "error": T.STAFF_MOVE_ERROR}.get(status, T.STAFF_MOVE_ERROR)


# --- moderazione: approva / rifiuta (sub:) -----------------------------------

@router.callback_query(IsAdmin(), F.data.regexp(r"^sub:\d+:back$"))
async def cb_back(callback: CallbackQuery, settings: "Settings") -> None:
    sub = inbox.get_submission(int(callback.data.split(":")[1]))
    if sub is None or sub.status != "pending" or not _chat_ok(sub, callback, settings):
        await callback.answer(T.STAFF_ALREADY, show_alert=True)
        return
    await callback.answer()
    await edit_message(callback.message, render_card(sub, chosen=bool(sub.dest_path)), card_markup(sub))


@router.callback_query(IsAdmin(), F.data.regexp(r"^sub:\d+:ok:\d+(:\d+)?$"))
async def cb_approve(callback: CallbackQuery, bot: Bot, settings: "Settings") -> None:
    parts = callback.data.split(":")
    sub_id, credits = int(parts[1]), int(parts[3])
    price = int(parts[4]) if len(parts) > 4 else None
    sub = inbox.get_submission(sub_id)
    if sub is None or sub.status != "pending":
        await callback.answer(T.STAFF_ALREADY, show_alert=True)
        return
    if not _chat_ok(sub, callback, settings):
        await callback.answer(T.STAFF_WRONG_CHAT, show_alert=True)
        return

    if _is_direct(sub, callback):
        if not sub.dest_path:
            await callback.answer(T.ADMIN_SESSION_LOST, show_alert=True)
            return
        await callback.answer()
        await _save_direct(bot, settings, callback.message, callback.from_user.id,
                           _admin_by_ctx.get(sub_id, [sub_id]), price)
        return

    base = render_card(sub, chosen=bool(sub.dest_path))
    res = approve_submission(settings, sub_id, callback.from_user.id, credits, price)
    if res.status == "need_price":
        await callback.answer()
        await edit_message(callback.message, f"{base}\n\n{T.SC_PRICE_ASK}",
                           _price_markup(sub_id, credits, settings))
        return
    if res.status != "ok":
        await callback.answer(_error_text(res.status), show_alert=True)
        return
    await callback.answer()

    if sub.sha256:
        storage.remember_file_id(sub.sha256, sub.file_id, sub.file_unique_id)
    await _react(bot, sub.user_id, sub.user_message_id, "👍")
    text = T.APPROVED_USER.format(name=T.escape(sub.file_name), credits=credits)
    try:
        await bot.send_message(sub.user_id, text, message_effect_id=PARTY_EFFECT)
    except TelegramBadRequest:
        await bot.send_message(sub.user_id, text)
    except TelegramAPIError:
        log.warning("utente %s non raggiungibile", sub.user_id)
    await edit_message(callback.message,
                       T.card_approved(base, _admin_label(callback.from_user), credits, res.dest_rel),
                       _reindex_markup())


@router.callback_query(IsAdmin(), F.data.regexp(r"^sub:\d+:no$"))
async def cb_reject_ask(callback: CallbackQuery, settings: "Settings") -> None:
    sub = inbox.get_submission(int(callback.data.split(":")[1]))
    if sub is None or sub.status != "pending" or not _chat_ok(sub, callback, settings):
        await callback.answer(T.STAFF_ALREADY, show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=label, callback_data=f"sub:{sub.id}:no:{code}")]
            for code, label in T.REJECT_LABELS.items()]
    rows.append([InlineKeyboardButton(text=T.BACK_BTN, callback_data=f"sub:{sub.id}:back")])
    await callback.answer(T.STAFF_REJECT_ASK)
    await edit_message(callback.message, render_card(sub, chosen=bool(sub.dest_path)),
                       InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(IsAdmin(), F.data.regexp(r"^sub:\d+:no:(dup|unreadable|offtopic|other)$"))
async def cb_reject(callback: CallbackQuery, bot: Bot, settings: "Settings") -> None:
    _, sub_id, _, code = callback.data.split(":")
    sub = inbox.get_submission(int(sub_id))
    if sub is None or sub.status != "pending" or not _chat_ok(sub, callback, settings):
        await callback.answer(T.STAFF_ALREADY, show_alert=True)
        return
    base = render_card(sub, chosen=bool(sub.dest_path))
    if not inbox.reject(sub.id, callback.from_user.id):
        await callback.answer(T.STAFF_ALREADY, show_alert=True)
        return
    await callback.answer()
    reason = T.REJECT_REASONS[code]
    await _react(bot, sub.user_id, sub.user_message_id, "👎")
    try:
        await bot.send_message(sub.user_id, T.REJECTED_USER.format(
            name=T.escape(sub.file_name), reason=reason))
    except TelegramAPIError:
        log.warning("utente %s non raggiungibile", sub.user_id)
    await edit_message(callback.message,
                       T.card_rejected(base, _admin_label(callback.from_user), T.REJECT_LABELS[code]),
                       None)


def context_for_message(msg: Message, settings: "Settings") -> int | None:
    """Id dell'invio a cui appartiene un messaggio di navigazione (scheda staff o
    pannello dell'admin in privato); None se non è legato a nessun invio."""
    ctx = _admin_msgs.get((msg.chat.id, msg.message_id))
    if ctx is not None:
        return ctx
    if msg.chat.id != settings.staff_chat_id:   # gli id dei messaggi sono per chat
        return None
    sub = inbox.get_by_staff_message(msg.message_id)
    return sub.id if sub and sub.status == "pending" else None
