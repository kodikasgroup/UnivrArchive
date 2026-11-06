"""Connessione SQLite, schema, migrazioni, utenti, crediti, VIP, kv.

REGOLA PER TUTTI I MODULI bot/db/*: le scritture si fanno solo dal thread
dell'event loop e senza `await` dentro un `with conn:`; così una funzione DB è
atomica rispetto agli altri handler. Lo scan di archive.py gira in thread ma
non scrive: scrive solo apply_reindex, dal loop. Tutto l'SQL usa parametri `?`.

`conn` è un proxy stabile: `from bot.db import conn` funziona anche se fatto
prima di init() (e init() può essere richiamata, es. nei test, su un altro file).
Il proxy espone l'API di sqlite3.Connection (execute, `with conn:`, ...).
"""
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

PERMANENT = "9999-12-31"
_FMT = "%Y-%m-%d %H:%M:%S"

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    credits     INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
    vip_until   TEXT,
    downloads   INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT
);
CREATE INDEX IF NOT EXISTS users_username ON users(username COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS blobs (
    sha256              TEXT PRIMARY KEY,
    file_id             TEXT,
    file_unique_id      TEXT,
    storage_message_id  INTEGER
);

CREATE TABLE IF NOT EXISTS nodes (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL,
    parent_id       INTEGER REFERENCES nodes(id),
    is_dir          INTEGER NOT NULL,
    price           INTEGER NOT NULL DEFAULT 0,
    size            INTEGER,
    mtime           REAL,
    sha256          TEXT REFERENCES blobs(sha256),
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    hidden          INTEGER NOT NULL DEFAULT 0,
    removed         INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS nodes_path_active ON nodes(path) WHERE removed = 0;
CREATE INDEX IF NOT EXISTS nodes_sha256 ON nodes(sha256);

CREATE TABLE IF NOT EXISTS purchases (
    user_id  INTEGER NOT NULL REFERENCES users(id),
    node_id  INTEGER NOT NULL REFERENCES nodes(id),
    price    INTEGER NOT NULL,
    at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, node_id)
);

CREATE TABLE IF NOT EXISTS credit_log (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    delta   INTEGER NOT NULL,
    reason  TEXT NOT NULL,
    at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS submissions (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    file_id          TEXT NOT NULL,
    file_unique_id   TEXT NOT NULL,
    file_name        TEXT NOT NULL,
    size             INTEGER,
    sha256           TEXT,
    inbox_path       TEXT,
    duplicate_of     INTEGER REFERENCES nodes(id),
    hint_node_id     INTEGER REFERENCES nodes(id),
    user_message_id  INTEGER,
    staff_message_id INTEGER,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected','duplicate')),
    credits          INTEGER NOT NULL DEFAULT 0,
    dest_path        TEXT,
    reviewed_by      INTEGER,
    reviewed_at      TEXT,
    at               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS submissions_unique ON submissions(file_unique_id);

CREATE TABLE IF NOT EXISTS favorites (
    user_id  INTEGER NOT NULL REFERENCES users(id),
    node_id  INTEGER NOT NULL REFERENCES nodes(id),
    at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, node_id)
);

CREATE TABLE IF NOT EXISTS downloads (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    node_id  INTEGER NOT NULL REFERENCES nodes(id),
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS downloads_user ON downloads(user_id, at DESC);
CREATE INDEX IF NOT EXISTS downloads_node ON downloads(node_id);

CREATE TABLE IF NOT EXISTS tickets (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    kind             TEXT NOT NULL CHECK (kind IN ('feedback','report','removal')),
    node_id          INTEGER REFERENCES nodes(id),
    text             TEXT,
    staff_message_id INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    closed_by        INTEGER,
    at               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS tickets_staff_msg ON tickets(staff_message_id);

CREATE TABLE IF NOT EXISTS group_folders (
    chat_id   INTEGER PRIMARY KEY,
    node_id   INTEGER NOT NULL REFERENCES nodes(id),
    linked_by INTEGER NOT NULL,
    at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

# MIGRATIONS[i] porta il DB dalla versione i alla i+1 (PRAGMA user_version).
# La 0 -> 1 è lo schema iniziale. Per cambiare lo schema: aggiungere uno script in coda.
MIGRATIONS: list[str] = [SCHEMA_V1]


class _Conn:
    """Proxy della connessione corrente (vedi docstring del modulo)."""

    _real: sqlite3.Connection | None = None

    def __getattr__(self, name):
        if self._real is None:
            raise RuntimeError("bot.db.init() non è stata chiamata")
        return getattr(self._real, name)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


conn = _Conn()


def init(db_path: Path) -> None:
    """Apre il DB (creando il file), imposta i PRAGMA e applica le migrazioni."""
    close()
    real = sqlite3.connect(str(db_path), check_same_thread=False)
    real.execute("PRAGMA journal_mode = WAL")
    real.execute("PRAGMA synchronous = NORMAL")
    real.execute("PRAGMA foreign_keys = ON")
    real.execute("PRAGMA busy_timeout = 5000")
    conn._real = real
    version = real.execute("PRAGMA user_version").fetchone()[0]
    if version > len(MIGRATIONS):
        raise RuntimeError(f"DB alla versione {version}, il codice arriva a {len(MIGRATIONS)}")
    for i in range(version, len(MIGRATIONS)):
        try:
            real.executescript(f"BEGIN;\n{MIGRATIONS[i]}\nPRAGMA user_version = {i + 1};\nCOMMIT;")
        except Exception:
            if real.in_transaction:
                real.execute("ROLLBACK")
            raise
        log.info("DB migrato alla versione %d", i + 1)


def close() -> None:
    if conn._real is not None:
        conn._real.close()
        conn._real = None


# ───────────────────────── utenti ─────────────────────────

@dataclass(frozen=True)
class User:
    id: int
    username: str | None
    first_name: str | None
    credits: int
    vip_until: str | None
    downloads: int
    blocked: bool
    created_at: str
    last_seen: str | None


_USER_COLS = "id, username, first_name, credits, vip_until, downloads, blocked, created_at, last_seen"


def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    """Crea o aggiorna l'utente; chi scrive di nuovo non ha più bloccato il bot."""
    with conn:
        conn.execute(
            "INSERT INTO users (id, username, first_name, last_seen) VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET username = excluded.username, "
            "first_name = excluded.first_name, last_seen = excluded.last_seen, blocked = 0",
            (user_id, username, first_name))


def get_user(user_id: int) -> User | None:
    row = conn.execute(f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return User(*row[:6], bool(row[6]), *row[7:])


def find_user(ref: str) -> int | None | Literal["ambiguous"]:
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        row = conn.execute("SELECT id FROM users WHERE id = ?", (int(ref),)).fetchone()
        return row[0] if row else None
    rows = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE LIMIT 2",
                        (ref.removeprefix("@"),)).fetchall()
    if not rows:
        return None
    return rows[0][0] if len(rows) == 1 else "ambiguous"


def is_vip(user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE id = ? AND vip_until > datetime('now')",
                        (user_id,)).fetchone() is not None


def grant_vip(user_id: int, days: int) -> str:
    """days > 0: somma alla scadenza se ancora valida; days == 0: permanente."""
    if days == 0:
        new = PERMANENT
    else:
        now = datetime.now(timezone.utc).strftime(_FMT)
        row = conn.execute("SELECT vip_until FROM users WHERE id = ?", (user_id,)).fetchone()
        current = row[0] if row and row[0] else ""
        if current.startswith(PERMANENT):
            new = current
        else:
            base = max(now, current)
            if len(base) == 10:  # solo data
                base += " 00:00:00"
            try:
                new = (datetime.strptime(base, _FMT) + timedelta(days=days)).strftime(_FMT)
            except OverflowError:
                new = PERMANENT
    with conn:
        conn.execute("UPDATE users SET vip_until = ? WHERE id = ?", (new, user_id))
    return new


def revoke_vip(user_id: int) -> None:
    with conn:
        conn.execute("UPDATE users SET vip_until = NULL WHERE id = ?", (user_id,))


def add_credits(user_id: int, delta: int, reason: str) -> bool:
    """Atomica; False (senza scrivere nulla) se l'utente non esiste o il saldo andrebbe < 0."""
    with conn:
        cur = conn.execute("UPDATE users SET credits = credits + ? WHERE id = ? AND credits + ? >= 0",
                           (delta, user_id, delta))
        if cur.rowcount != 1:
            return False
        conn.execute("INSERT INTO credit_log (user_id, delta, reason) VALUES (?, ?, ?)",
                     (user_id, delta, reason))
    return True


def set_blocked(user_id: int, blocked: bool) -> None:
    with conn:
        conn.execute("UPDATE users SET blocked = ? WHERE id = ?", (int(blocked), user_id))


def kv_get(key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def kv_set(key: str, value: str) -> None:
    with conn:
        conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
