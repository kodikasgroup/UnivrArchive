import asyncio
import tempfile
import unittest
from pathlib import Path

from aiogram.types import User

from tests import support_inbox as S
from tests.support_inbox import FakeBot, FakeNode

from bot import db  # noqa: E402
from bot.db import inbox  # noqa: E402
from bot.handlers import tickets  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        S.new_db(self.tmp)
        S.add_user(5, "mario")
        self.s = S.make_settings(self.tmp)
        S.set_tree(FakeNode(9, "INFORMATICA/RETI/esame.pdf", is_dir=False))
        self.bot = FakeBot()
        self.user = User(id=5, is_bot=False, first_name="Mario", username="mario")

    def tearDown(self):
        db.close()
        self._tmp.cleanup()

    def open(self, kind="feedback", text="ciao <b>", node_id=None) -> int:
        return asyncio.run(tickets.open_ticket(self.bot, self.s, self.user, kind, text, node_id))


class OpenTests(Base):
    def test_open_ticket_posts_card_and_maps_staff_message(self):
        tid = self.open()
        sent = self.bot.of("SendMessage")[0]
        self.assertEqual(sent.chat_id, -100)
        self.assertIn("&lt;b&gt;", sent.text)                          # HTML escapato
        self.assertEqual(sent.reply_markup.inline_keyboard[0][0].callback_data, f"tk:{tid}:ok")
        t = inbox.get_ticket(tid)
        self.assertEqual((t.kind, t.status, t.user_id), ("feedback", "open", 5))
        self.assertEqual(inbox.get_ticket_by_staff_message(t.staff_message_id).id, tid)
        self.assertGreater(t.staff_message_id, 0)

    def test_report_with_node(self):
        tid = self.open("report", None, 9)
        self.assertIn("INFORMATICA/RETI/esame.pdf", self.bot.of("SendMessage")[0].text)
        self.assertEqual(inbox.get_ticket(tid).node_id, 9)

    def test_staff_send_failure_removes_row(self):
        self.bot.fail_all = True
        with self.assertRaises(RuntimeError):
            self.open()
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)

    def test_commands(self):
        class Cmd:
            args = "il bot è bello"

        msg = S.make_message(self.bot, 1, 5, "private", from_id=5, text="/feedback il bot è bello")
        asyncio.run(tickets.cmd_feedback(msg, Cmd(), self.bot, self.s))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 1)

        class Empty:
            args = None

        before = len(self.bot.calls)
        asyncio.run(tickets.cmd_feedback(msg, Empty(), self.bot, self.s))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 1)
        self.assertGreater(len(self.bot.calls), before)               # istruzioni inviate

    def test_removal_extracts_node_link(self):
        class Cmd:
            args = "https://t.me/bot?start=f_9 sono l'autore"

        msg = S.make_message(self.bot, 1, 5, "private", from_id=5, text="/rimozione x")
        asyncio.run(tickets.cmd_removal(msg, Cmd(), self.bot, self.s))
        t = inbox.get_ticket(1)
        self.assertEqual((t.kind, t.node_id), ("removal", 9))


class ReplyTests(Base):
    def reply_msg(self, to_mid: int, from_id=1, chat=-100):
        m = S.make_message(self.bot, 700, chat, "supergroup", from_id=from_id, text="risposta",
                           reply_to={"message_id": to_mid, "date": 0, "chat": {"id": chat, "type": "supergroup"}})
        return m

    def check(self, msg):
        return asyncio.run(tickets._is_staff_ticket_reply(msg, self.s))

    def test_admin_reply_forwarded_to_user(self):
        tid = self.open()
        t = inbox.get_ticket(tid)
        res = self.check(self.reply_msg(t.staff_message_id))
        self.assertTrue(res)
        asyncio.run(tickets.staff_reply(self.reply_msg(t.staff_message_id), self.bot, res["ticket"]))
        sends = [c for c in self.bot.of("SendMessage") if c.chat_id == 5]
        copies = self.bot.of("CopyMessage")
        self.assertEqual(len(sends), 1)
        self.assertIn("Risposta dello staff", sends[0].text)
        self.assertEqual((copies[0].chat_id, copies[0].from_chat_id), (5, -100))

    def test_non_admin_and_other_chat_ignored(self):
        t = inbox.get_ticket(self.open())
        self.assertFalse(self.check(self.reply_msg(t.staff_message_id, from_id=77)))
        self.assertFalse(self.check(self.reply_msg(t.staff_message_id, chat=-555)))

    def test_reply_to_submission_card_ignored(self):
        sid = inbox.create_submission(5, "F", "U", "a.pdf", 1, 3)
        inbox.set_staff_message(sid, 321)
        self.assertFalse(self.check(self.reply_msg(321)))

    def test_closed_ticket_reply_refused(self):
        tid = self.open()
        t = inbox.get_ticket(tid)
        cb = S.make_callback(self.bot, f"tk:{tid}:ok",
                             S.make_message(self.bot, t.staff_message_id, -100, "supergroup", from_id=0, text="card"))
        asyncio.run(tickets.cb_close(cb))
        closed = inbox.get_ticket(tid)
        self.assertEqual((closed.status, closed.closed_by), ("closed", 1))
        res = self.check(self.reply_msg(t.staff_message_id))
        before = len(self.bot.of("CopyMessage"))
        asyncio.run(tickets.staff_reply(self.reply_msg(t.staff_message_id), self.bot, res["ticket"]))
        self.assertEqual(len(self.bot.of("CopyMessage")), before)
        self.assertEqual(self.bot.of("SendMessage")[-1].text, "Ticket chiuso")   # reply all'admin

    def test_close_twice(self):
        tid = self.open()
        self.assertTrue(inbox.close_ticket(tid, 1))
        self.assertFalse(inbox.close_ticket(tid, 2))
        self.assertEqual(inbox.get_ticket(tid).closed_by, 1)


if __name__ == "__main__":
    unittest.main()
