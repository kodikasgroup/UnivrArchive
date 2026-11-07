"""Invii utenti (submissions) e ticket. Tutto il loro SQL sta qui."""

from dataclasses import dataclass

from bot import db


@dataclass(frozen=True)
class Submission:
    id: int
    user_id: int
    file_id: str
    file_unique_id: str
    file_name: str
    size: int | None
    sha256: str | None
    inbox_path: str | None
    duplicate_of: int | None
    hint_node_id: int | None
    user_message_id: int | None
    staff_message_id: int | None
    status: str
    credits: int
    dest_path: str | None
    reviewed_by: int | None
    at: str


@dataclass(frozen=True)
class Ticket:
    id: int
    user_id: int
    kind: str
    node_id: int | None
    text: str | None
    staff_message_id: int
    status: str
    closed_by: int | None


_SUB_COLS = (
    "id, user_id, file_id, file_unique_id, file_name, size, sha256, inbox_path, "
    "duplicate_of, hint_node_id, user_message_id, staff_message_id, status, "
    "credits, dest_path, reviewed_by, at"
)
_TK_COLS = "id, user_id, kind, node_id, text, staff_message_id, status, closed_by"


def _sub(row: tuple | None) -> Submission | None:
    return Submission(*row) if row else None


# Un invio 'pending' senza scheda staff più vecchio di così è orfano: la scelta
# della cartella (in RAM, 10 minuti) è andata persa o la scheda non è partita.
# Non conta per dedup e limite giornaliero; lo recupera submit.recover_orphans.
ORPHAN_AFTER_S = 900
_LIVE = ("NOT (status = 'pending' AND staff_message_id IS NULL "
         f"AND at < datetime('now', '-{ORPHAN_AFTER_S} seconds'))")


# --- submissions ---------------------------------------------------------

def create_submission(user_id: int, file_id: str, file_unique_id: str, file_name: str,
                      size: int | None, user_message_id: int | None) -> int:
    with db.conn:
        cur = db.conn.execute(
            "INSERT INTO submissions (user_id, file_id, file_unique_id, file_name, size, "
            "user_message_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, file_id, file_unique_id, file_name, size, user_message_id),
        )
    return int(cur.lastrowid)


def delete_submission(sub_id: int) -> None:
    """Solo per righe appena create e mai presentate (es. download fallito)."""
    with db.conn:
        db.conn.execute("DELETE FROM submissions WHERE id = ? AND staff_message_id IS NULL", (sub_id,))


def get_submission(sub_id: int) -> Submission | None:
    row = db.conn.execute(f"SELECT {_SUB_COLS} FROM submissions WHERE id = ?", (sub_id,)).fetchone()
    return _sub(row)


def get_by_staff_message(staff_message_id: int) -> Submission | None:
    row = db.conn.execute(
        f"SELECT {_SUB_COLS} FROM submissions WHERE staff_message_id = ?", (staff_message_id,)
    ).fetchone()
    return _sub(row)


def seen_unique_id(file_unique_id: str) -> bool:
    """Questo file (per Telegram) è già stato inviato e non scartato?"""
    row = db.conn.execute(
        "SELECT 1 FROM submissions WHERE file_unique_id = ? "
        f"AND status IN ('pending', 'approved', 'duplicate') AND {_LIVE} LIMIT 1",
        (file_unique_id,),
    ).fetchone()
    return row is not None


def count_recent_pending(user_id: int, hours: int = 24) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) FROM submissions WHERE user_id = ? AND status = 'pending' "
        f"AND at >= datetime('now', ?) AND {_LIVE}",
        (user_id, f"-{int(hours)} hours"),
    ).fetchone()
    return int(row[0])


def set_file_info(sub_id: int, sha256: str, inbox_path: str) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET sha256 = ?, inbox_path = ? WHERE id = ?",
            (sha256, inbox_path, sub_id),
        )


def find_pending_by_sha256(sha256: str, exclude_id: int) -> int | None:
    """Stesso contenuto già in attesa, o approvato ma non ancora nell'albero (pre-/reindex)."""
    row = db.conn.execute(
        "SELECT id FROM submissions WHERE sha256 = ? AND status IN ('pending', 'approved') "
        f"AND id != ? AND {_LIVE} ORDER BY id LIMIT 1",
        (sha256, exclude_id),
    ).fetchone()
    return int(row[0]) if row else None


def mark_duplicate(sub_id: int, duplicate_of_node: int | None) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET status = 'duplicate', duplicate_of = ? WHERE id = ?",
            (duplicate_of_node, sub_id),
        )


def set_hint(sub_id: int, node_id: int | None) -> None:
    with db.conn:
        db.conn.execute("UPDATE submissions SET hint_node_id = ? WHERE id = ?", (node_id, sub_id))


def set_dest_folder(sub_id: int, folder_rel: str | None) -> None:
    """Finché è pending, dest_path = cartella scelta dall'admin (percorso relativo).
    All'approvazione diventa il percorso finale del file."""
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET dest_path = ? WHERE id = ? AND status = 'pending'",
            (folder_rel, sub_id),
        )


def set_staff_message(sub_id: int, staff_message_id: int) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET staff_message_id = ? WHERE id = ?", (staff_message_id, sub_id)
        )


