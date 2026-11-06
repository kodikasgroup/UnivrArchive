import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import GetMe

from bot import archive, db
from bot.db import stats
from bot.handlers import admin
from bot.texts import admin as T


def make_preview(**kw) -> archive.Preview:
    base = dict(created_at=datetime(2026, 1, 1), added=[], modified=[], moved=[], removed=[],
                price_changed=[], hidden_no_price=[], hidden_over_max=[], exclusive_leaks=[],
                removed_with_purchases=[], in_copy=[], over_50mb=[])
    base.update(kw)
    return archive.Preview(**base)


class PreviewTextTest(unittest.TestCase):
    def test_empty(self):
        self.assertTrue(make_preview().is_empty)

    def test_300_files_40_folders_fits(self):
        added = [f"INFORMATICA/Anno {i % 40}/Corso con nome molto lungo {i % 40}/file_{i}.pdf" for i in range(300)]
        long = "EXCLUSIVE/" + "x" * 190 + ".pdf"
        p = make_preview(
            added=added, modified=[long] * 9, removed=[long + str(i) for i in range(50)],
            moved=[(long, long)] * 30, hidden_no_price=[long] * 20,
            hidden_over_max=[(long, 99)] * 20, exclusive_leaks=[(long, long)] * 20,
            price_changed=[(long, 1, 2)] * 20, over_50mb=[long] * 20, in_copy=["a"] * 3,
            removed_with_purchases=[long] * 20)
        text = T.reindex_preview(p)
        self.assertLessEqual(len(text), 4096)
        self.assertIn("+300 file", text)
        self.assertIn("−50 rimossi", text)

    def test_simple_300_files(self):
        added = [f"A/Cartella {i % 40}/f{i}.pdf" for i in range(300)]
        text = T.reindex_preview(make_preview(added=added))
        self.assertLessEqual(len(text), 4096)
        self.assertIn("+300 file", text)

    def test_details_capped_at_five(self):
        p = make_preview(removed=[f"a/{i}.pdf" for i in range(8)])
        text = T.reindex_preview(p)
        self.assertEqual(text.count(".pdf</code>"), 5)
        self.assertIn("…e altri 3", text)

    def test_html_escaped(self):
        text = T.reindex_preview(make_preview(removed=["a/<b>&.pdf"]))
        self.assertIn("&lt;b&gt;&amp;", text)


def fake_msg():
    m = MagicMock()
    m.edit_text = AsyncMock()
    m.answer = AsyncMock()
    m.chat.id = 1
    m.from_user.id = 1
    return m


class ReindexTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init(Path(self.tmp.name) / "bot.db")
        self.bot = MagicMock()
        self.status = fake_msg()
        self.bot.send_message = AsyncMock(return_value=self.status)
        self.settings = SimpleNamespace()

    async def asyncTearDown(self):
        db.close()
        self.tmp.cleanup()

    async def test_empty_preview_frees_lock(self):
        with patch.object(archive, "start_reindex", AsyncMock(return_value=make_preview())), \
             patch.object(archive, "cancel_reindex") as cancel:
            await admin._run_reindex(self.bot, self.settings, 1, 1)
        cancel.assert_called_once_with(1)
        self.assertEqual(self.status.edit_text.call_args.args[0], T.REINDEX_NONE)

    async def test_preview_with_buttons(self):
        with patch.object(archive, "start_reindex", AsyncMock(return_value=make_preview(added=["a/b.pdf"]))):
            await admin._run_reindex(self.bot, self.settings, 1, 1)
        kb = self.status.edit_text.call_args.kwargs["reply_markup"]
        self.assertEqual([b.callback_data for b in kb.inline_keyboard[0]], ["rx:ok", "rx:no"])

    async def test_busy(self):
        db.upsert_user(7, "capo", "Capo")
        with patch.object(archive, "start_reindex", AsyncMock(side_effect=archive.ReindexBusy(7))):
            await admin._run_reindex(self.bot, self.settings, 1, 1)
        self.assertIn("già in corso da @capo", self.status.edit_text.call_args.args[0])

    async def test_apply_expired_and_changed(self):
        call = MagicMock(); call.answer = AsyncMock(); call.message = fake_msg(); call.from_user.id = 1
        with patch.object(archive, "apply_reindex", AsyncMock(side_effect=archive.PreviewExpired())):
            await admin.cb_reindex_apply(call, self.bot, self.settings)
        self.assertEqual(call.message.edit_text.call_args.args[0], T.REINDEX_EXPIRED)
        newp = make_preview(added=["x/y.pdf"])
        with patch.object(archive, "apply_reindex", AsyncMock(side_effect=archive.DiskChanged(newp))):
            await admin.cb_reindex_apply(call, self.bot, self.settings)
        self.assertIn("+1 file", call.message.edit_text.call_args.args[0])

    async def test_apply_ok_starts_upload_with_progress(self):
        call = MagicMock(); call.answer = AsyncMock(); call.message = fake_msg(); call.from_user.id = 1
        res = archive.ApplyResult(added=12, modified=1, moved=0, removed=3, to_upload=25)
        seen = {}

        def fake_upload(bot, settings, progress):
            seen["progress"] = progress
        with patch.object(archive, "apply_reindex", AsyncMock(return_value=res)), \
             patch.object(admin.storage, "resume_background_upload", fake_upload):
            await admin.cb_reindex_apply(call, self.bot, self.settings)
        self.assertIn("+12 file, 1 modificato, 3 rimossi", call.message.edit_text.call_args.args[0])
        call.message.edit_text.reset_mock()
        for done in range(1, 26):
            await seen["progress"](done, 25)
        self.assertEqual(call.message.edit_text.await_count, 3)  # 10, 20, 25
        self.assertIn("⬆️ Caricati 25/25", call.message.edit_text.call_args.args[0])


class BroadcastTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init(Path(self.tmp.name) / "bot.db")
        for i in range(1, 6):
            db.upsert_user(i, f"u{i}", f"U{i}")
        db.set_blocked(5, True)

    async def asyncTearDown(self):
        db.close()
        self.tmp.cleanup()

    async def test_recipients_exclude_blocked(self):
        self.assertEqual(stats.broadcast_recipients(), [1, 2, 3, 4])

    async def test_retry_forbidden_and_blocked_users(self):
        calls = []
        retried = {"done": False}

        async def copy_message(chat_id, from_chat_id, message_id):
            calls.append(chat_id)
            if chat_id == 3 and not retried["done"]:
                retried["done"] = True
                raise TelegramRetryAfter(GetMe(), "flood", 7)
            if chat_id == 2:
                raise TelegramForbiddenError(GetMe(), "blocked")
            if chat_id == 4:
                raise RuntimeError("rete")
        bot = MagicMock()
        bot.copy_message = copy_message
        sleeps = []

        async def fake_sleep(s):
            sleeps.append(s)
        notes = []

        async def notify(t):
            notes.append(t)
        res = await admin.run_broadcast(bot, stats.broadcast_recipients(), 99, 5, notify, sleep=fake_sleep)
        self.assertEqual(calls, [1, 2, 3, 3, 4])      # utente 3 ritentato, 5 escluso
        self.assertIn(7, sleeps)
        self.assertEqual((res.sent, res.blocked, res.errors), (2, 1, 1))
        self.assertTrue(db.get_user(2).blocked)
        self.assertIsNotNone(db.get_user(4))          # errori generici: niente cancellazioni
        self.assertIn("Inviati: 2", notes[-1])

    async def test_progress_every_100(self):
        for i in range(100, 350):
            db.upsert_user(i, None, None)
        bot = MagicMock()
        bot.copy_message = AsyncMock()
        notes = []

        async def notify(t):
            notes.append(t)

        async def nosleep(s):
            pass
        recipients = stats.broadcast_recipients()
        await admin.run_broadcast(bot, recipients, 1, 1, notify, sleep=nosleep)
        self.assertEqual(len(notes), len(recipients) // 100 + 1)


class CommandsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init(Path(self.tmp.name) / "bot.db")
        db.upsert_user(10, "mario", "Mario")
        db.upsert_user(11, "Dup", "A")
        db.upsert_user(12, "dup", "B")
        db.add_credits(10, 5, "x")
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        self.msg = fake_msg()
        self.msg.from_user.id = 1

    async def asyncTearDown(self):
        db.close()
        self.tmp.cleanup()

    def cmd(self, args):
        return SimpleNamespace(args=args)

    def reply(self):
        return self.msg.answer.call_args.args[0]

    async def test_credits_ok_and_log(self):
        await admin.cmd_credits_add(self.msg, self.cmd("@mario 3 premio test"), self.bot)
        self.assertEqual(db.get_user(10).credits, 8)
        r = db.conn.execute("SELECT reason FROM credit_log ORDER BY id DESC").fetchone()[0]
        self.assertEqual(r, "admin:1:premio test")
        self.bot.send_message.assert_awaited()

    async def test_credits_ambiguous(self):
        await admin.cmd_credits_add(self.msg, self.cmd("@dup 3"), self.bot)
        self.assertEqual(self.reply(), T.USER_AMBIGUOUS)

    async def test_credits_not_found(self):
        await admin.cmd_credits_add(self.msg, self.cmd("999 3"), self.bot)
        self.assertEqual(self.reply(), T.USER_NOT_FOUND)
        await admin.cmd_credits_add(self.msg, self.cmd("@nessuno 3"), self.bot)
        self.assertEqual(self.reply(), T.USER_NOT_FOUND)

    async def test_credits_negative_beyond_balance(self):
        await admin.cmd_credits_add(self.msg, self.cmd("10 -9"), self.bot)
        self.assertEqual(self.reply(), T.credits_insufficient(-9))
        self.assertEqual(db.get_user(10).credits, 5)

    async def test_credits_usage(self):
        for a in (None, "10", "10 abc", "10 0"):
            await admin.cmd_credits_add(self.msg, self.cmd(a), self.bot)
            self.assertEqual(self.reply(), T.CREDITS_USAGE)

    async def test_vip(self):
        await admin.cmd_vip(self.msg, self.cmd("10 0"))
        self.assertIn("permanente", self.reply())
        await admin.cmd_vip(self.msg, self.cmd("10 off"))
        self.assertIsNone(db.get_user(10).vip_until)
        await admin.cmd_vip(self.msg, self.cmd("10 30"))
        self.assertIn("fino al", self.reply())
        await admin.cmd_vip(self.msg, self.cmd("10 boh"))
        self.assertEqual(self.reply(), T.VIP_USAGE)

    async def test_stats_text(self):
        db.conn.execute("UPDATE users SET downloads = 4 WHERE id = 10")
        db.conn.commit()
        await admin.cmd_stats(self.msg)
        text = self.reply()
        self.assertIn("Utenti: 3", text)
        self.assertIn("4 totali", text)

    async def test_pending_links(self):
        settings = SimpleNamespace(staff_chat_id=-1001234567890)
        with patch.object(admin.inbox, "list_pending", return_value=[(1, 55, "a<b>.pdf")]), \
             patch.object(admin.inbox, "count_pending", return_value=1):
            await admin.cmd_pending(self.msg, settings)
        text = self.reply()
        self.assertIn("https://t.me/c/1234567890/55", text)
        self.assertIn("a&lt;b&gt;.pdf", text)

    async def test_notify_empty_index(self):
        settings = SimpleNamespace(admin_ids=frozenset({1, 2}))
        await admin.notify_empty_index(self.bot, settings)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.bot.send_message.reset_mock()
        db.conn.execute("INSERT INTO nodes (path, is_dir) VALUES ('a', 1)")
        await admin.notify_empty_index(self.bot, settings)
        self.bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
