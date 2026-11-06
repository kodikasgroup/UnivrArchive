import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bot import db
from scripts import migrate_old_db as mig


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = root / "old.db"
        self.new = root / "new.db"
        c = sqlite3.connect(self.old)
        c.executescript("""
            CREATE TABLE User (chat_id INTEGER, username TEXT, f_name TEXT, state TEXT);
            CREATE TABLE Reserved (chat_id INTEGER, Credit INTEGER, Vip INTEGER);
            CREATE TABLE Download (chat_id INTEGER, n_download INTEGER);
            INSERT INTO User VALUES (1, 'uno', 'Uno', '2026-10-01 10:00:00');
            INSERT INTO User VALUES (1, 'uno_dup', 'Uno bis', '2026-10-02 10:00:00');
            INSERT INTO User VALUES (2, NULL, 'Due', '2026-09-01 10:00:00');
            INSERT INTO Reserved VALUES (1, 5, 0);
            INSERT INTO Reserved VALUES (1, 8, 0);
            INSERT INTO Reserved VALUES (2, 3, 1);
            INSERT INTO Reserved VALUES (3, 12, 1);       -- solo in Reserved
            INSERT INTO Download VALUES (1, 4);
            INSERT INTO Download VALUES (1, 6);
            INSERT INTO Download VALUES (4, 7);           -- solo in Download
        """)
        c.commit()
        c.close()

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        c = sqlite3.connect(self.new)
        r = c.execute("SELECT id, username, credits, vip_until, downloads, last_seen FROM users ORDER BY id").fetchall()
        c.close()
        return r

    def test_migration_results(self):
        before_hash = digest(self.old)
        before, after = mig.migrate(self.old, self.new)
        self.assertEqual(before["utenti"], 0)
        self.assertEqual(after, {"utenti": 4, "crediti": 23, "vip": 2, "download": 17})
        self.assertEqual(self.rows(), [
            (1, "uno", 8, None, 10, "2026-10-01 10:00:00"),
            (2, None, 3, "9999-12-31", 0, "2026-09-01 10:00:00"),
            (3, None, 12, "9999-12-31", 0, None),
            (4, None, 0, None, 7, None),
        ])
        self.assertEqual(digest(self.old), before_hash)  # vecchio DB intatto

    def test_idempotent(self):
        mig.migrate(self.old, self.new)
        first = self.rows()
        before, after = mig.migrate(self.old, self.new)
        self.assertEqual(before, after)
        self.assertEqual(self.rows(), first)

    def test_dry_run_writes_nothing(self):
        before, after = mig.migrate(self.old, self.new, dry_run=True)
        self.assertEqual(after["utenti"], 4)
        self.assertFalse(self.new.exists())

    def test_old_db_opened_read_only(self):
        c = mig._open_old(self.old)
        with self.assertRaises(sqlite3.OperationalError):
            c.execute("INSERT INTO User VALUES (9, 'x', 'x', 'x')")
        c.close()

    def test_main_prints_summary(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mig.main([str(self.old), str(self.new), "--dry-run"]), 0)
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertIn("utenti", out.getvalue())

    def test_totals_old(self):
        self.assertEqual(mig.old_totals(self.old), {"utenti": 4, "crediti": 23, "vip": 2, "download": 17})


if __name__ == "__main__":
    unittest.main()
