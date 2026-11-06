"""SQL dell'archivio: tabelle `nodes` e `blobs` (schema creato da T1)."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Iterator

from bot import db

if TYPE_CHECKING:
    from bot.storage import Blob


@dataclass(frozen=True)
class NodeWrite:
    """Stato finale di un nodo. op: keep | touch | update | insert."""

    path: str
    is_dir: bool
    price: int
    size: int
    mtime: float
    sha256: str | None
    hidden: bool
    op: str
    id: int | None = None
    added_at: str | None = None  # solo per insert / riuso di una riga rimossa


@contextlib.contextmanager
def _transaction() -> Iterator[None]:
    conn = db.conn
    if conn.in_transaction:  # il chiamante gestisce già la transazione
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


# ───────────────────────── lettura ─────────────────────────

def count_nodes() -> int:
    return db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]


def load_active() -> list[tuple]:
    """(id, path, parent_id, is_dir, price, size, mtime, sha256, hidden) dei nodi con removed = 0."""
    return db.conn.execute(
        "SELECT id, path, parent_id, is_dir, price, size, mtime, sha256, hidden FROM nodes WHERE removed = 0"
    ).fetchall()


def load_removed() -> list[tuple]:
    """Righe rimosse: (id, path, sha256, is_dir), dalla più vecchia."""
    return db.conn.execute("SELECT id, path, sha256, is_dir FROM nodes WHERE removed = 1 ORDER BY id").fetchall()


def load_all_for_tree() -> list[tuple]:
    """(id, path, parent_id, is_dir, price, size, sha256, added_at, hidden, removed)"""
    return db.conn.execute(
        "SELECT id, path, parent_id, is_dir, price, size, sha256, added_at, hidden, removed FROM nodes"
    ).fetchall()


def node_has_purchases(node_id: int) -> bool:
    row = db.conn.execute("SELECT 1 FROM purchases WHERE node_id = ? LIMIT 1", (node_id,)).fetchone()
    return row is not None


def ids_with_purchases(node_ids: Iterable[int]) -> set[int]:
    ids = list(node_ids)
    found: set[int] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(
            r[0]
            for r in db.conn.execute(f"SELECT DISTINCT node_id FROM purchases WHERE node_id IN ({marks})", chunk)
        )
    return found


# ───────────────────────── scrittura (reindex) ─────────────────────────

def apply_changes(removed_ids: list[int], writes: list[NodeWrite], now: str) -> None:
    """Una sola transazione: rimozioni, spostamenti, inserimenti. `now` = 'YYYY-MM-DD HH:MM:SS' UTC.

    `writes` contiene tutti i nodi dello stato finale (anche `keep`, che servono
    a risolvere il parent_id).
    """
    conn = db.conn
    with _transaction():
        for node_id in removed_ids:
            conn.execute("UPDATE nodes SET removed = 1 WHERE id = ?", (node_id,))
        # libera i vecchi percorsi: l'indice univoco vale solo tra i nodi attivi
        for w in writes:
            if w.op == "update" and w.id is not None:
                conn.execute("UPDATE nodes SET removed = 1, path = ? WHERE id = ?", (f"\x00moving/{w.id}", w.id))
        # i blob vanno creati prima dei nodi (foreign key)
        shas = {w.sha256 for w in writes if w.sha256 and w.op in ("update", "insert")}
        conn.executemany("INSERT OR IGNORE INTO blobs (sha256) VALUES (?)", [(s,) for s in shas])

        ids: dict[str, int] = {w.path: w.id for w in writes if w.id is not None}
        # cartelle per profondità crescente (i padri esistono sempre), poi i file
        ordered = sorted(writes, key=lambda w: (not w.is_dir, w.path.count("/"), w.path))
        for w in ordered:
            parent_path = w.path.rpartition("/")[0]
            parent_id = ids.get(parent_path) if parent_path else None
            if w.op == "touch":
                conn.execute("UPDATE nodes SET size = ?, mtime = ? WHERE id = ?", (w.size, w.mtime, w.id))
            elif w.op == "update":
                conn.execute(
                    "UPDATE nodes SET path=?, parent_id=?, is_dir=?, price=?, size=?, mtime=?, sha256=?, "
                    "hidden=?, removed=0, added_at=COALESCE(?, added_at) WHERE id=?",
                    (w.path, parent_id, w.is_dir, w.price, w.size, w.mtime, w.sha256, w.hidden, w.added_at, w.id),
                )
            elif w.op == "insert":
                cur = conn.execute(
                    "INSERT INTO nodes (path, parent_id, is_dir, price, size, mtime, sha256, added_at, hidden) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (w.path, parent_id, w.is_dir, w.price, w.size, w.mtime, w.sha256, w.added_at or now, w.hidden),
                )
                ids[w.path] = cur.lastrowid


def apply_touches(writes: list[NodeWrite]) -> None:
    """Aggiorna solo size/mtime (nessuna modifica visibile)."""
    with _transaction():
        db.conn.executemany(
            "UPDATE nodes SET size = ?, mtime = ? WHERE id = ?", [(w.size, w.mtime, w.id) for w in writes]
        )


# ───────────────────────── blob / canale storage ─────────────────────────

def get_blob(sha256: str) -> Blob | None:
    from bot.storage import Blob  # import tardivo: storage importa questo modulo

    row = db.conn.execute(
        "SELECT sha256, file_id, file_unique_id, storage_message_id FROM blobs WHERE sha256 = ?", (sha256,)
    ).fetchone()
    return Blob(*row) if row else None


def set_file_id(sha256: str, file_id: str, file_unique_id: str | None) -> None:
    with _transaction():
        db.conn.execute("INSERT OR IGNORE INTO blobs (sha256) VALUES (?)", (sha256,))
        db.conn.execute(
            "UPDATE blobs SET file_id = ?, file_unique_id = ? WHERE sha256 = ?", (file_id, file_unique_id, sha256)
        )


def set_storage(sha256: str, file_id: str, file_unique_id: str | None, storage_message_id: int) -> None:
    with _transaction():
        db.conn.execute("INSERT OR IGNORE INTO blobs (sha256) VALUES (?)", (sha256,))
        db.conn.execute(
            "UPDATE blobs SET file_id = ?, file_unique_id = ?, storage_message_id = ? WHERE sha256 = ?",
            (file_id, file_unique_id, storage_message_id, sha256),
        )


_TO_UPLOAD = (
    "FROM blobs b JOIN nodes n ON n.sha256 = b.sha256 "
    "WHERE b.storage_message_id IS NULL AND n.removed = 0 AND n.hidden = 0 AND n.is_dir = 0"
)


def blobs_to_upload() -> list[tuple[str, str]]:
    """(sha256, path) di un nodo attivo per ogni blob non ancora nel canale."""
    return db.conn.execute(
        f"SELECT b.sha256, MIN(n.path) {_TO_UPLOAD} GROUP BY b.sha256 ORDER BY MIN(n.id)"
    ).fetchall()


def count_to_upload() -> int:
    return db.conn.execute(f"SELECT COUNT(DISTINCT b.sha256) {_TO_UPLOAD}").fetchone()[0]
