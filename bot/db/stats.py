"""Query di statistiche, destinatari del broadcast e pulizia dei download."""

from bot import db


def _one(sql: str, params: tuple = ()) -> int:
    return db.conn.execute(sql, params).fetchone()[0] or 0


def overview() -> dict:
    return {
        "users": _one("SELECT COUNT(*) FROM users"),
        "blocked": _one("SELECT COUNT(*) FROM users WHERE blocked = 1"),
        "active_7": _one("SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-7 days')"),
        "active_30": _one("SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-30 days')"),
        "downloads_total": _one("SELECT SUM(downloads) FROM users"),
        "downloads_30": _one("SELECT COUNT(*) FROM downloads WHERE at >= datetime('now', '-30 days')"),
        "tickets": _one("SELECT COUNT(*) FROM tickets WHERE status = 'open'"),
    }


def top_files(limit: int = 10) -> list[tuple[int, int]]:
    """(node_id, download) dei file più scaricati."""
    rows = db.conn.execute(
        "SELECT node_id, COUNT(*) AS n FROM downloads GROUP BY node_id ORDER BY n DESC, node_id LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def broadcast_recipients() -> list[int]:
    return [r[0] for r in db.conn.execute("SELECT id FROM users WHERE blocked = 0 ORDER BY id")]


def nodes_count() -> int:
    return _one("SELECT COUNT(*) FROM nodes")


def purge_downloads_before(cutoff: str) -> int:
    """Cancella i download con `at` < cutoff ('YYYY-MM-DD HH:MM:SS'). Ritorna le righe tolte."""
    with db.conn:
        return db.conn.execute("DELETE FROM downloads WHERE at < ?", (cutoff,)).rowcount
