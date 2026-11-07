"""Acquisti, download, preferiti, gruppi collegati (SQL con parametri `?`)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from bot import db


@contextmanager
def _tx() -> Iterator[sqlite3.Connection]:
    """Transazione atomica, valida sia in modalità legacy che in autocommit.
    Se una transazione è già aperta ci si accoda a quella."""
    conn = db.conn
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def buy(user_id: int, node_id: int, price: int) -> bool:
    """Acquisto atomico. `price` è quello letto dall'albero adesso.
    True se acquistato ora o già posseduto (nessun doppio addebito)."""
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM purchases WHERE user_id=? AND node_id=?",
                        (user_id, node_id)).fetchone():
            return True
        cur = conn.execute(
            "UPDATE users SET credits = credits - ? WHERE id = ? AND credits >= ?",
            (price, user_id, price))
        if cur.rowcount == 0:
            return False
        conn.execute("INSERT INTO purchases (user_id, node_id, price) VALUES (?,?,?)",
                     (user_id, node_id, price))
        conn.execute("INSERT INTO credit_log (user_id, delta, reason) VALUES (?,?,?)",
                     (user_id, -price, f"purchase:{node_id}"))
    return True


def has_purchase(user_id: int, node_id: int) -> bool:
    return db.conn.execute("SELECT 1 FROM purchases WHERE user_id=? AND node_id=?",
                           (user_id, node_id)).fetchone() is not None


def log_download(user_id: int, node_id: int) -> None:
    with _tx() as conn:
        conn.execute("INSERT INTO downloads (user_id, node_id) VALUES (?,?)",
                     (user_id, node_id))
        conn.execute("UPDATE users SET downloads = downloads + 1 WHERE id = ?", (user_id,))


def recent_downloads(user_id: int, limit: int = 10) -> list[int]:
    """Ultimi file scaricati, dal più recente, senza ripetizioni."""
    rows = db.conn.execute(
        "SELECT node_id FROM downloads WHERE user_id = ? "
        "GROUP BY node_id ORDER BY MAX(id) DESC LIMIT ?",
        (user_id, limit)).fetchall()
    return [r[0] for r in rows]


def toggle_favorite(user_id: int, node_id: int) -> bool:
    """True = ora è tra i preferiti."""
    with _tx() as conn:
        cur = conn.execute("DELETE FROM favorites WHERE user_id=? AND node_id=?",
                           (user_id, node_id))
        if cur.rowcount:
            return False
        conn.execute("INSERT INTO favorites (user_id, node_id) VALUES (?,?)",
                     (user_id, node_id))
    return True


def list_favorites(user_id: int) -> list[int]:
    rows = db.conn.execute(
        "SELECT node_id FROM favorites WHERE user_id = ? ORDER BY at DESC, rowid DESC",
        (user_id,)).fetchall()
    return [r[0] for r in rows]


def get_group_folder(chat_id: int) -> int | None:
    row = db.conn.execute("SELECT node_id FROM group_folders WHERE chat_id = ?",
                          (chat_id,)).fetchone()
    return row[0] if row else None


def set_group_folder(chat_id: int, node_id: int, admin_id: int) -> None:
    with _tx() as conn:
        conn.execute(
            "INSERT INTO group_folders (chat_id, node_id, linked_by) VALUES (?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET node_id = excluded.node_id, "
            "linked_by = excluded.linked_by, at = datetime('now')",
            (chat_id, node_id, admin_id))


def delete_group_folder(chat_id: int) -> None:
    with _tx() as conn:
        conn.execute("DELETE FROM group_folders WHERE chat_id = ?", (chat_id,))
