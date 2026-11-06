"""Canale storage: ogni contenuto (sha256) caricato una sola volta, consegna da file_id."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Chat, FSInputFile, InlineKeyboardMarkup, Message

from bot.db import nodes as db_nodes

if TYPE_CHECKING:
    from bot.archive import Node
    from bot.config import Settings

log = logging.getLogger(__name__)

UPLOAD_INTERVAL = 3.0  # secondi tra due messaggi nel canale (20/minuto)
MAX_RETRIES = 3
_BAD_FILE_ID = ("wrong file identifier", "wrong remote file identifier", "file reference", "invalid file")


@dataclass(frozen=True)
class Blob:
    sha256: str
    file_id: str | None
    file_unique_id: str | None
    storage_message_id: int | None


_locks: dict[str, asyncio.Lock] = {}
_refresh_tried: set[str] = set()
_background: asyncio.Task | None = None


def remember_file_id(sha256: str, file_id: str, file_unique_id: str) -> None:
    """Per i file arrivati da Telegram: nessun upload da rifare."""
    db_nodes.set_file_id(sha256, file_id, file_unique_id)


def _is_bad_file_id(e: TelegramBadRequest) -> bool:
    msg = (e.message or "").lower()
    return any(k in msg for k in _BAD_FILE_ID)


def _caption_for_channel(path: str, sha256: str) -> str:
    tag = f"\n#{sha256[:12]}"
    return path[: 1024 - len(tag)] + tag


async def _channel_send(bot: Bot, chat_id: int, document, caption: str) -> Message:
    """send_document nel canale, con gestione di TelegramRetryAfter."""
    for attempt in range(MAX_RETRIES):
        try:
            return await bot.send_document(chat_id, document, caption=caption)
        except TelegramRetryAfter as e:
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(e.retry_after + 1)
    raise RuntimeError("unreachable")


async def _upload(bot: Bot, settings: Settings, sha256: str, path: str) -> Blob:
    """Carica nel canale (lock per sha256) se manca il messaggio nel canale."""
    lock = _locks.setdefault(sha256, asyncio.Lock())
    async with lock:
        blob = db_nodes.get_blob(sha256)
        if blob and blob.file_id and blob.storage_message_id:
            return blob
        caption = _caption_for_channel(path, sha256)
        if blob and blob.file_id:  # file_id arrivato da Telegram: nessun byte dal disco
            try:
                msg = await _channel_send(bot, settings.storage_chat_id, blob.file_id, caption)
            except TelegramBadRequest as e:
                if not _is_bad_file_id(e):
                    raise
                msg = None
            if msg is not None:
                return _save(sha256, msg)
        msg = await _channel_send(bot, settings.storage_chat_id, _disk_file(settings, path), caption)
        return _save(sha256, msg)


def _disk_file(settings: Settings, path: str) -> FSInputFile:
    full = Path(settings.archive_dir) / path
    if not full.is_file():
        raise FileNotFoundError(path)
    return FSInputFile(full)


def _save(sha256: str, msg: Message) -> Blob:
    doc = msg.document
    if doc is None:  # Telegram può riclassificare il media: prendiamo il primo disponibile
        doc = msg.audio or msg.video or msg.animation or msg.voice
    db_nodes.set_storage(sha256, doc.file_id, doc.file_unique_id, msg.message_id)
    return Blob(sha256, doc.file_id, doc.file_unique_id, msg.message_id)


async def ensure_uploaded(bot: Bot, settings: Settings, node: Node) -> Blob:
    if not node.sha256:
        raise ValueError("ensure_uploaded: il nodo non ha sha256")
    return await _upload(bot, settings, node.sha256, node.path)


async def send_file(
    bot: Bot,
    settings: Settings,
    chat_id: int,
    node: Node,
    *,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    protect: bool = False,
    message_effect_id: str | None = None,
) -> Message:
    """Invia da file_id. Mai forward, mai la didascalia del canale."""
    if not node.sha256:
        raise ValueError("send_file: il nodo non ha sha256")
    blob = db_nodes.get_blob(node.sha256)
    if blob is None or not blob.file_id:
        blob = await ensure_uploaded(bot, settings, node)
    extra = {"message_effect_id": message_effect_id} if message_effect_id else {}

    async def send(file_id: str) -> Message:
        return await bot.send_document(
            chat_id, file_id, caption=caption, reply_markup=reply_markup, protect_content=protect, **extra
        )

    try:
        return await send(blob.file_id)
    except TelegramBadRequest as e:
        if not _is_bad_file_id(e):
            raise
        log.warning("file_id non valido per %s, recupero", node.sha256[:12])
    if blob.storage_message_id:
        # copyMessage restituisce solo il message_id, non il file_id: lo rinfreschiamo in background
        copied = await bot.copy_message(
            chat_id, settings.storage_chat_id, blob.storage_message_id,
            caption=caption, reply_markup=reply_markup, protect_content=protect,
        )
        _schedule_refresh(bot, settings, node)
        return Message(message_id=copied.message_id, date=datetime.now(timezone.utc), chat=Chat(id=chat_id, type="private"))
    # niente copia nel canale: ricarica dal disco e riprova
    blob = await _reupload(bot, settings, node)
    return await send(blob.file_id)


async def _reupload(bot: Bot, settings: Settings, node: Node) -> Blob:
    lock = _locks.setdefault(node.sha256, asyncio.Lock())
    async with lock:
        msg = await _channel_send(
            bot, settings.storage_chat_id, _disk_file(settings, node.path),
            _caption_for_channel(node.path, node.sha256),
        )
        return _save(node.sha256, msg)


def _schedule_refresh(bot: Bot, settings: Settings, node: Node) -> None:
    """Ricava un file_id valido ricaricando dal disco (una volta per contenuto e per processo)."""
    if node.sha256 in _refresh_tried or not (Path(settings.archive_dir) / node.path).is_file():
        return
    _refresh_tried.add(node.sha256)

    async def run() -> None:
        try:
            await _reupload(bot, settings, node)
        except Exception:
            log.exception("refresh file_id fallito per %s", node.path)

    asyncio.get_running_loop().create_task(run())


def resume_background_upload(
    bot: Bot, settings: Settings, progress: Callable[[int, int], Awaitable[None]] | None = None
) -> asyncio.Task | None:
    """Carica i blob senza storage_message_id. Un solo task alla volta; None se non c'è nulla da fare."""
    global _background
    if _background is not None and not _background.done():
        return _background
    todo = db_nodes.blobs_to_upload()
    if not todo:
        return None
    _background = asyncio.get_running_loop().create_task(_run_background(bot, settings, todo, progress))
    return _background


async def _run_background(bot, settings, todo: list[tuple[str, str]], progress) -> None:
    total = len(todo)
    done = 0
    last_send = 0.0
    for sha, path in todo:
        blob = db_nodes.get_blob(sha)
        if blob and blob.storage_message_id:
            done += 1
            continue
        wait = UPLOAD_INTERVAL - (time.monotonic() - last_send)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await _upload(bot, settings, sha, path)
        except FileNotFoundError:
            log.warning("file mancante su disco, salto: %s", path)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("upload fallito: %s", path)
        last_send = time.monotonic()
        done += 1
        if progress and done % 10 == 0:
            await progress(done, total)
    if progress and done % 10 != 0:
        await progress(done, total)