def claim_approval(sub_id: int, admin_id: int, credits: int) -> bool:
    """pending -> approved in modo atomico. False se già gestito (doppio click)."""
    with db.conn:
        cur = db.conn.execute(
            "UPDATE submissions SET status = 'approved', credits = ?, reviewed_by = ?, "
            "reviewed_at = datetime('now') WHERE id = ? AND status = 'pending'",
            (credits, admin_id, sub_id),
        )
    return cur.rowcount == 1


def revert_claim(sub_id: int) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET status = 'pending', credits = 0, reviewed_by = NULL, "
            "reviewed_at = NULL WHERE id = ? AND status = 'approved'",
            (sub_id,),
        )


def finalize_approval(sub_id: int, dest_path: str) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET dest_path = ?, inbox_path = NULL WHERE id = ?",
            (dest_path, sub_id),
        )


def orphaned_pending() -> list[Submission]:
    rows = db.conn.execute(
        f"SELECT {_SUB_COLS} FROM submissions WHERE status = 'pending' "
        f"AND staff_message_id IS NULL AND NOT {_LIVE} ORDER BY id"
    ).fetchall()
    return [Submission(*r) for r in rows]


def reject_orphan(sub_id: int) -> None:
    """Orfano non recuperabile: scartato (il file in inbox andrà via con la pulizia)."""
    with db.conn:
        db.conn.execute(
            "UPDATE submissions SET status = 'rejected', reviewed_at = at "
            "WHERE id = ? AND status = 'pending' AND staff_message_id IS NULL",
            (sub_id,),
        )


def reject(sub_id: int, admin_id: int) -> bool:
    with db.conn:
        cur = db.conn.execute(
            "UPDATE submissions SET status = 'rejected', reviewed_by = ?, "
            "reviewed_at = datetime('now') WHERE id = ? AND status = 'pending'",
            (admin_id, sub_id),
        )
    return cur.rowcount == 1


# --- letti da admin e job notturno -----------------------------------------------------------

def count_pending() -> int:
    """Invii in attesa di moderazione (già presentati allo staff)."""
    row = db.conn.execute(
        "SELECT COUNT(*) FROM submissions WHERE status = 'pending' AND staff_message_id IS NOT NULL"
    ).fetchone()
    return int(row[0])


def list_pending(limit: int = 50) -> list[tuple[int, int, str]]:
    rows = db.conn.execute(
        "SELECT id, staff_message_id, file_name FROM submissions "
        "WHERE status = 'pending' AND staff_message_id IS NOT NULL ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    return [(int(r[0]), int(r[1]), r[2]) for r in rows]


def expired_inbox_files(days: int = 30) -> list[str]:
    """Percorsi inbox di rejected/duplicate più vecchi di `days`. Non li azzera:
    lo fa clear_inbox_paths dopo la cancellazione riuscita."""
    rows = db.conn.execute(
        "SELECT inbox_path FROM submissions WHERE status IN ('rejected', 'duplicate') "
        "AND inbox_path IS NOT NULL AND COALESCE(reviewed_at, at) < datetime('now', ?)",
        (f"-{int(days)} days",),
    ).fetchall()
    return [r[0] for r in rows]


def clear_inbox_paths(paths: list[str]) -> None:
    with db.conn:
        db.conn.executemany(
            "UPDATE submissions SET inbox_path = NULL WHERE inbox_path = ? "
            "AND status IN ('rejected', 'duplicate')",
            [(p,) for p in paths],
        )


def stale_pending(days: int = 30) -> list[int]:
    rows = db.conn.execute(
        "SELECT id FROM submissions WHERE status = 'pending' AND staff_message_id IS NOT NULL "
        "AND at < datetime('now', ?) ORDER BY id",
        (f"-{int(days)} days",),
    ).fetchall()
    return [int(r[0]) for r in rows]


# --- tickets ---------------------------------------------------------------

def create_ticket(user_id: int, kind: str, node_id: int | None, text: str | None,
                  temp_staff_message_id: int) -> int:
    """staff_message_id è NOT NULL e unico: si inserisce con un valore temporaneo
    (negativo) e lo si aggiorna dopo aver pubblicato la scheda."""
    with db.conn:
        cur = db.conn.execute(
            "INSERT INTO tickets (user_id, kind, node_id, text, staff_message_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, kind, node_id, text, temp_staff_message_id),
        )
    return int(cur.lastrowid)


def set_ticket_staff_message(ticket_id: int, staff_message_id: int) -> None:
    with db.conn:
        db.conn.execute(
            "UPDATE tickets SET staff_message_id = ? WHERE id = ?", (staff_message_id, ticket_id)
        )


def delete_ticket(ticket_id: int) -> None:
    with db.conn:
        db.conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))


def get_ticket(ticket_id: int) -> Ticket | None:
    row = db.conn.execute(f"SELECT {_TK_COLS} FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return Ticket(*row) if row else None


def get_ticket_by_staff_message(staff_message_id: int) -> Ticket | None:
    row = db.conn.execute(
        f"SELECT {_TK_COLS} FROM tickets WHERE staff_message_id = ?", (staff_message_id,)
    ).fetchone()
    return Ticket(*row) if row else None


def close_ticket(ticket_id: int, admin_id: int) -> bool:
    with db.conn:
        cur = db.conn.execute(
            "UPDATE tickets SET status = 'closed', closed_by = ? WHERE id = ? AND status = 'open'",
            (admin_id, ticket_id),
        )
    return cur.rowcount == 1

