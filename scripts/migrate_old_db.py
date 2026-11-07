"""Migra utenti, crediti, VIP e download dal vecchio DB (v1) al nuovo.

    python -m scripts.migrate_old_db <vecchio.db> <nuovo.db> [--dry-run]

Il vecchio DB è aperto in sola lettura. Rilanciabile: stesso risultato a ogni esecuzione.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from bot import db


def _open_old(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"Vecchio DB non trovato: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def summary() -> dict[str, int]:
    """Numeri del DB nuovo (db.conn)."""
    q = lambda sql: db.conn.execute(sql).fetchone()[0] or 0  # noqa: E731
    return {
        "utenti": q("SELECT COUNT(*) FROM users"),
        "crediti": q("SELECT SUM(credits) FROM users"),
        "vip": q("SELECT COUNT(*) FROM users WHERE vip_until IS NOT NULL"),
        "download": q("SELECT SUM(downloads) FROM users"),
    }


def _copy_users(old: sqlite3.Connection) -> None:
    """SQL di migrazione, con lettura dal vecchio DB tramite una connessione separata read-only."""
    users = old.execute("SELECT chat_id, username, f_name, state FROM User ORDER BY rowid").fetchall()
    reserved = old.execute("SELECT chat_id, MAX(Credit), MAX(Vip) FROM Reserved GROUP BY chat_id").fetchall()
    downloads = old.execute("SELECT chat_id, SUM(n_download) FROM Download GROUP BY chat_id").fetchall()
    only_reserved = [(r[0],) for r in old.execute("SELECT DISTINCT chat_id FROM Reserved")]
    only_download = [(r[0],) for r in old.execute("SELECT DISTINCT chat_id FROM Download")]

    # righe duplicate per chat_id (il vecchio DB non aveva chiavi): INSERT OR IGNORE tiene la prima
    db.conn.executemany(
        "INSERT OR IGNORE INTO users (id, username, first_name, last_seen) VALUES (?, ?, ?, ?)", users)
    db.conn.executemany("INSERT OR IGNORE INTO users (id) VALUES (?)", only_reserved)
    db.conn.executemany("INSERT OR IGNORE INTO users (id) VALUES (?)", only_download)

    credit = {cid: max(c or 0, 0) for cid, c, _ in reserved}
    vip = {cid for cid, _, v in reserved if v == 1}
    dl = {cid: n or 0 for cid, n in downloads}
    ids = [r[0] for r in db.conn.execute("SELECT id FROM users").fetchall()]
    db.conn.executemany(
        "UPDATE users SET credits = ?, vip_until = ?, downloads = ? WHERE id = ?",
        [(credit.get(i, 0), "9999-12-31" if i in vip else None, dl.get(i, 0), i) for i in ids],
    )


def migrate(old_path: Path, new_path: Path, dry_run: bool = False) -> tuple[dict, dict]:
    """Ritorna (prima, dopo). Con dry_run lavora su una copia e non scrive nulla."""
    old = _open_old(old_path)
    tmp = None
    target = new_path
    try:
        if dry_run:
            tmp = tempfile.mkdtemp(prefix="migrate-dry-")
            target = Path(tmp) / "bot.db"
            if new_path.exists():
                shutil.copyfile(new_path, target)
        db.init(target)
        before = summary()
        with db.conn:
            _copy_users(old)
        after = summary()
        return before, after
    finally:
        old.close()
        if db.conn is not None:
            db.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def old_totals(old_path: Path) -> dict[str, int]:
    old = _open_old(old_path)
    try:
        q = lambda sql: old.execute(sql).fetchone()[0] or 0  # noqa: E731
        return {
            "utenti": q("SELECT COUNT(*) FROM (SELECT chat_id FROM User UNION SELECT chat_id FROM Reserved "
                        "UNION SELECT chat_id FROM Download)"),
            "crediti": q("SELECT SUM(c) FROM (SELECT MAX(Credit) AS c FROM Reserved GROUP BY chat_id)"),
            "vip": q("SELECT COUNT(DISTINCT chat_id) FROM Reserved WHERE Vip = 1"),
            "download": q("SELECT SUM(n_download) FROM Download"),
        }
    finally:
        old.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old_db", type=Path)
    ap.add_argument("new_db", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="stampa il riepilogo senza scrivere")
    args = ap.parse_args(argv)

    src = old_totals(args.old_db)
    before, after = migrate(args.old_db, args.new_db, args.dry_run)
    print(f"{'DRY-RUN: nulla scritto' if args.dry_run else 'Migrazione completata'}")
    print(f"{'':10}{'vecchio':>10}{'nuovo prima':>13}{'nuovo dopo':>12}")
    for k in src:
        print(f"{k:10}{src[k]:>10}{before[k]:>13}{after[k]:>12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
