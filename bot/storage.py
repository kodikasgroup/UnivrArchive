"""Canale storage: ogni contenuto (sha256) caricato una sola volta, consegna da file_id.

Regola: il percorso utente (send_file) NON legge mai il disco. Se un file non è ancora
nel canale, la richiesta va in testa alla coda del caricamento in background (l'unico
punto che legge l'archivio su disco) e il file parte all'utente appena caricato."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
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


# Dimensione massima inviabile: 50 MB col server di Telegram, 2 GB col server locale.
# Impostata all'avvio da configure(); None = nessun limite (test).
MAX_SEND_BYTES: int | None = None
LOCAL_API: bool = True  # server Bot API locale in uso


def configure(settings: Settings) -> None:
    global MAX_SEND_BYTES, LOCAL_API
    MAX_SEND_BYTES = settings.max_send_bytes
    LOCAL_API = settings.local_api


def too_large(node: Node) -> bool:
    """Il file supera il limite del server Bot API in uso: visibile ma non inviabile."""
    return MAX_SEND_BYTES is not None and not node.is_dir and (node.size or 0) > MAX_SEND_BYTES


class TooLarge(Exception):
    """File oltre il limite del server Bot API in uso (serve il server locale)."""


class NotReady(Exception):
    """Il file non è ancora nel canale: è in testa alla coda e partirà appena caricato."""


@dataclass
class _Waiting:
    """Un utente che aspetta un file in preparazione."""
    chat_id: int
    caption: str
    reply_markup: InlineKeyboardMarkup | None
    protect: bool
    extra: dict
    on_sent: Callable[[], None] | None


@dataclass
class _Job:
    """Caricamento prioritario: path su disco, file_id fallito (se c'era), chi aspetta."""
    path: str
    failed_file_id: str | None
    waiting: list[_Waiting]


_locks: dict[str, asyncio.Lock] = {}
_priority: dict[str, _Job] = {}  # sha256 -> job, in ordine di richiesta
_background: asyncio.Task | None = None
_progress: Callable[[int, int], Awaitable[None]] | None = None  # avanzamento del task in corso


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
    on_sent: Callable[[], None] | None = None,
) -> Message:
    """Invia da file_id o copiando dal canale. Mai forward, mai la didascalia del canale,
    mai letture dal disco. Se il file non è ancora nel canale solleva NotReady: la
    richiesta resta in coda e il file parte da solo appena caricato; `on_sent` viene
    chiamata in quel momento (es. per contare il download)."""
    if not node.sha256:
        raise ValueError("send_file: il nodo non ha sha256")
    if too_large(node):
        raise TooLarge(node.path)
    blob = db_nodes.get_blob(node.sha256)
    extra = {"message_effect_id": message_effect_id} if message_effect_id else {}
    waiting = _Waiting(chat_id, caption, reply_markup, protect, extra, on_sent)
    if blob is not None and not blob.file_id and blob.storage_message_id:
        # nel canale ma senza file_id (es. token nuovo): copia dal canale
        return await _copy_from_channel(bot, settings, chat_id, node, blob, caption, reply_markup, protect, extra)
    if blob is None or not blob.file_id:
        _enqueue(bot, settings, node, None, waiting)
        raise NotReady(node.path)
    try:
        return await bot.send_document(
            chat_id, blob.file_id, caption=caption, reply_markup=reply_markup, protect_content=protect, **extra
        )
    except TelegramBadRequest as e:
        if not _is_bad_file_id(e):
            raise
        log.warning("file_id non valido per %s, recupero", node.sha256[:12])
    if blob.storage_message_id:
        return await _copy_from_channel(bot, settings, chat_id, node, blob, caption, reply_markup, protect, extra)
    # né file_id valido né copia nel canale: ricaricamento in coda prioritaria
    _enqueue(bot, settings, node, blob.file_id, waiting)
    raise NotReady(node.path)


def _enqueue(bot: Bot, settings: Settings, node: Node, failed_file_id: str | None,
             waiting: _Waiting | None) -> None:
    """Mette il file in testa al caricamento in background e lo avvia se è fermo."""
    job = _priority.get(node.sha256)
    if job is None:
        job = _priority[node.sha256] = _Job(node.path, failed_file_id, [])
    elif failed_file_id and not job.failed_file_id:
        job.failed_file_id = failed_file_id
    if waiting is not None:
        job.waiting.append(waiting)
    resume_background_upload(bot, settings)


async def _copy_from_channel(
    bot: Bot, settings: Settings, chat_id: int, node: Node, blob: Blob,
    caption: str, reply_markup: InlineKeyboardMarkup | None, protect: bool, extra: dict,
) -> Message:
    """copy_message dal canale con la NOSTRA didascalia e ricava un file_id nuovo."""
    copied = await bot.copy_message(
        chat_id, settings.storage_chat_id, blob.storage_message_id,
        caption=caption, protect_content=protect, **extra,
    )
    msg: Message | None = None
    if reply_markup is not None:
        # copyMessage restituisce solo il message_id: aggiungere la tastiera dopo restituisce il
        # messaggio completo, e con lui il file_id valido per questo bot
        try:
            edited = await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=copied.message_id, reply_markup=reply_markup
            )
        except TelegramBadRequest:
            log.warning("tastiera non aggiunta alla copia di %s", node.sha256[:12])
            edited = None
        if isinstance(edited, Message):
            msg = edited
    doc = msg and (msg.document or msg.audio or msg.video or msg.animation or msg.voice)
    if doc:
        db_nodes.set_file_id(node.sha256, doc.file_id, doc.file_unique_id)
        return msg
    # file_id non ricavabile dalla copia: lo rinfresca il caricamento in background
    # (l'utente il file l'ha già ricevuto, nessuno aspetta)
    _enqueue(bot, settings, node, blob.file_id, None)
    return msg or Message(message_id=copied.message_id, date=datetime.now(timezone.utc), chat=Chat(id=chat_id, type="private"))


