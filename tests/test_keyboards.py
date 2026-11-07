import unittest

from tests import support_browse as sup

from bot import archive, keyboards
from bot.texts import browse as T

LONG = "Nome_molto_lungo_" * 6


def sample_specs():
    specs = [
        (100001, None, "INFORMATICA", True),
        (100002, 100001, "1°_Anno", True),
        (100003, 100001, "2°_Anno", True),
        (100004, 100002, "ALGORITMI", True),
        (100005, 100002, "Analisi", True),
        (100006, 100004, "Esami", True),
        (100007, 100006, LONG + ".pdf", False, 0, 1_258_291),
        (100008, 100004, "Formulario.pdf", False),
        (200001, None, "EXCLUSIVE", True),
        (200002, 200001, "3°_Anno", True),
        (200003, 200002, "Fondamenti", True),
        (200004, 200003, "(E)manuale.pdf", False, 5, 2_400_000),
        (300001, None, "TOLC", True),
        (300002, 300001, "Test.pdf", False),
    ]
    return specs


def buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def texts(markup):
    return [b.text for b in buttons(markup)]


def type_fields(button):
    """Campi-tipo valorizzati: Telegram ne vuole esattamente uno per bottone."""
    extra = {"text", "icon_custom_emoji_id", "style"}
    return [f for f in type(button).model_fields
            if f not in extra and getattr(button, f) is not None]


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        keyboards.set_bot_username("testbot")
        archive.tree = sup.make_tree(sample_specs(), old=True)

    def test_callback_data_within_64_bytes_all_modes(self):
        tree = archive.tree
        ids = [None] + [n for n in tree._nodes if tree.get(n).is_dir]
        for mode in ("browse", "pick", "staff", "group"):
            for nid in ids:
                for admin in (False, True):
                    _, kb = keyboards.folder(nid, 0, mode=mode, ctx=999999, is_admin=admin)
                    for b in buttons(kb):
                        if b.callback_data:
                            self.assertLessEqual(len(b.callback_data.encode()), 64,
                                                 (mode, nid, b.callback_data))

    def test_long_names_do_not_break_data(self):
        _, kb = keyboards.folder(100006)
        file_btn = [b for b in buttons(kb) if b.callback_data == "n:100007"][0]
        self.assertIn("1.2 MB", file_btn.text)
        self.assertTrue(file_btn.text.startswith("📖"))

    def test_home_menu_labels(self):
        text, kb = keyboards.folder(None)
        labels = texts(kb)
        self.assertIn("✏INFORMATICA✏", labels)
        self.assertIn("✴EXCLUSIVE✴", labels)
        self.assertEqual(text, T.START_TEXT)
        self.assertLessEqual(len(T.START_TEXT), 1024)

    def test_breadcrumb_and_level_text(self):
        text, _ = keyboards.folder(100004)
        self.assertTrue(text.startswith("📂 INFORMATICA › 1° Anno › ALGORITMI"))
        self.assertIn("⏰Scegli il Materiale⏰", text)

    def test_empty_folder(self):
        sup_tree = sup.make_tree(sample_specs() + [(100009, 100005, "Vuota", True)], old=True)
        archive.tree = sup_tree
        text, _ = keyboards.folder(100009)
        self.assertIn(T.EMPTY, text)

    def test_pagination_25_items(self):
        specs = [(1, None, "CORSO", True)] + [(10 + i, 1, f"Cartella_{i:02d}", True)
                                              for i in range(25)]
        archive.tree = sup.make_tree(specs, old=True)
        _, kb0 = keyboards.folder(1, 0)
        _, kb1 = keyboards.folder(1, 1)
        _, kb2 = keyboards.folder(1, 2)
        self.assertIn("1/3", texts(kb0))
        self.assertIn("2/3", texts(kb1))
        self.assertIn("3/3", texts(kb2))
        ind = [b for b in buttons(kb1) if b.text == "2/3"][0]
        self.assertIsNone(ind.callback_data)
        self.assertIsNotNone(ind.disabled)
        data = [b.callback_data for b in buttons(kb1)]
        self.assertIn("n:1", data)       # ◀️ torna alla pagina 0 (nessun suffisso)
        self.assertIn("n:1:2", data)     # ▶️
        # 10 elementi per pagina (+ riga paginazione, azioni, home)
        entries = [b for b in buttons(kb0) if b.callback_data and b.callback_data.startswith("n:1")
                   and b.text.startswith("Cartella")]
        self.assertEqual(len(entries), 10)
        # ultima pagina: ▶️ disabilitato
        nxt = [b for b in buttons(kb2) if b.text == "▶️"][0]
        self.assertIsNone(nxt.callback_data)
        self.assertIsNotNone(nxt.disabled)
        # nessuna paginazione se basta una pagina
        _, small = keyboards.folder(None)
        self.assertFalse([t for t in texts(small) if "/" in t and t[0].isdigit()])

    def test_page_out_of_range_is_clamped(self):
        _, kb = keyboards.folder(100004, 99)
        self.assertTrue(buttons(kb))

    def test_two_columns_only_at_depth_two(self):
        specs = [(1, None, "CORSO", True), (2, 1, "Anno", True)] + \
                [(10 + i, 2, f"Materia_{i}", True) for i in range(4)] + \
                [(30 + i, 10, f"Sezione_{i}", True) for i in range(4)]
        archive.tree = sup.make_tree(specs, old=True)
        _, kb2 = keyboards.folder(2)         # profondità 2: due colonne
        _, kb3 = keyboards.folder(10)        # profondità 3: una colonna
        _, kb1 = keyboards.folder(1)         # profondità 1: una colonna
        mat_rows = [r for r in kb2.inline_keyboard if r[0].text.startswith("Materia")]
        self.assertEqual([len(r) for r in mat_rows], [2, 2])
        for kb in (kb3, kb1):
            rows = [r for r in kb.inline_keyboard
                    if r[0].callback_data and r[0].callback_data.startswith("n:")
                    and r[0].text[0] not in "<🏠🔍"]
            self.assertTrue(all(len(r) == 1 for r in rows))

    def test_exclusive_texts_differ(self):
        for depth in (1, 2, 3):
            self.assertNotEqual(T.level_text(depth, "X", True), T.level_text(depth, "X", False),
                                depth)
        self.assertIn("Eccoci nel area", T.level_text(1, "EXCLUSIVE", True))
        text, _ = keyboards.folder(200001)
        self.assertIn("Eccoci nel area ⭐️Exclusive⭐", text)

    def test_exclusive_file_label_shows_price(self):
        _, kb = keyboards.folder(200003)
        label = [b.text for b in buttons(kb) if b.callback_data == "n:200004"][0]
        self.assertIn("⭐", label)
        self.assertIn("5 cr", label)

    def test_pick_has_no_exclusive_and_no_files(self):
        _, home = keyboards.folder(None, mode="pick")
        data = [b.callback_data for b in buttons(home)]
        self.assertNotIn("pick:200001", data)
        self.assertNotIn("✴EXCLUSIVE✴", texts(home))
        self.assertIn("pick:100001", data)
        self.assertIn("pick:0:ok", data)             # 🤷 Non so
        self.assertNotIn("n:300002", data)
        _, inner = keyboards.folder(100004, mode="pick")
        data = [b.callback_data for b in buttons(inner)]
        self.assertIn("pick:100004:ok", data)         # 📥 Metti qui
        self.assertIn("pick:100002", data)            # BACK
        self.assertFalse([d for d in data if d and d.startswith("n:")])

    def test_staff_mode(self):
        _, kb = keyboards.folder(100004, mode="staff", ctx=77)
        data = [b.callback_data for b in buttons(kb)]
        self.assertIn("dst:77:100004", data)
        self.assertIn("adm:mkdir:100004", data)
        self.assertIn("dsn:77:100006", data)
        self.assertIn("dsn:77:0", data)               # HOME
        self.assertFalse([d for d in data if d and d.startswith(("n:", "adm:menu"))])

    def test_group_mode(self):
        _, kb = keyboards.folder(100004, mode="group")
        data = [b.callback_data for b in buttons(kb)]
        self.assertIn("grp:100004:ok", data)
        self.assertIn("grp:100006", data)

    def test_manage_button_only_for_admin(self):
        _, user = keyboards.folder(100004, is_admin=False)
        _, admin = keyboards.folder(100004, is_admin=True)
        self.assertNotIn("adm:menu:100004", [b.callback_data for b in buttons(user)])
        self.assertIn("adm:menu:100004", [b.callback_data for b in buttons(admin)])
        # is_admin è ignorato fuori dalla modalità browse
        _, pick = keyboards.folder(100004, mode="pick", is_admin=True)
        self.assertFalse([b for b in buttons(pick) if (b.callback_data or "").startswith("adm:")])

    def test_download_all_and_link_buttons(self):
        _, with_files = keyboards.folder(100004)      # ha Formulario.pdf gratuito
        self.assertIn("all:100004", [b.callback_data for b in buttons(with_files)])
        link = [b for b in buttons(with_files) if b.copy_text][0]
        self.assertEqual(link.copy_text.text, "https://t.me/testbot?start=n_100004")
        _, no_files = keyboards.folder(100005)        # vuota
        self.assertFalse([b for b in buttons(no_files) if b.callback_data == "all:100005"])
        search = [b for b in buttons(with_files) if b.text == T.BTN_SEARCH][0]
        self.assertEqual(search.switch_inline_query_current_chat, "")

    def test_home_button_is_primary_and_back_goes_to_parent(self):
        _, kb = keyboards.folder(100004)
        home = [b for b in buttons(kb) if b.text == T.HOME_BUTTON][0]
        self.assertEqual((home.callback_data, home.style), ("n:0", "primary"))
        back = [b for b in buttons(kb) if b.text == T.BACK_BUTTON][0]
        self.assertEqual(back.callback_data, "n:100002")
        _, top = keyboards.folder(100001)
        self.assertNotIn(T.BACK_BUTTON, texts(top))

    def test_new_badge(self):
        archive.tree = sup.make_tree(sample_specs(), old=False)
        _, kb = keyboards.folder(None)
        self.assertEqual(texts(kb)[0].count("🆕"), 0)         # in HOME niente badge
        _, kb = keyboards.folder(100001)
        self.assertIn("1° Anno 🆕", texts(kb))

    def test_cache_invalidated_by_new_tree(self):
        text1, _ = keyboards.folder(100005)
        self.assertIn(T.EMPTY, text1)
        specs = sample_specs() + [(100010, 100005, "Nuova.pdf", False)]
        archive.tree = sup.make_tree(specs, version=2, old=True)
        text2, kb2 = keyboards.folder(100005)
        self.assertNotIn(T.EMPTY, text2)
        self.assertIn("n:100010", [b.callback_data for b in buttons(kb2)])

    def test_cache_returns_same_result(self):
        self.assertIs(keyboards.folder(100004)[1], keyboards.folder(100004)[1])

    def test_every_button_has_exactly_one_type_field(self):
        specs = [(1, None, "CORSO", True)] + [(10 + i, 1, f"F_{i:02d}.pdf", False)
                                              for i in range(25)]
        archive.tree = sup.make_tree(specs, old=True)
        kbs = [keyboards.folder(1, p, mode=m, is_admin=True)[1]
               for p in range(3) for m in ("browse", "pick", "staff", "group")]
        kbs.append(keyboards.folder(None)[1])
        for kb in kbs:
            for b in buttons(kb):
                self.assertEqual(len(type_fields(b)), 1, b)

    def test_node_list(self):
        nodes = [archive.tree.get(100008), archive.tree.get(100004)]
        text, kb = keyboards.node_list("titolo", nodes)
        self.assertEqual(text, "titolo")
        self.assertEqual([b.callback_data for b in buttons(kb)],
                         ["n:100008", "n:100004", "n:0"])



