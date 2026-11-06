import unittest

from tests import t3_support as sup

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


if __name__ == "__main__":
    unittest.main()
