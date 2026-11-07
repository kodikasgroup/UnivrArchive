"""Avvio del bot: python -m bot"""
import asyncio
import importlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent

from bot import config, db
from bot.config import Settings
from bot.middlewares import UserMiddleware

log = logging.getLogger("bot")

# Ordine di registrazione: il primo router che matcha vince.
ROUTER_MODULES = ("admin", "manage", "tickets", "submit", "groups", "files", "browse")


def load_handler_modules() -> list:
    return [importlib.import_module(f"bot.handlers.{name}") for name in ROUTER_MODULES]


def build_commands(modules) -> tuple[list[BotCommand], list[BotCommand]]:
    """(comandi per tutti, comandi per gli admin = tutti + admin), senza doppioni."""
    def unique(cmds):
        seen, out = set(), []
        for c in cmds:
            if c.command not in seen:
                seen.add(c.command)
                out.append(c)
        return out
    default = unique(c for m in modules for c in m.COMMANDS)
    admin = unique(default + [c for m in modules for c in m.ADMIN_COMMANDS])
    return default, admin


async def on_error(event: ErrorEvent, bot: Bot, settings: Settings) -> bool:
    """Error handler globale: log con traceback, avviso breve in LOG_CHAT_ID, mai rilanciare."""
    log.error("Errore nell'update %s", event.update.update_id, exc_info=event.exception)
    if settings.log_chat_id:
        # solo tipo e id: niente testo dell'eccezione (potrebbe contenere token o dati del canale storage)
        text = f"⚠️ {type(event.exception).__name__} (update {event.update.update_id})"
        try:
            await bot.send_message(settings.log_chat_id, text[:3500], parse_mode=None)
        except Exception:
            log.exception("Invio dell'errore a LOG_CHAT_ID fallito")
    return True


def make_dispatcher(settings: Settings, modules) -> Dispatcher:
    dp = Dispatcher()
    dp["settings"] = settings
    dp.update.outer_middleware(UserMiddleware())
    dp.errors.register(on_error)
    for m in modules:
        dp.include_router(m.router)
    return dp


async def main() -> None:
    settings = config.load()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    for d in (settings.archive_dir, settings.inbox_dir, settings.trash_dir,
              settings.media_dir, settings.backups_dir):
        d.mkdir(parents=True, exist_ok=True)
    db.init(settings.db_path)

    # import tardivi: dipendono dal DB aperto e dagli altri moduli
    from bot import archive, jobs, storage
    archive.load_from_db()

    modules = load_handler_modules()
    defaults = DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True)
    if settings.local_api:  # file fino a 2 GB
        session = AiohttpSession(api=TelegramAPIServer.from_base(settings.bot_api_url, is_local=True))
        bot = Bot(settings.token, session=session, default=defaults)
    else:                   # server di Telegram: invio 50 MB, download 20 MB
        bot = Bot(settings.token, default=defaults)
    log.info("Server Bot API: %s", "locale" if settings.local_api else "Telegram (file oltre 50 MB bloccati)")
    storage.configure(settings)
    dp = make_dispatcher(settings, modules)

    default_cmds, admin_cmds = build_commands(modules)
    await bot.set_my_commands(default_cmds)
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:  # l'admin potrebbe non aver mai avviato il bot
            log.warning("Comandi admin non impostati per %s: %s", admin_id, type(e).__name__)

    jobs.start(bot, settings)
    storage.resume_background_upload(bot, settings)
    # il media di benvenuto si carica qui, una volta: /start usa solo il file_id
    from bot.handlers import browse
    asyncio.get_running_loop().create_task(browse.prepare_welcome(bot, settings))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
