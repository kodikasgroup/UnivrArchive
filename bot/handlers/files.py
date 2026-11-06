"""Click sui file, acquisto Exclusive, azioni sui file, "scarica tutto"."""

import asyncio
import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    CopyTextButton,
    DisabledButton,
    EphemeralMessageParameters,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    SwitchInlineQueryChosenChat,
    User,
)

from bot import archive, db, keyboards, storage
from bot.config import Settings
from bot.db import content
from bot.texts import browse as T

log = logging.getLogger(__name__)

router = Router(name="files")
COMMANDS: list[BotCommand] = []
ADMIN_COMMANDS: list[BotCommand] = []

CONFIRM_OVER = 20          # sopra questi file "scarica tutto" chiede conferma
STATUS_EVERY = 10          # messaggio di stato ogni N file
SEND_INTERVAL = 1.0        # ~1 file/s (limite Telegram per chat)
EPHEMERAL_FALLBACK_TTL = 60

_active_downloads: dict[int, asyncio.Task] = {}   # un solo "scarica tutto" per utente
_reported: dict[tuple[int, int], float] = {}      # anti-spam segnalazioni
REPORT_COOLDOWN = 600


# --- filtro: nei gruppi si risponde solo se collegati ----------------------------


async def allowed_callback(q: CallbackQuery) -> bool:
    msg = q.message
    if msg is None or msg.chat.type == "private":
        return True
    return content.get_group_folder(msg.chat.id) is not None


router.callback_query.filter(allowed_callback)


# --- helper condivisi con browse e groups -----------------------------------------


def parse_ints(data: str) -> list[int] | None:
    """'buy:12' -> [12]; None se non numerico."""
    try:
        return [int(p) for p in data.split(":")[1:]]
    except ValueError:
        return None


def is_group_query(q: CallbackQuery) -> bool:
    return q.message is not None and q.message.chat.type != "private"


async def ensure_username(bot: Bot) -> str:
    if not keyboards.bot_username():
        keyboards.set_bot_username((await bot.me()).username or "")
    return keyboards.bot_username()


