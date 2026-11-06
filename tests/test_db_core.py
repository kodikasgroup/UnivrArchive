import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bot import db
from bot.middlewares import UserMiddleware

TABLES = {"users", "nodes", "blobs", "purchases", "credit_log", "submissions",
          "favorites", "downloads", "tickets", "group_folders", "kv"}


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "bot.db"
        db.init(self.path)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(db.close)


class SchemaTest(DbTestCase):
    def test_tables_and_version(self):
        names = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(TABLES <= names)
        self.assertEqual(db.conn.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(db.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(db.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_init_idempotent(self):
        db.upsert_user(1, "a", "A")
        db.init(self.path)
        self.assertIsNotNone(db.get_user(1))

    def test_partial_unique_path_index(self):
        ins = "INSERT INTO nodes (path, is_dir, removed) VALUES (?, 0, ?)"
        with db.conn:
            db.conn.execute(ins, ("a/b.pdf", 1))
            db.conn.execute(ins, ("a/b.pdf", 0))
        with self.assertRaises(sqlite3.IntegrityError), db.conn:
            db.conn.execute(ins, ("a/b.pdf", 0))

    def test_migrations_applied_once(self):
        fake = ["", "CREATE TABLE extra (x INTEGER); INSERT INTO extra VALUES (1);"]
        with mock.patch.object(db, "MIGRATIONS", db.MIGRATIONS + fake[1:]):
            db.init(self.path)
            db.init(self.path)
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM extra").fetchone()[0], 1)
            self.assertEqual(db.conn.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_failed_migration_rolls_back(self):
        bad = "CREATE TABLE ok (x); INSERT INTO missing VALUES (1);"
        with mock.patch.object(db, "MIGRATIONS", db.MIGRATIONS + [bad]):
            with self.assertRaises(sqlite3.Error):
                db.init(self.path)
        db.init(self.path)
        self.assertEqual(db.conn.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertIsNone(db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ok'").fetchone())

    def test_newer_db_refused(self):
        db.conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(RuntimeError):
            db.init(self.path)


class UsersTest(DbTestCase):
    def test_upsert_and_get(self):
        db.upsert_user(1, "Ann", "Anna")
        u = db.get_user(1)
        self.assertEqual((u.username, u.first_name, u.credits, u.blocked), ("Ann", "Anna", 0, False))
        db.set_blocked(1, True)
        self.assertTrue(db.get_user(1).blocked)
        db.upsert_user(1, "Ann2", "Anna")
        u = db.get_user(1)
        self.assertEqual(u.username, "Ann2")
        self.assertFalse(u.blocked)
        self.assertIsNone(db.get_user(2))

    def test_find_user(self):
        db.upsert_user(1, "Mario", None)
        db.upsert_user(2, "dup", None)
        db.upsert_user(3, "DUP", None)
        self.assertEqual(db.find_user("1"), 1)
        self.assertIsNone(db.find_user("999"))
        self.assertEqual(db.find_user("@mario"), 1)
        self.assertEqual(db.find_user("@MARIO"), 1)
        self.assertIsNone(db.find_user("@nessuno"))
        self.assertEqual(db.find_user("@dup"), "ambiguous")

    def test_add_credits(self):
        db.upsert_user(1, None, None)
        self.assertTrue(db.add_credits(1, 5, "admin:9:test"))
        self.assertFalse(db.add_credits(1, -6, "purchase:1"))
        self.assertTrue(db.add_credits(1, -5, "purchase:1"))
        self.assertEqual(db.get_user(1).credits, 0)
        log = db.conn.execute("SELECT delta, reason FROM credit_log ORDER BY id").fetchall()
        self.assertEqual(log, [(5, "admin:9:test"), (-5, "purchase:1")])

    def test_add_credits_unknown_user(self):
        self.assertFalse(db.add_credits(42, 5, "x"))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM credit_log").fetchone()[0], 0)

    def test_vip(self):
        db.upsert_user(1, None, None)
        self.assertFalse(db.is_vip(1))
        first = db.grant_vip(1, 30)
        self.assertTrue(db.is_vip(1))
        second = db.grant_vip(1, 30)
        d1 = datetime.strptime(first, "%Y-%m-%d %H:%M:%S")
        d2 = datetime.strptime(second, "%Y-%m-%d %H:%M:%S")
        self.assertEqual(d2 - d1, timedelta(days=30))
        db.revoke_vip(1)
        self.assertFalse(db.is_vip(1))
        self.assertIsNone(db.get_user(1).vip_until)

    def test_vip_expired_restarts_from_now(self):
        db.upsert_user(1, None, None)
        db.conn.execute("UPDATE users SET vip_until = '2000-01-01 00:00:00' WHERE id = 1")
        self.assertFalse(db.is_vip(1))
        new = datetime.strptime(db.grant_vip(1, 1), "%Y-%m-%d %H:%M:%S")
        delta = new - datetime.now(timezone.utc).replace(tzinfo=None)
        self.assertLess(abs(delta - timedelta(days=1)), timedelta(minutes=1))

    def test_vip_permanent(self):
        db.upsert_user(1, None, None)
        self.assertEqual(db.grant_vip(1, 0), "9999-12-31")
        self.assertTrue(db.is_vip(1))
        self.assertEqual(db.grant_vip(1, 30), "9999-12-31")

    def test_kv(self):
        self.assertIsNone(db.kv_get("k"))
        db.kv_set("k", "a")
        db.kv_set("k", "b")
        self.assertEqual(db.kv_get("k"), "b")

    def test_conn_proxy_import_before_init(self):
        db.close()
        with self.assertRaises(RuntimeError):
            db.conn.execute("SELECT 1")
        db.init(self.path)
        self.assertEqual(db.conn.execute("SELECT 1").fetchone()[0], 1)


class MiddlewareTest(DbTestCase):
    def run_mw(self, mw, user):
        async def handler(event, data):
            return "ok"
        return asyncio.run(mw(handler, object(), {"event_from_user": user}))

    def test_upsert_once_per_hour(self):
        mw = UserMiddleware()
        u = SimpleNamespace(id=7, username="u", first_name="U", is_bot=False)
        with mock.patch.object(db, "upsert_user", wraps=db.upsert_user) as up:
            self.assertEqual(self.run_mw(mw, u), "ok")
            self.run_mw(mw, u)
            self.assertEqual(up.call_count, 1)
            mw._seen[7] -= 4000
            self.run_mw(mw, u)
            self.assertEqual(up.call_count, 2)
        self.assertEqual(db.get_user(7).username, "u")

    def test_db_error_does_not_block(self):
        mw = UserMiddleware()
        u = SimpleNamespace(id=8, username=None, first_name=None, is_bot=False)
        with mock.patch.object(db, "upsert_user", side_effect=sqlite3.OperationalError("boom")):
            self.assertEqual(self.run_mw(mw, u), "ok")
        self.assertNotIn(8, mw._seen)

    def test_no_user(self):
        self.assertEqual(self.run_mw(UserMiddleware(), None), "ok")


if __name__ == "__main__":
    unittest.main()
