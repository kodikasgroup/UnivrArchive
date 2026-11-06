"""Configurazione dal solo ambiente (vedi .env.example)."""
import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("BOT_TOKEN", "ADMIN_IDS", "STAFF_CHAT_ID", "STORAGE_CHAT_ID")


@dataclass(frozen=True)
class Settings:
    token: str
    admin_ids: frozenset[int]
    staff_chat_id: int
    storage_chat_id: int
    log_chat_id: int | None
    bot_api_url: str
    data_dir: Path
    price_max: int = 50
    submit_max_mb: int = 200
    submit_per_day: int = 10
    donation_link: str = ""
    rich_messages: bool = False
    log_level: str = "INFO"

    # percorsi derivati: un solo valore da configurare (DATA_DIR)
    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.db"

    @property
    def bot_api_dir(self) -> Path:
        return Path(os.environ.get("BOT_API_DIR") or "/var/lib/telegram-bot-api")


def _int(env: dict, key: str, default: int | None = None) -> int | None:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Valore non valido per {key}: {raw!r} (serve un numero intero)")


def load() -> Settings:
    env = os.environ
    if missing := [k for k in REQUIRED if not (env.get(k) or "").strip()]:
        raise SystemExit(f"Configurazione incompleta, mancano: {', '.join(missing)} "
                         f"(vedi .env.example)")
    admins = []
    for part in env["ADMIN_IDS"].split(","):
        if part.strip():
            try:
                admins.append(int(part))
            except ValueError:
                raise SystemExit(f"Valore non valido per ADMIN_IDS: {part.strip()!r} "
                                 f"(servono ID numerici separati da virgola)")
    if not admins:
        raise SystemExit("Configurazione incompleta, mancano: ADMIN_IDS (vedi .env.example)")
    return Settings(
        token=env["BOT_TOKEN"].strip(),
        admin_ids=frozenset(admins),
        staff_chat_id=_int(env, "STAFF_CHAT_ID"),
        storage_chat_id=_int(env, "STORAGE_CHAT_ID"),
        log_chat_id=_int(env, "LOG_CHAT_ID"),
        # in Docker non si toccano; senza Docker si sovrascrivono nell'ambiente
        bot_api_url=env.get("BOT_API_URL") or "http://telegram-bot-api:8081",
        data_dir=Path(env.get("DATA_DIR") or "/data"),
        price_max=_int(env, "PRICE_MAX", 50),
        submit_max_mb=_int(env, "SUBMIT_MAX_MB", 200),
        submit_per_day=_int(env, "SUBMIT_PER_DAY", 10),
        donation_link=(env.get("DONATION_LINK") or "").strip(),
        rich_messages=(env.get("RICH_MESSAGES") or "").strip() == "1",
        log_level=(env.get("LOG_LEVEL") or "INFO").strip().upper(),
    )
