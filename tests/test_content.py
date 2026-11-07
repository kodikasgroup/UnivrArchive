import unittest

from tests import support_browse as sup

from bot.db import content


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.conn = sup.open_db()
        self.conn.execute("INSERT INTO users (id, credits) VALUES (1, 12)")
        self.conn.execute("INSERT INTO users (id, credits) VALUES (2, 3)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def credits(self, uid):
        return self.conn.execute("SELECT credits FROM users WHERE id=?", (uid,)).fetchone()[0]

    def test_buy_ok_logs_and_charges(self):
        self.assertTrue(content.buy(1, 50, 5))
        self.assertEqual(self.credits(1), 7)
        self.assertTrue(content.has_purchase(1, 50))
        row = self.conn.execute("SELECT user_id, delta, reason FROM credit_log").fetchone()
        self.assertEqual(row, (1, -5, "purchase:50"))
        self.assertEqual(self.conn.execute("SELECT price FROM purchases").fetchone()[0], 5)

    def test_buy_exact_balance(self):
        self.assertTrue(content.buy(2, 50, 3))
        self.assertEqual(self.credits(2), 0)

    def test_buy_insufficient_writes_nothing(self):
        self.assertFalse(content.buy(2, 50, 5))
        self.assertEqual(self.credits(2), 3)
        self.assertFalse(content.has_purchase(2, 50))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM credit_log").fetchone()[0], 0)

    def test_buy_twice_no_double_charge(self):
        self.assertTrue(content.buy(1, 50, 5))
        self.assertTrue(content.buy(1, 50, 5))
        self.assertEqual(self.credits(1), 7)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM credit_log").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0], 1)

    def test_already_bought_ignores_balance(self):
        content.buy(2, 50, 3)
        self.assertTrue(content.buy(2, 50, 99))  # già suo: gratis, anche se il prezzo sale
        self.assertEqual(self.credits(2), 0)

    def test_toggle_favorite(self):
        self.assertTrue(content.toggle_favorite(1, 10))
        self.assertTrue(content.toggle_favorite(1, 11))
        self.assertEqual(content.list_favorites(1), [11, 10])  # più recente prima
        self.assertFalse(content.toggle_favorite(1, 10))
        self.assertEqual(content.list_favorites(1), [11])
        self.assertEqual(content.list_favorites(2), [])

    def test_log_download_counts_and_recent_order(self):
        for node in (10, 11, 10, 12):
            content.log_download(1, node)
        self.assertEqual(self.conn.execute(
            "SELECT downloads FROM users WHERE id=1").fetchone()[0], 4)
        self.assertEqual(content.recent_downloads(1), [12, 10, 11])
        self.assertEqual(content.recent_downloads(1, limit=2), [12, 10])
        self.assertEqual(content.recent_downloads(2), [])

    def test_group_folders(self):
        self.assertIsNone(content.get_group_folder(-100))
        content.set_group_folder(-100, 7, admin_id=1)
        self.assertEqual(content.get_group_folder(-100), 7)
        content.set_group_folder(-100, 9, admin_id=2)  # ricollegare sostituisce
        self.assertEqual(content.get_group_folder(-100), 9)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*), MAX(linked_by) FROM group_folders").fetchone(), (1, 2))
        content.delete_group_folder(-100)
        self.assertIsNone(content.get_group_folder(-100))


if __name__ == "__main__":
    unittest.main()
