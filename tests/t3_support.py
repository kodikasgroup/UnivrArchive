"""Supporto ai test di T3: stub dei moduli di altri task (se non esistono ancora),
albero finto e schema DB minimo. Importare PRIMA di `bot.keyboards` / `bot.handlers.*`."""

import dataclasses
import importlib
import sqlite3
import sys
import types
from datetime import UTC, datetime, timedelta


def _ensure(name: str, **attrs) -> None:
    try:
        importlib.import_module(name)
        return
    except ImportError:
        pass
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], child, mod)


@dataclasses.dataclass(frozen=True)
class _Node:
    id: int
    parent_id: int | None
    name: str
    raw_name: str
    path: str
    is_dir: bool
    depth: int
    is_exclusive: bool
    price: int
    size: int
    sha256: str | None
    added_at: datetime


@dataclasses.dataclass(frozen=True)
class _Settings:
    token: str = ""
    admin_ids: frozenset = frozenset()
    donation_link: str = ""


def _install() -> None:
    _ensure("bot")
    _ensure("bot.db")
    _ensure("bot.archive", EXCLUSIVE="EXCLUSIVE", Node=_Node, Tree=object, tree=None)
    _ensure("bot.config", Settings=_Settings)
    _ensure("bot.storage")
    _ensure("bot.db.nodes", get_blob=lambda sha: None)


_install()

from bot import archive, db  # noqa: E402

NOW = datetime.now(UTC).replace(tzinfo=None)


class FakeTree:
    """Albero in memoria con la stessa interfaccia di `archive.Tree` (contratto §5)."""

    def __init__(self, nodes, version=1):
        self.version = version
        self._nodes = {n.id: n for n in nodes}

    def get(self, node_id):
        return self._nodes.get(node_id)

    def children(self, node_id):
        kids = [n for n in self._nodes.values() if n.parent_id == node_id]
        return sorted(kids, key=lambda n: (not n.is_dir, n.name.casefold()))

    def breadcrumb(self, node_id):
        out = []
        n = self._nodes.get(node_id)
        while n is not None:
            out.append(n)
            n = self._nodes.get(n.parent_id) if n.parent_id else None
        return out[::-1]

    def nearest_visible(self, node_id):
        return None

    def is_new(self, node_id, days=7):
        n = self._nodes.get(node_id)
        return n is not None and n.added_at > NOW - timedelta(days=days)

    def new_files(self, days=7):
        return [n for n in self._nodes.values() if not n.is_dir and self.is_new(n.id, days)]

    def free_files(self, node_id):
        return [n for n in self.children(node_id) if not n.is_dir and n.price == 0]

    def search(self, query, limit=50, *, include_exclusive):
        q = query.casefold()
        found = [n for n in self._nodes.values()
                 if q in n.name.casefold() and (include_exclusive or not n.is_exclusive)]
        return sorted(found, key=lambda n: n.id)[:limit]

    def find_by_sha256(self, sha256):
        return [n for n in self._nodes.values() if n.sha256 == sha256]


def make_tree(specs, version=1, old=False):
    """specs: (id, parent_id, name, is_dir[, price[, size]]). Calcola path/depth/exclusive."""
    by_id = {s[0]: s for s in specs}
    nodes = []
    for s in specs:
        nid, parent, name, is_dir = s[:4]
        price = s[4] if len(s) > 4 else 0
        size = s[5] if len(s) > 5 else 1000
        chain, cur = [], s
        while cur is not None:
            chain.append(cur[2])
            cur = by_id.get(cur[1])
        chain.reverse()
        path = "/".join(chain)
        nodes.append(archive.Node(
            id=nid, parent_id=parent, name=name.replace("_", " "), raw_name=name, path=path,
            is_dir=is_dir, depth=len(chain), is_exclusive=chain[0] == "EXCLUSIVE",
            price=price, size=size, sha256=None if is_dir else f"sha{nid}",
            added_at=NOW - timedelta(days=30 if old else 1)))
    return FakeTree(nodes, version)


SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
  credits INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0), vip_until TEXT,
  downloads INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), last_seen TEXT);
CREATE TABLE purchases (user_id INTEGER NOT NULL, node_id INTEGER NOT NULL,
  price INTEGER NOT NULL, at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, node_id));
CREATE TABLE credit_log (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
  delta INTEGER NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE favorites (user_id INTEGER NOT NULL, node_id INTEGER NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (user_id, node_id));
CREATE TABLE downloads (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
  node_id INTEGER NOT NULL, at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE group_folders (chat_id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL,
  linked_by INTEGER NOT NULL, at TEXT NOT NULL DEFAULT (datetime('now')));
"""


def open_db() -> sqlite3.Connection:
    """DB in memoria con le tabelle usate da T3, assegnato a `bot.db.conn`."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    db.conn = conn
    return conn
