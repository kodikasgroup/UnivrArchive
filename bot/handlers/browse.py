"""Navigazione a bottoni, /start, deep link, ricerca, preferiti, recenti, novità."""

import asyncio
import base64
import binascii
import logging
import re
from collections.abc import Callable
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    ChosenInlineResult,
    FSInputFile,
    InlineQuery,
    InlineQueryResultCachedDocument,
    Message,
)

from bot import archive, db, keyboards
from bot.config import Settings
from bot.db import content
from bot.db import nodes as nodes_db
from bot.handlers import files
from bot.texts import browse as T

log = logging.getLogger(__name__)

router = Router(name="browse")
router.message.filter(F.chat.type == "private")   # nei gruppi ci pensa groups.py

COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Apri il menu"),
    BotCommand(command="cerca", description="Cerca un file o una cartella"),
    BotCommand(command="preferiti", description="I tuoi file salvati"),
    BotCommand(command="recenti", description="Gli ultimi file scaricati"),
    BotCommand(command="novita", description="Le novità degli ultimi 7 giorni"),
    BotCommand(command="crediti", description="I tuoi crediti"),
    BotCommand(command="help", description="Come funziona il bot"),
    BotCommand(command="privacy", description="Informativa privacy"),
]
ADMIN_COMMANDS: list[BotCommand] = []

LEGACY_COMMANDS = ("credits", "givecredits", "givevip", "sendmessage", "root", "remove",
                   "exclusive", "donation", "info")
INLINE_PAGE = 50
NEW_DAYS = 7

router.callback_query.filter(files.allowed_callback)


# --- funzioni pure (testate senza rete) ----------------------------------------------

_START_ARG = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SHARE_QUERY = re.compile(r"f:(\d+)")


def encode_search(query: str) -> str:
    """Testo di ricerca -> base64url senza '=' (per `?start=s_<...>`)."""
    return base64.urlsafe_b64encode(query.encode()).rstrip(b"=").decode()