class TooLargeTests(unittest.TestCase):
    """Server di Telegram: i file oltre il limite restano visibili con 📦."""

    def setUp(self):
        from bot import storage
        keyboards.set_bot_username("testbot")
        archive.tree = sup.make_tree(sample_specs(), old=True)
        self.storage = storage
        old = storage.MAX_SEND_BYTES
        storage.MAX_SEND_BYTES = 1_000_000          # il file da 1,2 MB è troppo grande
        self.addCleanup(setattr, storage, "MAX_SEND_BYTES", old)

    def labels(self, node_id):
        _, kb = keyboards.folder(node_id)
        return [b.text for row in kb.inline_keyboard for b in row]

    def test_oversized_file_visible_with_box_icon(self):
        labels = self.labels(100006)
        big = [l for l in labels if LONG[:10].replace("_", " ") in l]
        self.assertTrue(big and big[0].startswith("📦"), labels)
        self.assertTrue(any(l.startswith("📖Formulario") for l in self.labels(100004)))

    def test_download_all_hidden_when_only_oversized(self):
        self.assertNotIn(T.BTN_ALL, self.labels(100006))   # unico file: troppo grande
        self.assertIn(T.BTN_ALL, self.labels(100004))      # Formulario.pdf è piccolo


if __name__ == "__main__":
    unittest.main()
