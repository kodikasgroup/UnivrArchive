import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests import support_inbox as S
from tests.support_inbox import FakeBot, FakeNode

from bot import db  # noqa: E402
from bot.db import inbox  # noqa: E402
from bot.handlers import manage  # noqa: E402
from bot.handlers.manage import ManageError, NeedPrice  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        S.new_db(self.tmp)
        self.s = S.make_settings(self.tmp)
        a = self.s.archive_dir
        (a / "INFORMATICA" / "RETI").mkdir(parents=True)
        (a / "INFORMATICA" / "RETI" / "esame.pdf").write_text("x")
        (a / "EXCLUSIVE" / "Anno3").mkdir(parents=True)
        (a / "EXCLUSIVE" / "Anno3" / "10.tema.pdf").write_text("y")
        (a / "EXCLUSIVE" / "Anno3" / "libero.pdf").write_text("z")

    def tearDown(self):
        db.conn.close()
        self._tmp.cleanup()

    def exists(self, rel: str) -> bool:
        return (self.s.archive_dir / rel).exists()


class OpsTests(Base):
    def test_mkdir(self):
        self.assertEqual(manage.op_mkdir(self.s, "INFORMATICA", "Nuova Cartella"), "INFORMATICA/Nuova Cartella")
        self.assertTrue(self.exists("INFORMATICA/Nuova Cartella"))
        with self.assertRaises(ManageError):
            manage.op_mkdir(self.s, "INFORMATICA", "Nuova Cartella")        # conflitto
        self.assertEqual(manage.op_mkdir(self.s, "", "Corso"), "Corso")      # radice

    def test_mkdir_unsafe_names(self):
        self.assertEqual(manage.op_mkdir(self.s, "INFORMATICA", "../../fuori"), "INFORMATICA/fuori")
        for bad in ("", "..", "///", "   "):
            with self.assertRaises(ManageError):
                manage.op_mkdir(self.s, "INFORMATICA", bad)
        self.assertFalse((self.tmp / "fuori").exists())

    def test_parent_outside_archive(self):
        with self.assertRaises(ManageError):
            manage.op_mkdir(self.s, "../..", "x")
        with self.assertRaises(ManageError):
            manage.op_delete(self.s, "../bot.db")

    def test_rename_free(self):
        new = manage.op_rename(self.s, "INFORMATICA/RETI/esame.pdf", False, 0, "Esame 2024.pdf")
        self.assertEqual(new, "INFORMATICA/RETI/Esame 2024.pdf")
        self.assertTrue(self.exists(new))
        self.assertFalse(self.exists("INFORMATICA/RETI/esame.pdf"))

    def test_rename_exclusive_keeps_price_prefix(self):
        new = manage.op_rename(self.s, "EXCLUSIVE/Anno3/10.tema.pdf", False, 10, "tema nuovo.pdf")
        self.assertEqual(new, "EXCLUSIVE/Anno3/10.tema nuovo.pdf")
        # una cartella sotto EXCLUSIVE non ha prefisso
        self.assertEqual(manage.op_rename(self.s, "EXCLUSIVE/Anno3", True, 0, "Anno4"), "EXCLUSIVE/Anno4")

    def test_rename_conflict_and_protected(self):
        (self.s.archive_dir / "INFORMATICA" / "RETI" / "b.pdf").write_text("b")
        with self.assertRaises(ManageError):
            manage.op_rename(self.s, "INFORMATICA/RETI/esame.pdf", False, 0, "b.pdf")
        self.assertEqual((self.s.archive_dir / "INFORMATICA/RETI/b.pdf").read_text(), "b")
        with self.assertRaises(ManageError):
            manage.op_rename(self.s, "EXCLUSIVE", True, 0, "altro")
        with self.assertRaises(ManageError):
            manage.op_delete(self.s, "EXCLUSIVE")

    def test_move_free_file_and_dir_rules(self):
        new = manage.op_move(self.s, "INFORMATICA/RETI/esame.pdf", False, "INFORMATICA")
        self.assertEqual(new, "INFORMATICA/esame.pdf")
        with self.assertRaises(ManageError):                       # cartella dentro se stessa
            manage.op_move(self.s, "INFORMATICA", True, "INFORMATICA/RETI")
        with self.assertRaises(ManageError):                       # cartella dentro EXCLUSIVE
            manage.op_move(self.s, "INFORMATICA/RETI", True, "EXCLUSIVE/Anno3")

    def test_move_into_exclusive_needs_price(self):
        with self.assertRaises(NeedPrice):
            manage.op_move(self.s, "INFORMATICA/RETI/esame.pdf", False, "EXCLUSIVE/Anno3")
        new = manage.op_move(self.s, "INFORMATICA/RETI/esame.pdf", False, "EXCLUSIVE/Anno3", 5)
        self.assertEqual(new, "EXCLUSIVE/Anno3/5.esame.pdf")

    def test_move_out_of_exclusive_strips_price(self):
        new = manage.op_move(self.s, "EXCLUSIVE/Anno3/10.tema.pdf", False, "INFORMATICA")
        self.assertEqual(new, "INFORMATICA/tema.pdf")

    def test_move_conflict_never_overwrites(self):
        (self.s.archive_dir / "INFORMATICA" / "esame.pdf").write_text("altro")
        with self.assertRaises(ManageError):
            manage.op_move(self.s, "INFORMATICA/RETI/esame.pdf", False, "INFORMATICA")
        self.assertEqual((self.s.archive_dir / "INFORMATICA/esame.pdf").read_text(), "altro")
        self.assertTrue(self.exists("INFORMATICA/RETI/esame.pdf"))

    def test_price_rewrites_prefix(self):
        self.assertEqual(manage.op_price(self.s, "EXCLUSIVE/Anno3/10.tema.pdf", False, 5),
                         "EXCLUSIVE/Anno3/5.tema.pdf")
        self.assertEqual(manage.op_price(self.s, "EXCLUSIVE/Anno3/libero.pdf", False, 20),
                         "EXCLUSIVE/Anno3/20.libero.pdf")
        with self.assertRaises(ManageError):
            manage.op_price(self.s, "INFORMATICA/RETI/esame.pdf", False, 5)   # fuori da EXCLUSIVE
        with self.assertRaises(ManageError):
            manage.op_price(self.s, "EXCLUSIVE/Anno3", True, 5)

    def test_delete_goes_to_trash_never_removed(self):
        t = manage.op_delete(self.s, "INFORMATICA/RETI/esame.pdf", today=date(2026, 11, 6))
        self.assertEqual(t, "2026-11-06/INFORMATICA/RETI/esame.pdf")
        self.assertTrue((self.s.trash_dir / t).is_file())
        self.assertEqual((self.s.trash_dir / t).read_text(), "x")
        self.assertFalse(self.exists("INFORMATICA/RETI/esame.pdf"))
        # stesso percorso eliminato due volte nello stesso giorno: nessuna sovrascrittura
        (self.s.archive_dir / "INFORMATICA/RETI/esame.pdf").write_text("seconda")
        t2 = manage.op_delete(self.s, "INFORMATICA/RETI/esame.pdf", today=date(2026, 11, 6))
        self.assertNotEqual(t, t2)
        self.assertEqual((self.s.trash_dir / t).read_text(), "x")

    def test_delete_folder(self):
        t = manage.op_delete(self.s, "INFORMATICA/RETI", today=date(2026, 11, 6))
        self.assertTrue((self.s.trash_dir / t / "esame.pdf").is_file())

    def test_missing_node(self):
        with self.assertRaises(ManageError):
            manage.op_delete(self.s, "INFORMATICA/NonEsiste")