def decode_search(token: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        text = raw.decode().strip()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return text or None


def parse_start_arg(arg: str | None) -> tuple[str, int | str] | None:
    """Parametro di `/start`: ('n', id) cartella, ('f', id) file, ('s', testo) ricerca.
    Qualsiasi altra cosa -> None (si apre la HOME)."""
    if not arg or not _START_ARG.fullmatch(arg):
        return None
    kind, _, rest = arg.partition("_")
    if kind in ("n", "f") and rest.isdigit():
        return kind, int(rest)
    if kind == "s" and rest:
        text = decode_search(rest)
        return ("s", text) if text else None
    return None


def is_free_file(node: archive.Node) -> bool:
    return not node.is_dir and node.price <= 0 and not node.is_exclusive


def inline_candidates(query: str, tree: archive.Tree) -> list[archive.Node]:
    """Solo file gratuiti: Exclusive e nascosti non compaiono mai, nemmeno con
    `f:<id>` scritto a mano."""
    query = query.strip()
    if (m := _SHARE_QUERY.fullmatch(query)):
        node = tree.get(int(m.group(1)))
        return [node] if node is not None and is_free_file(node) else []
    if not query:
        found = tree.new_files(NEW_DAYS)
    else:
        found = tree.search(query, 500, include_exclusive=False)
    return [n for n in found if is_free_file(n)]


def select_inline(query: str, tree: archive.Tree, offset: int,
                  file_id_of: Callable[[archive.Node], str | None],
                  limit: int = INLINE_PAGE) -> tuple[list[tuple[archive.Node, str]], str]:
    """Una pagina di risultati inline (solo con file_id noto) e il `next_offset`."""
    candidates = inline_candidates(query, tree)
    out: list[tuple[archive.Node, str]] = []
    i = max(offset, 0)
    while i < len(candidates) and len(out) < limit:
        file_id = file_id_of(candidates[i])
        if file_id:
            out.append((candidates[i], file_id))
        i += 1
    return out, (str(i) if i < len(candidates) else "")


def _file_id_of(node: archive.Node) -> str | None:
    blob = nodes_db.get_blob(node.sha256) if node.sha256 else None
    return blob.file_id if blob else None


def _help(settings: Settings) -> str:
    from bot.texts import common
    return common.help_text(settings.donation_link)


def _common_text(name: str, fallback: str, settings: Settings) -> str:
    from bot.texts import common
    text = getattr(common, name, fallback)
    return text.replace("{donation_link}", settings.donation_link or "")


# --- /start e HOME ---------------------------------------------------------------------


def _welcome_file(settings: Settings) -> Path | None:
    """Solo `welcome.*` (mp4, gif…): gli altri file di media/ (es. l'avatar) non sono il benvenuto."""
    media = Path(settings.media_dir)
    if not media.is_dir():
        return None
    found = sorted(p for p in media.iterdir() if p.is_file() and p.stem.lower() == "welcome")
    return found[0] if found else None


async def prepare_welcome(bot: Bot, settings: Settings) -> None:
    """All'avvio (mai durante un /start): se manca il file_id del media di benvenuto,
    lo carica nel canale storage e lo salva. È l'unico punto che legge media/."""
    if db.kv_get("welcome_media"):
        return
    path = _welcome_file(settings)
    if path is None:
        return
    try:
        msg = await bot.send_animation(settings.storage_chat_id, FSInputFile(path), caption="welcome")
    except TelegramAPIError:
        log.exception("media di benvenuto non caricato")
        return
    media = msg.animation or msg.document or msg.video
    if media is not None:
        db.kv_set("welcome_media", media.file_id)


async def send_welcome(bot: Bot, settings: Settings, chat_id: int, is_admin: bool) -> None:
    """Animazione + testo + menu HOME in un solo messaggio. Solo dal file_id salvato:
    nessuna lettura dal disco. Senza media (o file_id non valido) manda solo il testo."""
    text, kb = keyboards.folder(None, is_admin=is_admin)
    file_id = db.kv_get("welcome_media")
    if file_id:
        try:
            await bot.send_animation(chat_id, file_id, caption=text, reply_markup=kb)
            return
        except TelegramBadRequest:  # file_id di un altro bot o scaduto: si ricarica in background
            log.warning("welcome_media non valido, ricarico in background")
            db.kv_set("welcome_media", "")
            asyncio.get_running_loop().create_task(prepare_welcome(bot, settings))
    await bot.send_message(chat_id, text, reply_markup=kb)


async def _send_folder(bot: Bot, chat_id: int, node_id: int | None, is_admin: bool) -> None:
    text, kb = keyboards.folder(node_id, is_admin=is_admin)
    await bot.send_message(chat_id, text, reply_markup=kb)


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, bot: Bot,
                   settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    await files.ensure_username(bot)
    is_admin = user.id in settings.admin_ids
    target = parse_start_arg(command.args)
    tree = archive.tree
    if target is not None:
        kind, value = target
        if kind == "s":
            return await _send_search(bot, message.chat.id, str(value))
        node = tree.get(int(value))
        if node is not None and kind == "f" and not node.is_dir:
            return await files.open_file(bot, settings, user, node)
        if node is not None and node.is_dir:
            return await _send_folder(bot, message.chat.id, node.id, is_admin)
        if node is not None:  # n_<file>: si apre la cartella che lo contiene
            return await _send_folder(bot, message.chat.id, node.parent_id, is_admin)
    await send_welcome(bot, settings, message.chat.id, is_admin)


async def _show_folder(bot: Bot, q: CallbackQuery, settings: Settings, node_id: int | None) -> None:
    is_admin = q.from_user.id in settings.admin_ids and not files.is_group_query(q)
    text, kb = keyboards.folder(node_id, page=_page_of(q.data), is_admin=is_admin)
    await files.show_view(bot, q, text, kb)


def _page_of(data: str | None) -> int:
    parts = (data or "").split(":")
    try:
        return int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return 0


@router.callback_query(F.data.startswith("n:"))
async def on_node(q: CallbackQuery, bot: Bot, settings: Settings) -> None:
    try:
        node_id = int(q.data.split(":")[1])
    except (IndexError, ValueError):
        await q.answer()
        return
    await files.ensure_username(bot)
    if node_id == 0:
        await q.answer()
        return await _show_folder(bot, q, settings, None)
    node = archive.tree.get(node_id)
    if node is None:  # rimosso o spostato: si va al livello più vicino
        await q.answer(T.MOVED, show_alert=True)
        near = archive.tree.nearest_visible(node_id)
        return await _show_folder(bot, q, settings, near.id if near else None)
    if not node.is_dir:
        return await files.open_file(bot, settings, q.from_user, node, q=q)
    await q.answer()
    await _show_folder(bot, q, settings, node.id)


@router.callback_query(F.data == "noop")
async def on_noop(q: CallbackQuery) -> None:
    await q.answer()


# --- comandi semplici ---------------------------------------------------------------------


@router.message(Command("help"))
async def on_help(message: Message, settings: Settings) -> None:
    await message.answer(_help(settings))


@router.message(Command("privacy"))
async def on_privacy(message: Message, settings: Settings) -> None:
    await message.answer(_common_text("PRIVACY", T.NOT_FOUND, settings))


@router.message(Command(*LEGACY_COMMANDS))
async def on_legacy(message: Message, settings: Settings) -> None:
    await message.answer(_help(settings))


@router.message(Command("crediti"))
async def on_credits(message: Message) -> None:
    if message.from_user is None:
        return
    user = db.get_user(message.from_user.id)
    credits = user.credits if user else 0
    vip = db.is_vip(message.from_user.id)
    await message.answer(T.credits_text(credits, user.vip_until if user else None, vip))


# --- ricerca -------------------------------------------------------------------------------


async def _send_search(bot: Bot, chat_id: int, query: str) -> None:
    found = archive.tree.search(query, keyboards.LIST_LIMIT, include_exclusive=True)
    text, kb = keyboards.node_list(T.search_results(query, len(found)), found)
    await bot.send_message(chat_id, text, reply_markup=kb)


@router.message(Command("cerca"))
async def on_search(message: Message, command: CommandObject, bot: Bot) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer(T.SEARCH_USAGE)
        return
    await _send_search(bot, message.chat.id, query)


@router.inline_query()
async def on_inline(q: InlineQuery) -> None:
    try:
        offset = int(q.offset or 0)
    except ValueError:
        offset = 0
    picked, next_offset = select_inline(q.query, archive.tree, offset, _file_id_of)
    results = [
        InlineQueryResultCachedDocument(
            id=str(node.id), title=node.name, document_file_id=file_id,
            description=keyboards.short_crumb(node) or None)
        for node, file_id in picked
    ]
    await q.answer(results, cache_time=300, is_personal=False, next_offset=next_offset)


@router.chosen_inline_result()
async def on_chosen(r: ChosenInlineResult) -> None:
    try:
        node_id = int(r.result_id)
    except ValueError:
        return
    node = archive.tree.get(node_id)
    if node is None or not is_free_file(node):
        return
    try:
        content.log_download(r.from_user.id, node_id)
    except Exception:  # utente non registrato (FK): non è grave
        log.warning("log_download inline fallito", exc_info=True)


# --- preferiti, recenti, novità --------------------------------------------------------------


def _visible(ids: list[int]) -> list[archive.Node]:
    nodes = (archive.tree.get(i) for i in ids)
    return [n for n in nodes if n is not None]


@router.message(Command("preferiti"))
async def on_favorites(message: Message) -> None:
    nodes = _visible(content.list_favorites(message.from_user.id))
    title = T.FAV_TITLE if nodes else T.FAV_EMPTY
    text, kb = keyboards.node_list(title, nodes)
    await message.answer(text, reply_markup=kb)


@router.message(Command("recenti"))
async def on_recent(message: Message) -> None:
    nodes = _visible(content.recent_downloads(message.from_user.id, 10))
    title = T.RECENT_TITLE if nodes else T.RECENT_EMPTY
    text, kb = keyboards.node_list(title, nodes)
    await message.answer(text, reply_markup=kb)


def news_groups(nodes: list[archive.Node]) -> list[tuple[str, int]]:
    """(cartella, numero di file nuovi), in ordine alfabetico di cartella."""
    counts: dict[str, int] = {}
    for n in nodes:
        where = " › ".join(x.name for x in archive.tree.breadcrumb(n.id)[:-1]) or "HOME"
        counts[where] = counts.get(where, 0) + 1
    return sorted(counts.items())


@router.message(Command("novita"))
async def on_news(message: Message) -> None:
    nodes = [n for n in archive.tree.new_files(NEW_DAYS) if not n.is_dir]
    if not nodes:
        text, kb = keyboards.node_list(T.NEWS_EMPTY, [])
    else:
        nodes.sort(key=lambda n: (keyboards.short_crumb(n, 9), n.name))  # raggruppati per cartella
        text, kb = keyboards.node_list(T.news_body(news_groups(nodes)), nodes)
    await message.answer(text, reply_markup=kb)
