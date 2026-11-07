import unittest

from tests import support_browse as sup

from bot import archive
from bot.handlers import browse, files
from bot.texts import browse as T


def specs():
    return [
        (1, None, "INFORMATICA", True),
        (2, 1, "Esami", True),
        (10, 2, "Analisi_2021.pdf", False),
        (11, 2, "Analisi_2022.pdf", False),
        (12, 2, "Algebra.pdf", False),
        (20, None, "EXCLUSIVE", True),
        (21, 20, "Analisi_avanzata", True),
        (22, 21, "10.Analisi_soluzioni.pdf", False, 10),
    ]


class DeepLinkTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(browse.parse_start_arg("n_142"), ("n", 142))
        self.assertEqual(browse.parse_start_arg("f_571"), ("f", 571))
        for bad in (None, "", "n_", "n_abc", "x_1", "n_1_2", "n 1", "f_-3", "hello", "n_" + "9" * 70):
            self.assertIsNone(browse.parse_start_arg(bad), bad)

    def test_search_roundtrip(self):
        for q in ("analisi matematica", "è più già", "a", "x" * 45):
            token = browse.encode_search(q)
            self.assertNotIn("=", token)
            self.assertRegex(token, r"^[A-Za-z0-9_-]+$")
            self.assertEqual(browse.decode_search(token), q)
            self.assertEqual(browse.parse_start_arg("s_" + token), ("s", q))
        self.assertEqual(browse.encode_search("analisi matematica"), "YW5hbGlzaSBtYXRlbWF0aWNh")

    def test_search_invalid(self):
        self.assertIsNone(browse.parse_start_arg("s_"))
        self.assertIsNone(browse.parse_start_arg("s_!!!"))
        self.assertIsNone(browse.decode_search("/w"))  # byte non UTF-8


class InlineTests(unittest.TestCase):
    def setUp(self):
        self.tree = sup.make_tree(specs(), old=True)
        archive.tree = self.tree
        self.fid = lambda n: f"fid{n.id}"

    def ids(self, query, offset=0, **kw):
        picked, nxt = browse.select_inline(query, self.tree, offset, self.fid, **kw)
        return [n.id for n, _ in picked], nxt

    def test_search_excludes_exclusive_and_folders(self):
        ids, nxt = self.ids("analisi")
        self.assertEqual(sorted(ids), [10, 11])   # non 21 (cartella), non 22 (Exclusive)
        self.assertEqual(nxt, "")

    def test_share_query_free_file(self):
        self.assertEqual(self.ids("f:12")[0], [12])

    def test_share_query_exclusive_is_empty(self):
        self.assertEqual(self.ids("f:22")[0], [])

    def test_share_query_missing_or_folder_is_empty(self):
        self.assertEqual(self.ids("f:999")[0], [])
        self.assertEqual(self.ids("f:2")[0], [])

    def test_empty_query_shows_only_recent_free_files(self):
        self.assertEqual(self.ids("")[0], [])             # archivio "vecchio"
        self.tree = sup.make_tree(specs(), old=False)
        ids, _ = self.ids("")
        self.assertEqual(sorted(ids), [10, 11, 12])       # mai il 22

    def test_paging_with_next_offset(self):
        ids, nxt = self.ids("analisi", limit=1)
        self.assertEqual(len(ids), 1)
        self.assertEqual(nxt, "1")
        ids2, nxt2 = self.ids("analisi", offset=int(nxt), limit=1)
        self.assertEqual(nxt2, "")
        self.assertEqual(sorted(ids + ids2), [10, 11])

    def test_files_without_file_id_are_skipped(self):
        self.fid = lambda n: None if n.id == 10 else "x"
        self.assertEqual(self.ids("analisi")[0], [11])

    def test_is_free_file(self):
        self.assertTrue(browse.is_free_file(self.tree.get(10)))
        self.assertFalse(browse.is_free_file(self.tree.get(22)))
        self.assertFalse(browse.is_free_file(self.tree.get(2)))


