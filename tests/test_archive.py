import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from bot import archive, db
from bot.archive import Tree, is_hidden, natural_key, parse_name

SCHEMA = """
CREATE TABLE blobs (sha256 TEXT PRIMARY KEY, file_id TEXT, file_unique_id TEXT, storage_message_id INTEGER);
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, parent_id INTEGER REFERENCES nodes(id),
    is_dir INTEGER NOT NULL, price INTEGER NOT NULL DEFAULT 0, size INTEGER, mtime REAL,
    sha256 TEXT REFERENCES blobs(sha256), added_at TEXT NOT NULL DEFAULT (datetime('now')),
    hidden INTEGER NOT NULL DEFAULT 0, removed INTEGER NOT NULL DEFAULT 0);
"""


def ts(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


class ParseNameTest(unittest.TestCase):
    def test_cases_from_doc(self):
        self.assertEqual(parse_name("5.(E)manuale.pdf", "EXCLUSIVE/3°_Anno/F/R/5.(E)manuale.pdf", False), ("(E)manuale.pdf", 5))
        self.assertEqual(parse_name("10Luglio21.pdf", "EXCLUSIVE/1°_Anno/A/T/10Luglio21.pdf", False), ("Luglio21.pdf", 10))
        self.assertEqual(parse_name("10 facts.doc", "INGLESE/ESERCIZI/10 facts.doc", False), ("10 facts.doc", 0))
        self.assertEqual(parse_name("2°_Anno", "INFORMATICA/2°_Anno", True), ("2° Anno", 0))

    def test_price_at_depth_one_under_exclusive(self):
        self.assertEqual(parse_name("5.riassunto.pdf", "EXCLUSIVE/5.riassunto.pdf", False), ("riassunto.pdf", 5))

    def test_no_price_under_exclusive(self):
        self.assertEqual(parse_name("note.pdf", "EXCLUSIVE/x/note.pdf", False)[1], 0)

    def test_hidden_names(self):
        for n in (".DS_Store", "~$doc.docx", "a.part", "b.TMP", "c.crdownload", "Thumbs.db", "desktop.ini"):
            self.assertTrue(is_hidden(n), n)
        self.assertFalse(is_hidden("esame.pdf"))

    def test_natural_order(self):
        names = ["10°_Anno", "2°_Anno", "1°_Anno"]
        self.assertEqual(sorted(names, key=natural_key), ["1°_Anno", "2°_Anno", "10°_Anno"])


class TreeTest(unittest.TestCase):
    def setUp(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA)
        self.conn = conn
        db.conn = conn
        self.addCleanup(conn.close)
        rows = [  # id, path, parent, is_dir, price, size, sha, added_at, hidden, removed
            (1, "INFO", None, 1, 0, 0, None, ts(100), 0, 0),
            (2, "INFO/10°_Anno", 1, 1, 0, 0, None, ts(100), 0, 0),
            (3, "INFO/2°_Anno", 1, 1, 0, 0, None, ts(100), 0, 0),
            (4, "INFO/2°_Anno/Analisi_Matematica.pdf", 3, 0, 0, 10, "aa", ts(100), 0, 0),
            (5, "INFO/2°_Anno/nuovo.pdf", 3, 0, 0, 10, "bb", ts(1), 0, 0),
            (6, "INFO/readme.txt", 1, 0, 0, 1, "cc", ts(100), 0, 0),
            (7, "EXCLUSIVE", None, 1, 0, 0, None, ts(100), 0, 0),
            (8, "EXCLUSIVE/5.Riassunto Perché.pdf", 7, 0, 5, 1, "dd", ts(100), 0, 0),
            (9, "EXCLUSIVE/nascosto.pdf", 7, 0, 0, 1, "ee", ts(100), 1, 0),
            (10, "INFO/vecchio.pdf", 1, 0, 0, 1, "ff", ts(100), 0, 1),
            (11, "INFO/2°_Anno/copia.pdf", 3, 0, 0, 10, "aa", ts(100), 0, 0),
        ]
        self.t = Tree(rows)

    def test_children_order_dirs_first_natural(self):
        names = [n.name for n in self.t.children(1)]
        self.assertEqual(names, ["2° Anno", "10° Anno", "readme.txt"])
        self.assertEqual([n.name for n in self.t.children(None)], ["EXCLUSIVE", "INFO"])

    def test_hidden_and_removed_not_visible(self):
        self.assertIsNone(self.t.get(9))
        self.assertIsNone(self.t.get(10))
        self.assertEqual([n.id for n in self.t.children(7)], [8])

    def test_node_fields(self):
        n = self.t.get(8)
        self.assertEqual((n.name, n.raw_name, n.price, n.is_exclusive, n.depth), ("Riassunto Perché.pdf", "5.Riassunto Perché.pdf", 5, True, 2))
        self.assertTrue(self.t.get(7).is_exclusive)
        self.assertFalse(self.t.get(4).is_exclusive)
        self.assertEqual(self.t.get(4).added_at.tzinfo, timezone.utc)

    def test_breadcrumb_and_nearest_visible(self):
        self.assertEqual([n.id for n in self.t.breadcrumb(4)], [1, 3, 4])
        self.assertEqual(self.t.nearest_visible(10).id, 1)   # rimosso -> padre
        self.assertEqual(self.t.nearest_visible(9).id, 7)    # nascosto -> padre
        self.assertEqual(self.t.nearest_visible(4).id, 4)
        self.assertIsNone(self.t.nearest_visible(999))

    def test_is_new(self):
        self.assertTrue(self.t.is_new(5))
        self.assertTrue(self.t.is_new(3))   # cartella con discendente nuovo
        self.assertTrue(self.t.is_new(1))
        self.assertFalse(self.t.is_new(2))
        self.assertFalse(self.t.is_new(4))
        self.assertEqual([n.id for n in self.t.new_files()], [5])

    def test_free_files(self):
        self.assertEqual([n.id for n in self.t.free_files(3)], [4, 11, 5])
        self.assertEqual(self.t.free_files(7), [])

    def test_search(self):
        r = self.t.search("perche", include_exclusive=True)
        self.assertEqual([n.id for n in r], [8])
        self.assertEqual(self.t.search("PERCHE", include_exclusive=False), [])
        # prima i file, poi le cartelle
        r = self.t.search("anno", include_exclusive=False)
        self.assertEqual([n.id for n in r], [3, 2])
        r = self.t.search("a", limit=2, include_exclusive=True)
        self.assertEqual(len(r), 2)
        self.assertEqual(self.t.search("  ", include_exclusive=True), [])

    def test_find_by_sha256(self):
        self.assertEqual(sorted(n.id for n in self.t.find_by_sha256("aa")), [4, 11])
        self.assertEqual(self.t.find_by_sha256("zz"), [])

    def test_version_grows(self):
        self.assertGreater(Tree([]).version, self.t.version)

    def test_load_from_db_replaces_global(self):
        self.conn.execute("INSERT INTO nodes (path, is_dir) VALUES ('X', 1)")
        old = archive.tree
        archive.load_from_db()
        self.assertIsNot(archive.tree, old)
        self.assertEqual([n.name for n in archive.tree.children(None)], ["X"])


if __name__ == "__main__":
    unittest.main()