async def _reupload_path(bot: Bot, settings: Settings, sha256: str, path: str,
                         failed_file_id: str | None) -> Blob:
    """Ricarica dal disco (solo dal task in background) un contenuto il cui file_id non vale più."""
    lock = _locks.setdefault(sha256, asyncio.Lock())
    async with lock:
        # un'altra richiesta ha già rinfrescato il file_id mentre aspettavamo il lock?
        blob = db_nodes.get_blob(sha256)
        if blob and blob.file_id and blob.file_id != failed_file_id:
            return blob
        msg = await _channel_send(
            bot, settings.storage_chat_id, _disk_file(settings, path), _caption_for_channel(path, sha256),
        )
        return _save(sha256, msg)


def resume_background_upload(
    bot: Bot, settings: Settings, progress: Callable[[int, int], Awaitable[None]] | None = None
) -> asyncio.Task | None:
    """Carica i blob senza storage_message_id e le richieste prioritarie degli utenti.
    Un solo task alla volta; None se non c'è nulla da fare."""
    global _background, _progress
    if _background is not None and not _background.done():
        if progress is not None:  # l'ultimo che chiede riceve l'avanzamento
            _progress = progress
        return _background
    if not _priority and not db_nodes.blobs_to_upload(MAX_SEND_BYTES):
        return None
    _progress = progress
    _background = asyncio.get_running_loop().create_task(_run_background(bot, settings))
    return _background


async def _run_priority(bot: Bot, settings: Settings, sha: str, job: _Job) -> None:
    """Carica (o ricarica) un file richiesto da un utente e lo consegna a chi aspetta."""
    try:
        if job.failed_file_id:
            blob = await _reupload_path(bot, settings, sha, job.path, job.failed_file_id)
        else:
            blob = await _upload(bot, settings, sha, job.path)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("caricamento prioritario fallito: %s", job.path)
        return  # chi aspettava può ricliccare: la richiesta torna in coda
    for w in job.waiting:
        try:
            await bot.send_document(w.chat_id, blob.file_id, caption=w.caption,
                                    reply_markup=w.reply_markup, protect_content=w.protect, **w.extra)
        except TelegramAPIError:
            log.warning("consegna in attesa fallita: %s → %s", job.path, w.chat_id)
            continue
        if w.on_sent is not None:
            try:
                w.on_sent()
            except Exception:
                log.exception("on_sent fallita per %s", job.path)


async def _run_background(bot, settings) -> None:
    """Prima le richieste degli utenti (in ordine di arrivo), poi i blob mancanti.
    Rilegge la coda a ogni file: richieste nuove e blob aggiunti da un /reindex nel
    frattempo entrano subito; quelli falliti in questo giro si riprovano al prossimo avvio."""
    failed: set[tuple[str, str]] = set()
    done = 0
    last_send = 0.0
    log.info("canale storage: caricamento in background avviato (%d file da caricare, %d richiesti da utenti)",
             len(db_nodes.blobs_to_upload(MAX_SEND_BYTES)), len(_priority))

    async def pace() -> None:
        nonlocal last_send
        wait = UPLOAD_INTERVAL - (time.monotonic() - last_send)
        if wait > 0:
            await asyncio.sleep(wait)
        last_send = time.monotonic()

    while True:
        if _priority:
            sha = next(iter(_priority))
            await pace()
            job = _priority.pop(sha)  # tolto ora: chi chiede durante il caricamento crea un job nuovo
            log.info("canale storage: carico subito %s (richiesto da %d utenti)", job.path, len(job.waiting))
            await _run_priority(bot, settings, sha, job)
            continue
        todo = [t for t in db_nodes.blobs_to_upload(MAX_SEND_BYTES) if tuple(t) not in failed]
        if not todo:
            break
        sha, path = todo[0]
        blob = db_nodes.get_blob(sha)
        if not (blob and blob.storage_message_id):
            await pace()
            try:
                await _upload(bot, settings, sha, path)
            except FileNotFoundError:
                log.warning("file mancante su disco, salto: %s", path)
                failed.add((sha, path))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("upload fallito: %s", path)
                failed.add((sha, path))
        done += 1
        if done % 10 == 0:
            log.info("canale storage: caricati %d/%d", done, done + len(todo) - 1)
            if _progress:
                await _progress(done, done + len(todo) - 1)
    log.info("canale storage: caricamento finito (%d elaborati, %d falliti: si riprovano al prossimo avvio)",
             done, len(failed))
    if _progress and done % 10 != 0:
        await _progress(done, done)
