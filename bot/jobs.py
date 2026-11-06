"""Task notturno (backup, pulizie, albero in RAM). Un solo task asyncio, alle 03:00 UTC."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot import archive, db
from bot.config import Settings
from bot.db import inbox, stats
from bot.handlers import admin
from bot.texts import admin as T

log = logging.getLogger(__name__)

RUN_HOUR_UTC = 3
FMT = "%Y-%m-%d %H:%M:%S"
BACKUPS_KEEP = 14
TRASH_DAYS = 30
INBOX_DAYS = 30
BOT_API_DAYS = 1
DOWNLOADS_DAYS = 365  # 12 mesi

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # UTC naive, come il DB


def seconds_until_next(now: datetime, hour: int = RUN_HOUR_UTC) -> float:
    nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def is_due(last: str | None, now: datetime) -> bool:
    if not last:
        return True
    try:
        return now - datetime.strptime(last, FMT) > timedelta(hours=24)
    except ValueError:
        return True


def _mtime(p: Path) -> datetime:
    return datetime.fromtimestamp(p.stat().st_mtime, UTC).replace(tzinfo=None)


# ── passi (funzioni sincrone: girano in thread) ─────────────────────────────


def backup_db(db_path: Path, backups_dir: Path, today: datetime, keep: int = BACKUPS_KEEP) -> None:
    """VACUUM INTO da una connessione dedicata (non tocca quella del bot), poi ruota."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"bot-{today:%Y-%m-%d}.db"
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(db_path)
    try:
        src.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        src.close()
    tmp.replace(target)
    old = sorted(backups_dir.glob("bot-????-??-??.db"))[:-keep]
    for f in old:
        f.unlink(missing_ok=True)


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)


def clean_trash(trash_dir: Path, now: datetime, days: int = TRASH_DAYS) -> int:
    """Cancella gli elementi di trash/ più vecchi di `days` (data nel nome, altrimenti mtime)."""
    if not trash_dir.is_dir():
        return 0
    limit = now - timedelta(days=days)
    n = 0
    for p in trash_dir.iterdir():
        try:
            when = datetime.strptime(p.name[:10], "%Y-%m-%d")
        except ValueError:
            when = _mtime(p)
        if when < limit:
            _remove(p)
            n += 1
    return n


def delete_inbox_files(paths: list[str], settings: Settings) -> int:
    """Cancella solo file che stanno davvero dentro inbox_dir."""
    root = Path(settings.inbox_dir).resolve()
    n = 0
    for raw in paths:
        p = Path(raw)
        for cand in (p,) if p.is_absolute() else (root / p, Path(settings.data_dir) / p):
            cand = cand.resolve()
            if cand.is_relative_to(root) and cand.is_file():
                cand.unlink(missing_ok=True)
                n += 1
                break
    return n


def clean_bot_api(bot_api_dir: Path, now: datetime, days: int = BOT_API_DAYS) -> int:
    """Solo i file sotto */documents/: il resto della cartella è stato del server."""
    if not bot_api_dir.is_dir():
        return 0
    limit = now - timedelta(days=days)
    n = 0
    for docs in bot_api_dir.glob("*/documents"):
        if not docs.is_dir():
            continue
        for f in docs.rglob("*"):
            if f.is_file() and not f.is_symlink() and _mtime(f) < limit:
                f.unlink(missing_ok=True)
                n += 1
    return n


# ── giro completo ───────────────────────────────────────────────────────────


async def run_nightly(bot: Bot, settings: Settings, now: Clock = utcnow) -> list[str]:
    """Esegue tutti i passi; ritorna i nomi di quelli falliti."""
    t = now()
    failures: list[str] = []

    async def step(name: str, fn: Callable[[], Awaitable[object]]) -> None:
        try:
            log.info("job notturno: %s → %s", name, await fn())
        except Exception:
            log.exception("job notturno: %s fallito", name)
            failures.append(name)

    async def s_backup():
        await asyncio.to_thread(backup_db, settings.db_path, settings.backups_dir, t)

    async def s_trash():
        return await asyncio.to_thread(clean_trash, settings.trash_dir, t)

    async def s_inbox():
        paths = inbox.expired_inbox_files(INBOX_DAYS)
        n = await asyncio.to_thread(delete_inbox_files, paths, settings)
        stale = inbox.stale_pending(INBOX_DAYS)
        if stale:
            await bot.send_message(settings.staff_chat_id, T.stale_pending(stale))
        return f"{n} file, {len(stale)} invii vecchi"

    async def s_bot_api():
        return await asyncio.to_thread(clean_bot_api, settings.bot_api_dir, t)

    async def s_downloads():
        cutoff = (t - timedelta(days=DOWNLOADS_DAYS)).strftime(FMT)
        return stats.purge_downloads_before(cutoff)

    async def s_tree():
        archive.load_from_db()

    async def s_mark():
        db.kv_set("nightly_last", t.strftime(FMT))

    await step("backup", s_backup)
    await step("cestino", s_trash)
    await step("inbox", s_inbox)
    await step("bot-api", s_bot_api)
    await step("download", s_downloads)
    await step("albero", s_tree)
    await step("kv", s_mark)

    if failures and settings.log_chat_id:
        try:
            await bot.send_message(settings.log_chat_id, T.nightly_failed(failures))
        except TelegramAPIError:
            log.exception("job notturno: avviso in LOG_CHAT_ID fallito")
    return failures


async def _loop(bot: Bot, settings: Settings, now: Clock, sleep) -> None:
    try:
        await admin.notify_empty_index(bot, settings)
    except Exception:
        log.exception("notify_empty_index fallito")
    if is_due(db.kv_get("nightly_last"), now()):
        await run_nightly(bot, settings, now)
    while True:
        await sleep(seconds_until_next(now()))
        await run_nightly(bot, settings, now)


def start(bot: Bot, settings: Settings, *, now: Clock = utcnow, sleep=asyncio.sleep) -> asyncio.Task:
    return asyncio.create_task(_loop(bot, settings, now, sleep), name="nightly-job")