class HandlerTests(Base):
    def setUp(self):
        super().setUp()
        S.set_tree(
            FakeNode(1, "INFORMATICA"), FakeNode(2, "INFORMATICA/RETI", parent_id=1),
            FakeNode(3, "INFORMATICA/RETI/esame.pdf", is_dir=False, parent_id=2),
            FakeNode(4, "EXCLUSIVE"), FakeNode(5, "EXCLUSIVE/Anno3", parent_id=4),
            FakeNode(6, "EXCLUSIVE/Anno3/10.tema.pdf", is_dir=False, parent_id=5, price=10))
        self.bot = FakeBot()

    def cb(self, data, chat=1, chat_type="private", mid=50):
        return S.make_callback(self.bot, data, S.make_message(self.bot, mid, chat, chat_type, from_id=0))

    def test_delete_requires_confirmation_then_moves(self):
        asyncio.run(manage.cb_delete(self.cb("adm:del:3"), self.s))
        self.assertTrue(self.exists("INFORMATICA/RETI/esame.pdf"))
        asyncio.run(manage.cb_delete(self.cb("adm:del:3:ok"), self.s))
        self.assertFalse(self.exists("INFORMATICA/RETI/esame.pdf"))
        self.assertEqual(len(list(self.s.trash_dir.rglob("esame.pdf"))), 1)

    def test_price_flow(self):
        asyncio.run(manage.cb_price(self.cb("adm:price:6:5"), self.s))
        self.assertTrue(self.exists("EXCLUSIVE/Anno3/5.tema.pdf"))

    def test_move_flow_via_negative_ctx(self):
        asyncio.run(manage.cb_move_dst(self.cb("dst:-3:1"), self.s))
        self.assertTrue(self.exists("INFORMATICA/esame.pdf"))

    def test_move_into_exclusive_asks_price_then_moves(self):
        asyncio.run(manage.cb_move_dst(self.cb("dst:-3:5"), self.s))
        self.assertTrue(self.exists("INFORMATICA/RETI/esame.pdf"))       # non ancora spostato
        asyncio.run(manage.cb_move_price(self.cb("adm:mvp:3:5:10"), self.s))
        self.assertTrue(self.exists("EXCLUSIVE/Anno3/10.esame.pdf"))

    def test_mkdir_during_moderation_sets_destination(self):
        S.add_user(5, "mario")
        sid = inbox.create_submission(5, "F", "U", "x.pdf", 1, 7)
        inbox.set_staff_message(sid, 900)

        class FakeState:
            def __init__(self, data):
                self.data = data
                self.cleared = False

            async def get_data(self):
                return self.data

            async def clear(self):
                self.cleared = True

        panel = S.make_message(self.bot, 900, -100, "supergroup", from_id=0)
        st = FakeState({"parent": "INFORMATICA", "panel": panel, "ctx": sid, "node_id": 1})
        msg = S.make_message(self.bot, 901, -100, "supergroup", from_id=1, text="Nuovo Corso")
        asyncio.run(manage.msg_mkdir(msg, st, self.bot, self.s))
        self.assertTrue(self.exists("INFORMATICA/Nuovo Corso"))
        self.assertEqual(inbox.get_submission(sid).dest_path, "INFORMATICA/Nuovo Corso")
        self.assertTrue(st.cleared)


if __name__ == "__main__":
    unittest.main()
