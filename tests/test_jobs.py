import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot import archive, db, jobs
from tests.support_inbox import restore_db_proxy

NOW = datetime(2026, 11, 6, 3, 0, 0)


def age(path: Path, days: float) -> None:
    t = (NOW - timedelta(days=days)).replace(tzinfo=UTC).timestamp()
    os.utime(path, (t, t))


class JobsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.s = SimpleNamespace(
            db_path=self.root / "bot.db", backups_dir=self.root / "backups",
            trash_dir=self.root / "trash", inbox_dir=self.root / "inbox",
            data_dir=self.root, bot_api_dir=self.root / "bot-api",
            staff_chat_id=-100111, log_chat_id=-100222, admin_ids=frozenset({1}))
        restore_db_proxy()
        db.init(self.s.db_path)
        for d in (self.s.trash_dir, self.s.inbox_dir):
            d.mkdir()
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        self.clock = lambda: NOW

    async def asyncTearDown(self):
        db.close()
        self.tmp.cleanup()

    def test_schedule_math(self):
        self.assertEqual(jobs.seconds_until_next(datetime(2026, 1, 1, 2, 0)), 3600)
        self.assertEqual(jobs.seconds_until_next(datetime(2026, 1, 1, 3, 0)), 86400)
        self.assertEqual(jobs.seconds_until_next(datetime(2026, 1, 1, 23, 0)), 4 * 3600)

    def test_is_due(self):
        self.assertTrue(jobs.is_due(None, NOW))
        self.assertTrue(jobs.is_due("2026-11-05 02:00:00", NOW))
        self.assertFalse(jobs.is_due("2026-11-05 12:00:00", NOW))

    async def test_trash_only_expired(self):
        old = self.s.trash_dir / "2026-09-01"
        new = self.s.trash_dir / "2026-11-01"
        odd_old = self.s.trash_dir / "misc"
        for d in (old, new, odd_old):
            (d / "sub").mkdir(parents=True)
            (d / "sub" / "f.txt").write_text("x")
        age(odd_old, 40)
        n = jobs.clean_trash(self.s.trash_dir, NOW)
        self.assertEqual(n, 2)
        self.assertFalse(old.exists())
        self.assertFalse(odd_old.exists())
        self.assertTrue(new.exists())

    async def test_backup_rotation_keeps_14(self):
        self.s.backups_dir.mkdir()
        for i in range(20):
            (self.s.backups_dir / f"bot-2026-10-{i + 1:02d}.db").write_text("x")
        jobs.backup_db(self.s.db_path, self.s.backups_dir, NOW)
        files = sorted(p.name for p in self.s.backups_dir.iterdir())
        self.assertEqual(len(files), 14)
        self.assertEqual(files[-1], "bot-2026-11-06.db")
        self.assertEqual(files[0], "bot-2026-10-08.db")
        # il backup è un DB valido
        import sqlite3
        c = sqlite3.connect(self.s.backups_dir / "bot-2026-11-06.db")
        c.execute("SELECT COUNT(*) FROM users").fetchone()
        c.close()

    async def test_inbox_deletes_only_inside_inbox(self):
        inside = self.s.inbox_dir / "1" / "a.pdf"
        inside.parent.mkdir()
        inside.write_text("x")
        outside = self.root / "precious.txt"
        outside.write_text("x")
        done = jobs.delete_inbox_files([str(inside), str(outside), "nonexistent.pdf"], self.s)
        self.assertEqual(len(done), 3)            # tutti sistemati: nessun retry
        self.assertFalse(inside.exists())
        self.assertTrue(outside.exists())

    async def test_inbox_path_kept_when_delete_fails(self):
        from bot.db import inbox
        db.upsert_user(5, "u", "U")
        ok, bad = self.s.inbox_dir / "1.pdf", self.s.inbox_dir / "2.pdf"
        for i, f in enumerate((ok, bad), 1):
            f.write_text("x")
            sid = inbox.create_submission(5, "F", f"U{i}", "a.pdf", 1, 7)
            inbox.set_file_info(sid, "h", str(f))
            db.conn.execute("UPDATE submissions SET status='rejected', at='2020-01-01 00:00:00' WHERE id=?", (sid,))
        db.conn.commit()
        real_unlink = Path.unlink

        def unlink(p, missing_ok=False):
            if p.name == "2.pdf":
                raise PermissionError("ro")
            real_unlink(p, missing_ok=missing_ok)
        with patch.object(Path, "unlink", unlink), \
             patch.object(jobs.inbox, "stale_pending", return_value=[]), \
             patch.object(jobs, "backup_db"), patch.object(archive, "load_from_db"):
            failures = await jobs.run_nightly(self.bot, self.s, self.clock)
        self.assertEqual(failures, [])
        self.assertFalse(ok.exists())
        self.assertEqual(inbox.expired_inbox_files(30), [str(bad)])   # si riprova domani

    async def test_nightly_and_startup_recover_orphans(self):
        rec = AsyncMock(return_value=(1, 0))
        with patch.object(jobs.submit, "recover_orphans", rec), patch.object(jobs, "backup_db"), \
             patch.object(archive, "load_from_db"):
            await jobs.run_nightly(self.bot, self.s, self.clock)
        rec.assert_awaited_once_with(self.bot, self.s)

    async def test_run_nightly_full(self):
        old_trash = self.s.trash_dir / "2026-01-01"
        old_trash.mkdir()
        db.upsert_user(1, "a", "A")
        db.conn.execute("INSERT INTO nodes (id, path, is_dir) VALUES (1, 'x', 1)")
        db.conn.execute("INSERT INTO downloads (user_id, node_id, at) VALUES (1, 1, '2024-01-01 00:00:00')")
        db.conn.execute("INSERT INTO downloads (user_id, node_id, at) VALUES (1, 1, '2026-10-01 00:00:00')")
        db.conn.commit()
        with patch.object(jobs.inbox, "expired_inbox_files", return_value=[]), \
             patch.object(jobs.inbox, "stale_pending", return_value=[4, 5]), \
             patch.object(archive, "load_from_db") as load:
            failures = await jobs.run_nightly(self.bot, self.s, self.clock)
        self.assertEqual(failures, [])
        self.assertFalse(old_trash.exists())
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0], 1)
        load.assert_called_once()
        self.assertEqual(db.kv_get("nightly_last"), "2026-11-06 03:00:00")
        self.assertEqual(self.bot.send_message.await_count, 1)  # solo il riepilogo staff
        self.assertEqual(self.bot.send_message.call_args.args[0], -100111)
        self.assertTrue((self.s.backups_dir / "bot-2026-11-06.db").exists())

    async def test_failing_step_does_not_block_others(self):
        old_trash = self.s.trash_dir / "2026-01-01"
        old_trash.mkdir()
        with patch.object(jobs, "backup_db", side_effect=RuntimeError("disco pieno")), \
             patch.object(jobs.inbox, "expired_inbox_files", side_effect=RuntimeError("boom")), \
             patch.object(jobs.inbox, "stale_pending", return_value=[]), \
             patch.object(archive, "load_from_db") as load:
            failures = await jobs.run_nightly(self.bot, self.s, self.clock)
        self.assertEqual(failures, ["backup", "inbox"])
        self.assertFalse(old_trash.exists())      # i passi dopo sono girati
        load.assert_called_once()
        self.assertEqual(db.kv_get("nightly_last"), "2026-11-06 03:00:00")
        chat_ids = [c.args[0] for c in self.bot.send_message.call_args_list]
        self.assertEqual(chat_ids, [-100222])     # avviso in LOG_CHAT_ID

    async def test_loop_runs_at_startup_if_due_then_sleeps(self):
        sleeps = []

        class Stop(Exception):
            pass

        async def fake_sleep(s):
            sleeps.append(s)
            raise Stop

        with patch.object(jobs, "run_nightly", AsyncMock(return_value=[])) as run, \
             patch.object(jobs.submit, "recover_orphans", AsyncMock(return_value=(0, 0))) as rec, \
             patch.object(jobs.admin, "notify_empty_index", AsyncMock()):
            with self.assertRaises(Stop):
                await jobs._loop(self.bot, self.s, self.clock, fake_sleep)
        run.assert_awaited_once()
        rec.assert_awaited_once()                 # recupero orfani all'avvio
        self.assertEqual(sleeps, [86400])
        # non dovuto: nessun giro all'avvio
        db.kv_set("nightly_last", "2026-11-05 20:00:00")
        with patch.object(jobs, "run_nightly", AsyncMock(return_value=[])) as run, \
             patch.object(jobs.admin, "notify_empty_index", AsyncMock()):
            with self.assertRaises(Stop):
                await jobs._loop(self.bot, self.s, self.clock, fake_sleep)
        run.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
