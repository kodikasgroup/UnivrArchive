"""Supporto ai test di invii e staff: stub dei moduli mancanti (se non presenti),
DB temporaneo, bot finto che registra le chiamate (nessuna rete)."""

import importlib
import sys
import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from aiogram import Bot
from aiogram.filters import Filter
from aiogram.methods import GetFile, GetMe
from aiogram.types import CallbackQuery, File, InlineKeyboardMarkup, Message, MessageId, User

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bot as bot_pkg  # noqa: E402


def _missing(name: str) -> bool:
    try:
        importlib.import_module(name)
        return False
    except ImportError:
        return True


def _install(name: str, mod: types.ModuleType) -> None:
    sys.modules[name] = mod
    setattr(bot_pkg, name.split(".")[1], mod)


# --- archivio finto -------------------------------------------------------------

@dataclass(frozen=True)
class FakeNode:
    id: int
    path: str
    is_dir: bool = True
    parent_id: int | None = None
    price: int = 0
    sha256: str | None = None

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1].replace("_", " ")

    @property
    def is_exclusive(self) -> bool:
        return self.path.split("/", 1)[0] == "EXCLUSIVE"


class FakeTree:
    def __init__(self, *nodes: FakeNode):
        self.nodes = {n.id: n for n in nodes}

    def get(self, node_id):
        return self.nodes.get(node_id)

    def find_by_sha256(self, sha):
        return [n for n in self.nodes.values() if n.sha256 == sha]


def _ensure_stubs() -> None:
    if _missing("bot.archive"):
        m = types.ModuleType("bot.archive")
        m.EXCLUSIVE = "EXCLUSIVE"
        m.tree = FakeTree()
        _install("bot.archive", m)
    if _missing("bot.storage"):
        m = types.ModuleType("bot.storage")
        remembered: list = []
        m.remembered = remembered
        m.remember_file_id = lambda *a: remembered.append(a)
        _install("bot.storage", m)
    if _missing("bot.keyboards"):
        m = types.ModuleType("bot.keyboards")
        m.folder = lambda node_id, page=0, **kw: (f"folder {node_id}", InlineKeyboardMarkup(inline_keyboard=[]))
        _install("bot.keyboards", m)
    if _missing("bot.filters"):
        m = types.ModuleType("bot.filters")

        class IsAdmin(Filter):
            async def __call__(self, event, settings=None) -> bool:
                return True

        class IsPrivate(IsAdmin):
            pass

        m.IsAdmin, m.IsPrivate = IsAdmin, IsPrivate
        _install("bot.filters", m)


_ensure_stubs()
from bot import archive, db  # noqa: E402


def restore_db_proxy() -> None:
    """Alcuni test di altri moduli assegnano una sqlite3.Connection a bot.db.conn:
    qui si rimette il proxy, così db.init()/db.close() funzionano."""
    if not isinstance(db.conn, db._Conn):
        db.conn = db._Conn()


def new_db(tmp: Path) -> None:
    """DB reale pulito in tmp (chiudere con db.close())."""
    restore_db_proxy()
    db.init(tmp / "bot.db")


def add_user(user_id: int, username: str | None = None, credits: int = 0) -> None:
    with db.conn:
        db.conn.execute(
            "INSERT OR REPLACE INTO users (id, username, first_name, credits) VALUES (?,?,?,?)",
            (user_id, username, f"Nome{user_id}", credits))


def credits_of(user_id: int) -> int:
    return db.conn.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()[0]


def make_settings(tmp: Path, **kw) -> SimpleNamespace:
    s = SimpleNamespace(
        archive_dir=tmp / "archive", inbox_dir=tmp / "inbox", trash_dir=tmp / "trash",
        bot_api_dir=tmp / "botapi", staff_chat_id=-100, admin_ids=frozenset({1, 2}),
        submit_max_mb=200, submit_per_day=10, price_max=50,
        local_api=True, max_download_bytes=2000 * 1024 * 1024)  # server Bot API locale (default dei test)
    for k, v in kw.items():
        setattr(s, k, v)
    for d in (s.archive_dir, s.inbox_dir, s.trash_dir, s.bot_api_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s


def set_tree(*nodes: FakeNode):
    """Albero vero (`archive.Tree`) + righe in `nodes` (con il DB reale c'è la chiave esterna)."""
    if getattr(archive, "STUB", False):
        archive.tree = FakeTree(*nodes)
        return archive.tree
    rows = [(n.id, n.path, n.parent_id, int(n.is_dir), n.price, 0, n.sha256,
             "2024-01-01 00:00:00", 0, 0) for n in nodes]
    for r in rows:
        if r[6]:
            db.conn.execute("INSERT OR IGNORE INTO blobs (sha256) VALUES (?)", (r[6],))
        db.conn.execute(
            "INSERT OR REPLACE INTO nodes (id, path, parent_id, is_dir, price, size, sha256, added_at, hidden, removed)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", r)
    db.conn.commit()
    archive.tree = archive.Tree(rows)
    return archive.tree


# --- bot finto ------------------------------------------------------------------

class FakeBot(Bot):
    """Bot vero (aiogram) il cui trasporto è sostituito: registra i metodi chiamati."""

    def __init__(self, files: dict[str, str] | None = None):
        super().__init__("123456:TESTTOKEN")
        self.calls: list = []
        self.files = files or {}
        self._next_id = 1000
        self.fail_all = False

    async def __call__(self, method, request_timeout=None):
        self.calls.append(method)
        if self.fail_all:
            raise RuntimeError("rete giù")
        name = type(method).__name__
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="bot", username="testbot")
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path=self.files[method.file_id])
        if name == "CopyMessage":
            self._next_id += 1
            return MessageId(message_id=self._next_id)
        if name == "SendMessage":
            self._next_id += 1
            return make_message(self, self._next_id, method.chat_id, "text")
        return True

    def of(self, name: str) -> list:
        return [c for c in self.calls if type(c).__name__ == name]


def make_message(bot, message_id: int, chat_id: int, chat_type: str = "private", *,
                 from_id: int = 5, text: str | None = None, document: dict | None = None,
                 media_group_id: str | None = None, reply_to: dict | None = None) -> Message:
    d = {"message_id": message_id, "date": datetime.now(),
         "chat": {"id": chat_id, "type": chat_type},
         "from": {"id": from_id, "is_bot": False, "first_name": "U", "username": f"u{from_id}"}}
    if text is not None:
        d["text"] = text
    if document is not None:
        d["document"] = document
    if media_group_id:
        d["media_group_id"] = media_group_id
    if reply_to:
        d["reply_to_message"] = reply_to
    return Message.model_validate(d, context={"bot": bot})


def make_callback(bot, data: str, message: Message, from_id: int = 1) -> CallbackQuery:
    return CallbackQuery.model_validate(
        {"id": "1", "chat_instance": "x", "data": data,
         "from": {"id": from_id, "is_bot": False, "first_name": "A", "username": f"adm{from_id}"},
         "message": message.model_dump(by_alias=True, exclude_none=True, mode="python")},
        context={"bot": bot})