async def show_view(bot: Bot, q: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    """Sostituisce il contenuto del messaggio della callback (testo, didascalia o
    effimero). Messaggio non modificabile/troppo vecchio: ne manda uno nuovo."""
    msg = q.message
    if not isinstance(msg, Message):
        await bot.send_message(q.from_user.id, text, reply_markup=kb)
        return
    try:
        if msg.ephemeral_message_id is not None:
            await bot.edit_ephemeral_message_text(
                chat_id=msg.chat.id, receiver_user_id=q.from_user.id,
                ephemeral_message_id=msg.ephemeral_message_id, text=text, reply_markup=kb)
        elif msg.text is not None:
            await msg.edit_text(text, reply_markup=kb)
        else:
            await msg.edit_caption(caption=text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        if msg.ephemeral_message_id is not None:
            raise
        await bot.send_message(msg.chat.id, text, reply_markup=kb)


async def send_ephemeral(bot: Bot, chat_id: int, user_id: int, text: str,
                         reply_markup: InlineKeyboardMarkup | None = None,
                         callback_query_id: str | None = None) -> Message:
    """Messaggio visibile solo a `user_id` (Bot API 10.2+). Se l'API rifiuta,
    messaggio normale che si cancella da solo dopo 60 secondi."""
    try:
        return await bot.send_message(
            chat_id, text, reply_markup=reply_markup,
            ephemeral_message_parameters=EphemeralMessageParameters(
                receiver_user_id=user_id, callback_query_id=callback_query_id))
    except TelegramAPIError:
        log.warning("messaggio effimero non riuscito, uso il ripiego", exc_info=True)
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        task = asyncio.create_task(_delete_later(bot, chat_id, msg.message_id))
        task.add_done_callback(lambda _t: None)
        return msg


async def _delete_later(bot: Bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(EPHEMERAL_FALLBACK_TTL)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass


def node_crumb(node: archive.Node) -> list[str]:
    """Nomi delle cartelle che contengono il nodo (il nodo escluso)."""
    return [n.name for n in archive.tree.breadcrumb(node.id)[:-1]]


def file_keyboard(node: archive.Node) -> InlineKeyboardMarkup:
    paid = node.price > 0
    first: list[InlineKeyboardButton] = []
    if not paid:
        first.append(InlineKeyboardButton(
            text=T.BTN_SHARE,
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query=f"f:{node.id}", allow_user_chats=True, allow_group_chats=True,
                allow_bot_chats=False, allow_channel_chats=False)))
    if keyboards.bot_username():
        first.append(InlineKeyboardButton(
            text=T.BTN_LINK,
            copy_text=CopyTextButton(text=keyboards.deep_link("f", node.id))))
    rows = [first] if first else []
    rows.append([
        InlineKeyboardButton(text=T.BTN_SAVE, callback_data=f"fav:{node.id}"),
        InlineKeyboardButton(text=T.BTN_REPORT, callback_data=f"rep:{node.id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_view(node: archive.Node, balance: int) -> tuple[str, InlineKeyboardMarkup]:
    can_pay = balance >= node.price
    if can_pay:
        buy = InlineKeyboardButton(text=T.buy_button(node.price), callback_data=f"buy:{node.id}",
                                   style="success")
    else:  # solo estetica: buy: rifà comunque il controllo lato server
        buy = InlineKeyboardButton(text=T.buy_button(node.price), callback_data="noop",
                                   style="success", disabled=DisabledButton())
    cancel = InlineKeyboardButton(text=T.CANCEL, callback_data=f"n:{node.parent_id or 0}",
                                  style="danger")
    text = T.purchase_card(node.name, node.size, node.price, balance)
    return text, InlineKeyboardMarkup(inline_keyboard=[[buy], [cancel]])


def balance_of(user_id: int) -> int:
    user = db.get_user(user_id)
    return user.credits if user else 0


def owns(user_id: int, node: archive.Node) -> bool:
    return node.price <= 0 or db.is_vip(user_id) or content.has_purchase(user_id, node.id)


async def deliver(bot: Bot, settings: Settings, user_id: int, node: archive.Node, *,
                  effect: str | None = None) -> str:
    """Invia il file in privato a `user_id` e conta il download.
    Ritorna "ok", "forbidden" (l'utente non ha avviato il bot) o "error"."""
    await ensure_username(bot)
    paid = node.price > 0
    caption = T.file_caption(node.name, node_crumb(node), node.size, node.added_at,
                             exclusive=paid)
    try:
        await storage.send_file(bot, settings, user_id, node, caption=caption,
                                reply_markup=file_keyboard(node), protect=paid,
                                message_effect_id=effect)
    except TelegramForbiddenError:
        return "forbidden"
    except Exception:
        log.exception("invio file %s a %s fallito", node.id, user_id)
        try:
            await bot.send_message(user_id, T.SEND_ERROR)
        except TelegramAPIError:
            pass
        return "error"
    try:
        content.log_download(user_id, node.id)
    except Exception:
        log.exception("log_download fallito")
    return "ok"


async def group_hint(bot: Bot, q: CallbackQuery, node: archive.Node) -> None:
    """Nel gruppo: l'utente deve aprire il bot in privato (messaggio effimero)."""
    await ensure_username(bot)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=T.OPEN_PRIVATE_BUTTON, url=keyboards.deep_link("f", node.id))]])
    try:
        await send_ephemeral(bot, q.message.chat.id, q.from_user.id, T.OPEN_PRIVATE, kb,
                             callback_query_id=q.id)
    except TelegramAPIError:
        log.exception("hint in privato non inviato")


async def open_file(bot: Bot, settings: Settings, user: User, node: archive.Node, *,
                    q: CallbackQuery | None = None) -> None:
    """Click su un file (callback `n:<id>`) o deep link `f_<id>` (q=None).
    Risponde alla callback, se c'è."""
    await ensure_username(bot)
    if q is not None:
        await q.answer()
    in_group = q is not None and is_group_query(q)
    if not owns(user.id, node):
        if in_group:
            return await group_hint(bot, q, node)
        text, kb = purchase_view(node, balance_of(user.id))
        if q is not None:
            return await show_view(bot, q, text, kb)
        await bot.send_message(user.id, text, reply_markup=kb)
        return
    result = await deliver(bot, settings, user.id, node)
    if result == "forbidden" and in_group:
        await group_hint(bot, q, node)


# --- acquisto -----------------------------------------------------------------------


@router.callback_query(F.data.startswith("buy:"))
async def on_buy(q: CallbackQuery, bot: Bot, settings: Settings) -> None:
    ids = parse_ints(q.data)
    node = archive.tree.get(ids[0]) if ids and len(ids) == 1 else None
    if node is None or node.is_dir or node.price <= 0:
        await q.answer(T.FILE_GONE, show_alert=True)
        return
    if is_group_query(q):
        await q.answer()
        return await group_hint(bot, q, node)
    user_id = q.from_user.id
    if not owns(user_id, node):
        # prezzo e saldo riletti ADESSO, non quelli della scheda mostrata prima
        if not content.buy(user_id, node.id, node.price):
            await q.answer(T.NOT_ENOUGH, show_alert=True)
            text, kb = purchase_view(node, balance_of(user_id))
            await show_view(bot, q, text, kb)
            return
        await q.answer(T.BOUGHT)
        effect = T.EFFECT_PARTY
    else:
        await q.answer()
        effect = None
    await deliver(bot, settings, user_id, node, effect=effect)
    text, kb = keyboards.folder(node.parent_id, mode="browse",
                                is_admin=user_id in settings.admin_ids)
    await show_view(bot, q, text, kb)


# --- preferiti e segnalazioni ----------------------------------------------------------


@router.callback_query(F.data.startswith("fav:"))
async def on_fav(q: CallbackQuery) -> None:
    ids = parse_ints(q.data)
    node = archive.tree.get(ids[0]) if ids and len(ids) == 1 else None
    if node is None:
        await q.answer(T.FILE_GONE, show_alert=True)
        return
    added = content.toggle_favorite(q.from_user.id, node.id)
    await q.answer(T.FAV_ADDED if added else T.FAV_REMOVED)


@router.callback_query(F.data.startswith("rep:"))
async def on_report(q: CallbackQuery, bot: Bot, settings: Settings) -> None:
    parts = q.data.split(":")
    try:
        node_id = int(parts[1])
    except (IndexError, ValueError):
        await q.answer()
        return
    node = archive.tree.get(node_id)
    if node is None or node.is_dir:
        await q.answer(T.FILE_GONE, show_alert=True)
        return
    msg = q.message
    await ensure_username(bot)
    if len(parts) == 2:  # scelta del motivo
        await q.answer()
        rows = [[InlineKeyboardButton(text=label, callback_data=f"rep:{node_id}:{key}")]
                for key, label in T.REPORT_REASONS.items()]
        rows.append([InlineKeyboardButton(text=T.CANCEL, callback_data=f"rep:{node_id}:x")])
        if isinstance(msg, Message):
            await _edit_markup(msg, InlineKeyboardMarkup(inline_keyboard=rows))
        return
    reason = parts[2]
    if reason in T.REPORT_REASONS:
        key = (q.from_user.id, node_id)
        now = time.monotonic()
        if now - _reported.get(key, -REPORT_COOLDOWN) < REPORT_COOLDOWN:
            await q.answer(T.REPORT_ALREADY)
        else:
            from bot.handlers import tickets  # T4: import tardivo, evita cicli
            _reported[key] = now
            await tickets.open_ticket(bot, settings, q.from_user, "report",
                                      text=T.REPORT_REASONS[reason], node_id=node_id)
            await q.answer(T.REPORT_DONE)
    else:
        await q.answer()
    if isinstance(msg, Message):
        await _edit_markup(msg, file_keyboard(node))


async def _edit_markup(msg: Message, kb: InlineKeyboardMarkup) -> None:
    try:
        await msg.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


# --- scarica tutto ------------------------------------------------------------------------


@router.callback_query(F.data.startswith("all:"))
async def on_all(q: CallbackQuery, bot: Bot, settings: Settings) -> None:
    parts = q.data.split(":")
    try:
        node_id = int(parts[1])
    except (IndexError, ValueError):
        await q.answer()
        return
    confirmed = len(parts) > 2 and parts[2] == "ok"
    folder_node = archive.tree.get(node_id)
    files = archive.tree.free_files(node_id) if folder_node and folder_node.is_dir else []
    if not files:
        await q.answer(T.ALL_NONE, show_alert=True)
        return
    user_id = q.from_user.id
    task = _active_downloads.get(user_id)
    if task is not None and not task.done():
        await q.answer(T.ALL_BUSY)
        return
    if len(files) > CONFIRM_OVER and not confirmed:
        await q.answer()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=T.BTN_CONFIRM, callback_data=f"all:{node_id}:ok",
                                  style="success")],
            [InlineKeyboardButton(text=T.CANCEL, callback_data=f"n:{node_id}",
                                  style="danger")],
        ])
        await show_view(bot, q, T.all_confirm(len(files), sum(f.size for f in files)), kb)
        return
    await q.answer()
    await ensure_username(bot)
    _active_downloads[user_id] = asyncio.create_task(
        download_all(bot, settings, user_id, files))
    if confirmed:  # il messaggio di conferma torna a essere il menu
        text, kb = keyboards.folder(node_id, mode="browse",
                                    is_admin=user_id in settings.admin_ids
                                    and not is_group_query(q))
        await show_view(bot, q, text, kb)


