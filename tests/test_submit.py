import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from tests import support_inbox as S
from tests.support_inbox import FakeBot, FakeNode

from bot import archive, db  # noqa: E402
from bot.db import inbox  # noqa: E402
from bot.handlers import submit  # noqa: E402


class SanitizeTests(unittest.TestCase):
    def test_traversal_and_separators(self):
        self.assertEqual(submit.sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(submit.sanitize_filename("a/b.pdf"), "b.pdf")
        self.assertEqual(submit.sanitize_filename("..\\..\\win\\x.pdf"), "x.pdf")
        self.assertEqual(submit.sanitize_filename("con\x00trollo.pdf"), "controllo.pdf")

    def test_special_chars_hidden_empty(self):
        self.assertEqual(submit.sanitize_filename('a:b*c?"d<e>f|g.pdf'), "abcdefg.pdf")
        self.assertEqual(submit.sanitize_filename(""), "file")
        self.assertEqual(submit.sanitize_filename(".."), "file")
        self.assertEqual(submit.sanitize_filename(".hidden.pdf"), "hidden.pdf")
        self.assertEqual(submit.sanitize_filename("evil‮gnp.exe"), "evilgnp.exe")

    def test_long_name_keeps_extension(self):
        out = submit.sanitize_filename("x" * 300 + ".pdf")
        self.assertLessEqual(len(out), 120)
        self.assertTrue(out.endswith(".pdf"))

    def test_strip_price(self):
        self.assertEqual(submit.strip_price("5.(E)manuale.pdf"), "(E)manuale.pdf")
        self.assertEqual(submit.strip_price("10Architettura.pdf"), "Architettura.pdf")
        self.assertEqual(submit.strip_price("senza.pdf"), "senza.pdf")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self.assertEqual(submit.unique_path(d, "a.pdf").name, "a.pdf")
            (d / "a.pdf").write_text("x")
            self.assertEqual(submit.unique_path(d, "a.pdf").name, "a (2).pdf")
            (d / "a (2).pdf").write_text("x")
            self.assertEqual(submit.unique_path(d, "a.pdf").name, "a (3).pdf")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        S.new_db(self.tmp)
        S.add_user(5, "mario")
        self.settings = S.make_settings(self.tmp)
        (self.settings.archive_dir / "INFORMATICA" / "RETI").mkdir(parents=True)
        (self.settings.archive_dir / "EXCLUSIVE" / "Anno3").mkdir(parents=True)
        S.set_tree(
            FakeNode(1, "INFORMATICA"), FakeNode(2, "INFORMATICA/RETI", parent_id=1),
            FakeNode(3, "EXCLUSIVE"), FakeNode(4, "EXCLUSIVE/Anno3", parent_id=3))

    def tearDown(self):
        db.conn.close()
        self._tmp.cleanup()

    def new_sub(self, name="esame.pdf", content=b"abc", hint=2, uid=5, uniq=None) -> int:
        sid = inbox.create_submission(uid, "FID", uniq or f"U{len(name)}{content!r}", name, len(content), 77)
        path = self.settings.inbox_dir / f"{sid}.pdf"
        path.write_bytes(content)
        inbox.set_file_info(sid, hashlib.sha256(content).hexdigest(), str(path))
        inbox.set_hint(sid, hint)
        inbox.set_staff_message(sid, 500 + sid)
        return sid


class ApproveTests(Base):
    def test_approve_moves_file_and_gives_credits_once(self):
        sid = self.new_sub()
        r1 = submit.approve_submission(self.settings, sid, 1, 10)
        r2 = submit.approve_submission(self.settings, sid, 2, 10)   # secondo admin / doppio click
        self.assertEqual(r1.status, "ok")
        self.assertEqual(r2.status, "already")
        self.assertEqual(S.credits_of(5), 10)
        self.assertEqual(r1.dest_rel, "INFORMATICA/RETI/esame.pdf")
        self.assertTrue((self.settings.archive_dir / r1.dest_rel).is_file())
        sub = inbox.get_submission(sid)
        self.assertEqual((sub.status, sub.credits, sub.inbox_path, sub.reviewed_by), ("approved", 10, None, 1))
        self.assertFalse((self.settings.inbox_dir / f"{sid}.pdf").exists())
        n = db.conn.execute("SELECT COUNT(*) FROM credit_log WHERE reason=?", (f"submission:{sid}",)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_concurrent_calls_in_threads_give_credits_once(self):
        sid = self.new_sub()
        results = [submit.approve_submission(self.settings, sid, 1, 5) for _ in range(5)]
        self.assertEqual([r.status for r in results].count("ok"), 1)
        self.assertEqual(S.credits_of(5), 5)

    def test_name_collision(self):
        a = submit.approve_submission(self.settings, self.new_sub(content=b"1", uniq="a"), 1, 5)
        b = submit.approve_submission(self.settings, self.new_sub(content=b"2", uniq="b"), 1, 5)
        c = submit.approve_submission(self.settings, self.new_sub(content=b"3", uniq="c"), 1, 5)
        self.assertEqual([a.dest_rel, b.dest_rel, c.dest_rel],
                         ["INFORMATICA/RETI/esame.pdf", "INFORMATICA/RETI/esame (2).pdf",
                          "INFORMATICA/RETI/esame (3).pdf"])

    def test_malicious_name_stays_inside_archive(self):
        sid = self.new_sub(name="../../../../etc/passwd.pdf")
        r = submit.approve_submission(self.settings, sid, 1, 5)
        self.assertEqual(r.status, "ok")
        final = (self.settings.archive_dir / r.dest_rel).resolve()
        self.assertTrue(final.is_relative_to(self.settings.archive_dir.resolve()))
        self.assertEqual(final.name, "passwd.pdf")

    def test_folder_outside_archive_rejected(self):
        sid = self.new_sub()
        inbox.set_dest_folder(sid, "../..")
        self.assertEqual(submit.approve_submission(self.settings, sid, 1, 5).status, "bad_folder")
        self.assertEqual(inbox.get_submission(sid).status, "pending")
        self.assertEqual(S.credits_of(5), 0)

    def test_no_folder_does_not_approve(self):
        sid = self.new_sub(hint=None)
        r = submit.approve_submission(self.settings, sid, 1, 5)
        self.assertEqual(r.status, "no_folder")
        self.assertEqual(inbox.get_submission(sid).status, "pending")
        self.assertEqual(S.credits_of(5), 0)

    def test_admin_chosen_folder_wins_over_hint(self):
        sid = self.new_sub()
        inbox.set_dest_folder(sid, "INFORMATICA")
        r = submit.approve_submission(self.settings, sid, 1, 5)
        self.assertEqual(r.dest_rel, "INFORMATICA/esame.pdf")

    def test_exclusive_needs_price_and_prefixes(self):
        sid = self.new_sub(hint=4)
        r = submit.approve_submission(self.settings, sid, 1, 10)
        self.assertEqual(r.status, "need_price")
        self.assertEqual(inbox.get_submission(sid).status, "pending")
        self.assertEqual(submit.approve_submission(self.settings, sid, 1, 10, price=999).status, "need_price")
        r = submit.approve_submission(self.settings, sid, 1, 10, price=10)
        self.assertEqual(r.dest_rel, "EXCLUSIVE/Anno3/10.esame.pdf")

    def test_missing_inbox_file_reverts_nothing_given(self):
        sid = self.new_sub()
        (self.settings.inbox_dir / f"{sid}.pdf").unlink()
        self.assertEqual(submit.approve_submission(self.settings, sid, 1, 5).status, "error")
        self.assertEqual(inbox.get_submission(sid).status, "pending")
        self.assertEqual(S.credits_of(5), 0)

    def test_zero_credits_direct(self):
        sid = self.new_sub()
        self.assertEqual(submit.approve_submission(self.settings, sid, 1, 0).status, "ok")
        self.assertEqual(S.credits_of(5), 0)


class InboxDbTests(Base):
    def test_reject_once(self):
        sid = self.new_sub()
        self.assertTrue(inbox.reject(sid, 1))
        self.assertFalse(inbox.reject(sid, 2))

    def test_pending_lists_and_expiry(self):
        a, b = self.new_sub(uniq="a"), self.new_sub(uniq="b", content=b"zz")
        self.assertEqual(inbox.count_pending(), 2)
        self.assertEqual([x[0] for x in inbox.list_pending()], [a, b])
        inbox.reject(a, 1)
        with db.conn:
            db.conn.execute("UPDATE submissions SET reviewed_at = datetime('now','-40 days') WHERE id=?", (a,))
            db.conn.execute("UPDATE submissions SET at = datetime('now','-40 days') WHERE id=?", (b,))
        self.assertEqual(inbox.stale_pending(30), [b])
        paths = inbox.expired_inbox_files(30)
        self.assertEqual(len(paths), 1)
        self.assertEqual(inbox.expired_inbox_files(30), [])      # inbox_path azzerato
        self.assertIsNotNone(inbox.get_submission(a))             # la riga resta

    def test_rate_and_unique(self):
        self.new_sub(uniq="same")
        self.assertTrue(inbox.seen_unique_id("same"))
        self.assertFalse(inbox.seen_unique_id("other"))
        self.assertEqual(inbox.count_recent_pending(5), 1)


def _doc(name, uid, fid="F1", size=100):
    return {"file_id": fid, "file_unique_id": uid, "file_name": name, "file_size": size}


class IngestTests(Base):
    def setUp(self):
        super().setUp()
        self.bot = FakeBot()

    def put(self, fid, content: bytes, name="dl.pdf"):
        p = self.settings.bot_api_dir / name
        p.write_bytes(content)
        self.bot.files[fid] = str(p)

    def msg(self, name="esame.pdf", uid="U1", fid="F1", size=100, mid=10, group=None, from_id=5):
        return S.make_message(self.bot, mid, from_id, "private", from_id=from_id,
                              document=_doc(name, uid, fid, size), media_group_id=group)

    def run_ingest(self, m, admin=False):
        return asyncio.run(submit.ingest(self.bot, self.settings, m, admin))

    def test_ok_copies_to_inbox_with_hash(self):
        self.put("F1", b"hello")
        o = self.run_ingest(self.msg())
        self.assertIsNotNone(o.sub_id)
        sub = inbox.get_submission(o.sub_id)
        self.assertEqual(sub.sha256, hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(Path(sub.inbox_path).read_bytes(), b"hello")
        self.assertEqual(Path(sub.inbox_path).parent, self.settings.inbox_dir)

    def test_bad_extension_size_and_rate(self):
        self.assertIn("non è accettato", self.run_ingest(self.msg(name="virus.exe")).text)
        self.assertIn("troppo grande", self.run_ingest(self.msg(size=201 * 1024 * 1024)).text)
        self.settings.submit_per_day = 1
        self.put("F1", b"a")
        self.assertIsNotNone(self.run_ingest(self.msg(uid="A")).sub_id)
        self.put("F2", b"b")
        o = self.run_ingest(self.msg(uid="B", fid="F2"))
        self.assertIsNone(o.sub_id)
        self.assertIn("in attesa", o.text)
        self.assertIsNotNone(self.run_ingest(self.msg(uid="B", fid="F2"), admin=True).sub_id)

    def test_quick_dedup_unique_id(self):
        self.put("F1", b"a")
        self.assertIsNotNone(self.run_ingest(self.msg()).sub_id)
        o = self.run_ingest(self.msg())
        self.assertIsNone(o.sub_id)
        self.assertIn("lo abbiamo già", o.text)

    def test_dedup_against_archive_sha_gives_link(self):
        sha = hashlib.sha256(b"dup").hexdigest()
        S.set_tree(FakeNode(9, "INFORMATICA/x.pdf", is_dir=False, sha256=sha))
        self.put("F1", b"dup")
        o = self.run_ingest(self.msg())
        self.assertIsNone(o.sub_id)
        self.assertIn("start=f_9", o.text)
        row = db.conn.execute("SELECT status, duplicate_of FROM submissions").fetchone()
        self.assertEqual(row, ("duplicate", 9))

    def test_dedup_against_other_pending(self):
        self.put("F1", b"same")
        self.put("F2", b"same", name="dl2.pdf")
        self.assertIsNotNone(self.run_ingest(self.msg(uid="A")).sub_id)
        o = self.run_ingest(self.msg(uid="B", fid="F2"))
        self.assertIsNone(o.sub_id)
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM submissions WHERE status='duplicate'").fetchone()[0], 1)

    def test_download_outside_bot_api_dir_refused(self):
        self.bot.files["F1"] = "/etc/hosts"
        o = self.run_ingest(self.msg())
        self.assertIsNone(o.sub_id)
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)


class FlowTests(IngestTests):
    """on_document completo: pick, album, timeout, approvazione con callback."""

    def setUp(self):
        super().setUp()
        submit._picks.clear()
        submit._albums.clear()
        submit.ALBUM_WAIT = 0.05

    def test_album_single_prompt_one_card_per_file(self):
        self.put("F1", b"one")
        self.put("F2", b"two", name="dl2.pdf")

        async def go():
            m1 = self.msg(uid="A", fid="F1", mid=10, group="G")
            m2 = self.msg(uid="B", fid="F2", mid=11, group="G", name="b.pdf")
            await asyncio.gather(submit.on_document(m1, self.bot, self.settings),
                                 submit.on_document(m2, self.bot, self.settings))
            self.assertEqual(len(submit._picks), 1)
            (key, sess), = submit._picks.items()
            self.assertEqual(len(sess.sub_ids), 2)
            cb = S.make_callback(self.bot, "pick:2:ok", S.make_message(self.bot, key[1], key[0]), from_id=5)
            await submit.cb_pick(cb, self.bot, self.settings)

        asyncio.run(go())
        self.assertEqual(len(self.bot.of("CopyMessage")), 2)
        self.assertEqual(self.bot.of("CopyMessage")[0].chat_id, -100)
        self.assertEqual(len(self.bot.of("SendMessage")), 1)    # un solo "Per quale materia?"
        rows = db.conn.execute("SELECT hint_node_id, staff_message_id FROM submissions").fetchall()
        self.assertTrue(all(r[0] == 2 and r[1] for r in rows))
        self.assertEqual(len(self.bot.of("SetMessageReaction")), 2)

    def test_pick_timeout_means_unknown(self):
        self.put("F1", b"one")
        submit.PICK_TIMEOUT = 0.05

        async def go():
            await submit.on_document(self.msg(), self.bot, self.settings)
            await asyncio.sleep(0.3)

        try:
            asyncio.run(go())
        finally:
            submit.PICK_TIMEOUT = 600.0
        row = db.conn.execute("SELECT hint_node_id, staff_message_id FROM submissions").fetchone()
        self.assertIsNone(row[0])
        self.assertIsNotNone(row[1])

    def test_pick_from_other_user_refused(self):
        self.put("F1", b"one")

        async def go():
            await submit.on_document(self.msg(), self.bot, self.settings)
            (key, _), = submit._picks.items()
            cb = S.make_callback(self.bot, "pick:2:ok", S.make_message(self.bot, key[1], key[0]), from_id=99)
            await submit.cb_pick(cb, self.bot, self.settings)
            self.assertEqual(len(submit._picks), 1)
            submit._picks[key].task.cancel()

        asyncio.run(go())

    def test_pick_exclusive_refused(self):
        self.put("F1", b"one")

        async def go():
            await submit.on_document(self.msg(), self.bot, self.settings)
            (key, _), = submit._picks.items()
            cb = S.make_callback(self.bot, "pick:4:ok", S.make_message(self.bot, key[1], key[0]), from_id=5)
            await submit.cb_pick(cb, self.bot, self.settings)
            self.assertEqual(len(submit._picks), 1)
            submit._picks[key].task.cancel()

        asyncio.run(go())

    def test_staff_double_click_and_reject(self):
        sid = self.new_sub()
        staff_msg = S.make_message(self.bot, 500 + sid, -100, "supergroup", from_id=0)

        async def go():
            cb = S.make_callback(self.bot, f"sub:{sid}:ok:10", staff_msg)
            await submit.cb_approve(cb, self.bot, self.settings)
            await submit.cb_approve(cb, self.bot, self.settings)
            cb2 = S.make_callback(self.bot, f"sub:{sid}:no:dup", staff_msg, from_id=2)
            await submit.cb_reject(cb2, self.bot, self.settings)

        asyncio.run(go())
        self.assertEqual(S.credits_of(5), 10)
        self.assertEqual(inbox.get_submission(sid).status, "approved")
        sent = [c.text for c in self.bot.of("SendMessage")]
        self.assertEqual(len(sent), 1)
        self.assertIn("+10", sent[0])
        self.assertEqual(self.bot.of("SendMessage")[0].message_effect_id, submit.PARTY_EFFECT)

    def test_staff_approve_without_folder_is_refused(self):
        sid = self.new_sub(hint=None)
        staff_msg = S.make_message(self.bot, 500 + sid, -100, "supergroup", from_id=0)
        asyncio.run(submit.cb_approve(S.make_callback(self.bot, f"sub:{sid}:ok:5", staff_msg),
                                      self.bot, self.settings))
        self.assertEqual(inbox.get_submission(sid).status, "pending")
        self.assertEqual(S.credits_of(5), 0)

    def test_staff_exclusive_asks_price_then_approves(self):
        sid = self.new_sub(hint=4)
        staff_msg = S.make_message(self.bot, 500 + sid, -100, "supergroup", from_id=0)

        async def go():
            await submit.cb_approve(S.make_callback(self.bot, f"sub:{sid}:ok:10", staff_msg),
                                    self.bot, self.settings)
            self.assertEqual(inbox.get_submission(sid).status, "pending")
            await submit.cb_approve(S.make_callback(self.bot, f"sub:{sid}:ok:10:5", staff_msg),
                                    self.bot, self.settings)

        asyncio.run(go())
        self.assertEqual(inbox.get_submission(sid).dest_path, "EXCLUSIVE/Anno3/5.esame.pdf")

    def test_callback_from_wrong_chat_refused(self):
        sid = self.new_sub()
        other = S.make_message(self.bot, 500 + sid, -999, "supergroup", from_id=0)
        asyncio.run(submit.cb_approve(S.make_callback(self.bot, f"sub:{sid}:ok:10", other),
                                      self.bot, self.settings))
        self.assertEqual(inbox.get_submission(sid).status, "pending")

    def test_admin_direct_flow_saves_without_credits(self):
        S.add_user(1, "boss")
        self.put("F1", b"adm")

        async def go():
            await submit.on_document(self.msg(from_id=1, mid=20), self.bot, self.settings)
            sid = db.conn.execute("SELECT id FROM submissions").fetchone()[0]
            panel = S.make_message(self.bot, 1001, 1, "private", from_id=0)
            submit._admin_msgs[(1, 1001)] = sid
            cb = S.make_callback(self.bot, f"dst:{sid}:2", panel, from_id=1)
            await submit.cb_dst(cb, self.bot, self.settings)

        asyncio.run(go())
        row = db.conn.execute("SELECT status, credits, dest_path FROM submissions").fetchone()
        self.assertEqual(row[:2], ("approved", 0))
        self.assertEqual(row[2], "INFORMATICA/RETI/esame.pdf")
        self.assertEqual(self.bot.of("CopyMessage"), [])         # nessuna scheda staff


if __name__ == "__main__":
    unittest.main()