class HelperTests(unittest.TestCase):
    def test_parse_ints(self):
        self.assertEqual(files.parse_ints("buy:12"), [12])
        self.assertEqual(files.parse_ints("all:3:ok"), None)
        self.assertEqual(files.parse_ints("rep:3:99"), [3, 99])

    def test_purchase_view(self):
        archive.tree = sup.make_tree(specs(), old=True)
        node = archive.tree.get(22)
        text, kb = files.purchase_view(node, balance=12)
        buy = kb.inline_keyboard[0][0]
        self.assertEqual((buy.callback_data, buy.style), ("buy:22", "success"))
        self.assertIsNone(buy.disabled)
        self.assertEqual(kb.inline_keyboard[1][0].style, "danger")
        self.assertEqual(kb.inline_keyboard[1][0].callback_data, "n:21")
        self.assertIn("Costo: 10 crediti · Il tuo saldo: 12", text)
        self.assertNotIn("Come ottenere crediti", text)
        text, kb = files.purchase_view(node, balance=3)
        buy = kb.inline_keyboard[0][0]
        self.assertIsNotNone(buy.disabled)
        self.assertIn("Come ottenere crediti", text)

    def test_file_keyboard_exclusive_has_no_share(self):
        from bot import keyboards
        keyboards.set_bot_username("testbot")
        archive.tree = sup.make_tree(specs(), old=True)
        free = files.file_keyboard(archive.tree.get(10))
        paid = files.file_keyboard(archive.tree.get(22))
        self.assertEqual(free.inline_keyboard[0][0].switch_inline_query_chosen_chat.query, "f:10")
        self.assertEqual(free.inline_keyboard[0][1].copy_text.text,
                         "https://t.me/testbot?start=f_10")
        self.assertEqual(len(paid.inline_keyboard[0]), 1)
        self.assertIsNotNone(paid.inline_keyboard[0][0].copy_text)
        data = [b.callback_data for b in paid.inline_keyboard[-1]]
        self.assertEqual(data, ["fav:22", "rep:22"])
        for kb in (free, paid):
            for row in kb.inline_keyboard:
                for b in row:
                    self.assertLessEqual(len(b.callback_data or ""), 64)

    def test_texts(self):
        self.assertEqual(T.size(1_258_291), "1.2 MB")
        self.assertEqual(T.size(500), "500 B")
        self.assertIn("<tg-time", T.date_tag(sup.NOW))
        self.assertIn("&lt;b&gt;", T.file_caption("<b>", ["A"], 10, sup.NOW))
        self.assertLessEqual(len(T.START_TEXT), 1024)


def _query(data, chat_type="private", user_id=7):
    from unittest.mock import AsyncMock, MagicMock
    q = MagicMock()
    q.data = data
    q.id = "q1"
    q.from_user.id = user_id
    q.message.chat.type = chat_type
    q.message.chat.id = -100 if chat_type != "private" else user_id
    q.answer = AsyncMock()
    return q


class HandlerFixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from unittest import mock
        from bot import keyboards
        keyboards.set_bot_username("testbot")
        archive.tree = sup.make_tree(specs(), old=True)
        self.settings = sup._Settings()
        self.bot = mock.AsyncMock()
        self.sent = []

        async def send_file(bot, settings, user_id, node, **kw):
            self.sent.append(node.id)
        for target, attr, value in (
                (files.storage, "send_file", send_file),
                (files.content, "log_download", lambda *a: None),
                (files, "SEND_INTERVAL", 0)):
            p = mock.patch.object(target, attr, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        files._active_downloads.clear()
        files._reported.clear()

    async def test_double_tap_starts_one_download(self):
        import asyncio
        q1, q2 = _query("all:2"), _query("all:2")
        await asyncio.gather(files.on_all(q1, self.bot, self.settings),
                             files.on_all(q2, self.bot, self.settings))
        task = files._active_downloads[7]
        await task
        self.assertEqual(sorted(self.sent), [10, 11, 12])     # una volta sola
        q2.answer.assert_awaited_with(T.ALL_BUSY)
        self.assertNotIn(7, files._active_downloads)

    async def test_finally_does_not_drop_newer_download(self):
        import asyncio
        newer = asyncio.get_running_loop().create_future()
        files._active_downloads[7] = newer
        await files.download_all(self.bot, self.settings, 7, [archive.tree.get(10)])
        self.assertIs(files._active_downloads[7], newer)

    async def test_download_all_rereads_tree(self):
        nodes = archive.tree.free_files(2)
        # /reindex: 11 ora costa, 12 è sparito
        new = [n for n in specs() if n[0] != 12]
        new = [(11, 2, "Analisi_2022.pdf", False, 5) if n[0] == 11 else n for n in new]
        archive.tree = sup.make_tree(new, version=2, old=True)
        await files.download_all(self.bot, self.settings, 7, nodes)
        self.assertEqual(self.sent, [10])

    async def test_download_all_forbidden_from_group_gives_hint(self):
        from unittest import mock
        from aiogram.exceptions import TelegramForbiddenError
        self.bot.send_message.side_effect = TelegramForbiddenError(mock.MagicMock(), "blocked")
        with mock.patch.object(files, "group_hint", mock.AsyncMock()) as hint:
            q = _query("all:2", chat_type="supergroup")
            await files.download_all(self.bot, self.settings, 7, archive.tree.free_files(2),
                                     group_q=q, folder=archive.tree.get(2))
        hint.assert_awaited_once_with(self.bot, q, archive.tree.get(2))

    async def test_buy_on_now_free_file_delivers(self):
        await files.on_buy(_query("buy:10"), self.bot, self.settings)
        self.assertEqual(self.sent, [10])

    async def test_group_delivery_confirms_with_toast(self):
        from unittest import mock
        q = _query("n:10", chat_type="supergroup")
        with mock.patch.object(files.db, "is_vip", lambda uid: False, create=True):
            await files.open_file(self.bot, self.settings, q.from_user,
                                  archive.tree.get(10), q=q)
        self.assertEqual(self.sent, [10])
        q.answer.assert_awaited_once_with(T.SENT_PRIVATE)

    async def test_report_ticket_failure_answers_error(self):
        import sys
        import types
        from unittest import mock
        fake = types.SimpleNamespace(open_ticket=mock.AsyncMock(side_effect=RuntimeError))
        q = _query("rep:10:broken")
        q.message = None
        with mock.patch.dict(sys.modules, {"bot.handlers.tickets": fake}), \
                mock.patch("bot.handlers.tickets", fake, create=True):
            await files.on_report(q, self.bot, self.settings)
        q.answer.assert_awaited_once_with(T.REPORT_ERROR, show_alert=True)
        self.assertNotIn((7, 10), files._reported)

    async def test_too_large_file_shows_alert_and_sends_nothing(self):
        from unittest import mock
        q = _query("n:10")
        with mock.patch.object(files.storage, "MAX_SEND_BYTES", 10):   # i file di prova pesano 1000 byte
            await files.open_file(self.bot, self.settings, q.from_user, archive.tree.get(10), q=q)
        q.answer.assert_awaited_once_with(T.TOO_LARGE, show_alert=True)
        self.assertEqual(self.sent, [])

    def test_reported_is_pruned(self):
        files._reported[(1, 1)] = 0.0
        files._remember_report((2, 2), files.REPORT_COOLDOWN + 1.0)
        self.assertEqual(list(files._reported), [(2, 2)])


class NoDiskInUserPathTests(unittest.IsolatedAsyncioTestCase):
    """Il percorso utente non legge mai il disco: file non pronti in coda, /start dal file_id."""

    def setUp(self):
        from unittest import mock
        from bot import keyboards
        keyboards.set_bot_username("testbot")
        archive.tree = sup.make_tree(specs(), old=True)
        self.settings = sup._Settings()
        self.bot = mock.AsyncMock()
        self.logged = []
        self.on_sent = []

        async def not_ready(bot, settings, user_id, node, **kw):
            self.on_sent.append(kw["on_sent"])
            raise files.storage.NotReady(node.path)
        for target, attr, value in (
                (files.storage, "send_file", not_ready),
                (files.content, "log_download", lambda u, n: self.logged.append((u, n))),
                (files, "SEND_INTERVAL", 0)):
            p = mock.patch.object(target, attr, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        files._active_downloads.clear()

    async def test_file_not_ready_is_queued_and_counted_only_when_sent(self):
        result = await files.deliver(self.bot, self.settings, 7, archive.tree.get(10))
        self.assertEqual(result, "queued")
        self.bot.send_message.assert_awaited_once_with(7, T.PREPARING)
        self.assertEqual(self.logged, [])          # non ancora inviato: non conta
        self.on_sent[0]()                          # il task in background lo consegna
        self.assertEqual(self.logged, [(7, 10)])

    async def test_download_all_reports_queued_files(self):
        await files.download_all(self.bot, self.settings, 7, archive.tree.free_files(2))
        status = self.bot.send_message.return_value
        final = status.edit_text.await_args.args[0]
        self.assertIn(T.all_queued(3).strip(), final)
        self.assertEqual(self.logged, [])

    async def test_start_never_reads_media_dir(self):
        from unittest import mock
        with mock.patch.object(browse.db, "kv_get", lambda k: None, create=True), \
                mock.patch.object(browse, "_welcome_file",
                                  side_effect=AssertionError("/start ha letto il disco")):
            await browse.send_welcome(self.bot, self.settings, 7, False)
        self.bot.send_animation.assert_not_awaited()
        self.bot.send_message.assert_awaited_once()

    def test_welcome_file_ignores_other_media(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        media = Path(tempfile.mkdtemp())
        (media / "avatar.jpeg").write_bytes(b"x")          # la foto profilo non è il benvenuto
        settings = SimpleNamespace(media_dir=media)
        self.assertIsNone(browse._welcome_file(settings))
        (media / "welcome.mp4").write_bytes(b"x")
        self.assertEqual(browse._welcome_file(settings).name, "welcome.mp4")

    async def test_prepare_welcome_uploads_to_storage_channel_once(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest import mock
        media = Path(tempfile.mkdtemp())
        (media / "welcome.mp4").write_bytes(b"x")
        kv = {}
        settings = SimpleNamespace(media_dir=media, storage_chat_id=-100)
        self.bot.send_animation.return_value = SimpleNamespace(
            animation=SimpleNamespace(file_id="WFID"), document=None, video=None)
        with mock.patch.object(browse.db, "kv_get", kv.get, create=True), \
                mock.patch.object(browse.db, "kv_set", kv.__setitem__, create=True):
            await browse.prepare_welcome(self.bot, settings)
            await browse.prepare_welcome(self.bot, settings)   # già pronto: niente
        self.bot.send_animation.assert_awaited_once()
        self.assertEqual(self.bot.send_animation.await_args.args[0], -100)
        self.assertEqual(kv["welcome_media"], "WFID")


if __name__ == "__main__":
    unittest.main()