async def download_all(bot: Bot, settings: Settings, user_id: int,
                       nodes: list[archive.Node]) -> None:
    """Invio in background, ~1 file/s, messaggio di stato ogni 10 file."""
    total = len(nodes)
    done = 0
    status: Message | None = None
    try:
        try:
            status = await bot.send_message(user_id, T.all_progress(0, total))
        except TelegramForbiddenError:
            return
        for i, node in enumerate(nodes, 1):
            sent = await _send_plain(bot, settings, user_id, node)
            if sent is None:  # l'utente ha bloccato il bot: inutile continuare
                break
            if sent:
                done += 1
            if i % STATUS_EVERY == 0 and i < total:
                await _safe_edit(status, T.all_progress(i, total))
            await asyncio.sleep(SEND_INTERVAL)
        await _safe_edit(status, T.all_done(done, total))
    except Exception:
        log.exception("scarica tutto fallito")
    finally:
        _active_downloads.pop(user_id, None)


async def _send_plain(bot: Bot, settings: Settings, user_id: int,
                      node: archive.Node) -> bool | None:
    """True inviato, False errore, None se l'utente ha bloccato il bot."""
    for attempt in range(2):
        try:
            await storage.send_file(bot, settings, user_id, node,
                                    caption=f"📖 {html.escape(node.name)}")
            content.log_download(user_id, node.id)
            return True
        except TelegramRetryAfter as e:
            if attempt:
                return False
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            return None
        except Exception:
            log.exception("invio %s fallito", node.id)
            return False
    return False


async def _safe_edit(msg: Message | None, text: str) -> None:
    if msg is None:
        return
    try:
        await msg.edit_text(text)
    except TelegramAPIError:
        pass
