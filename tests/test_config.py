import os
import unittest
from pathlib import Path
from unittest import mock

from bot import config

MIN = {"BOT_TOKEN": "t", "ADMIN_IDS": "1, 2", "STAFF_CHAT_ID": "-100", "STORAGE_CHAT_ID": "-200"}


def load(env):
    with mock.patch.dict(os.environ, env, clear=True):
        return config.load()


class ConfigTest(unittest.TestCase):
    def test_empty_env_lists_all_missing(self):
        with self.assertRaises(SystemExit) as cm:
            load({})
        msg = str(cm.exception)
        for name in config.REQUIRED:
            self.assertIn(name, msg)

    def test_partial_missing(self):
        with self.assertRaises(SystemExit) as cm:
            load({"BOT_TOKEN": "t"})
        self.assertNotIn("BOT_TOKEN,", str(cm.exception))
        self.assertIn("ADMIN_IDS", str(cm.exception))

    def test_defaults(self):
        s = load(MIN)
        self.assertEqual(s.admin_ids, frozenset({1, 2}))
        self.assertEqual((s.staff_chat_id, s.storage_chat_id), (-100, -200))
        self.assertIsNone(s.log_chat_id)
        self.assertEqual((s.price_max, s.submit_max_mb, s.submit_per_day), (50, 200, 10))
        self.assertEqual(s.donation_link, "")
        self.assertFalse(s.rich_messages)
        self.assertEqual(s.log_level, "INFO")
        self.assertEqual(s.data_dir, Path("/data"))
        self.assertEqual(s.bot_api_url, "http://telegram-bot-api:8081")
        self.assertFalse(s.local_api)                     # default: server di Telegram
        self.assertEqual(s.max_send_bytes, 50 * 1024 * 1024)
        self.assertEqual(s.max_download_bytes, 20 * 1024 * 1024)

    def test_local_api_switch(self):
        for profiles, expected in (("local-api", True), ("beta,local-api", True), (" local-api , beta", True),
                                   ("beta", False), ("", False), ("local-apix", False)):
            s = load({**MIN, "COMPOSE_PROFILES": profiles})
            self.assertEqual(s.local_api, expected, profiles)
        s = load({**MIN, "COMPOSE_PROFILES": "local-api"})
        self.assertEqual((s.max_send_bytes, s.max_download_bytes), (2000 * 1024 * 1024,) * 2)

    def test_derived_paths(self):
        s = load({**MIN, "DATA_DIR": "/x"})
        self.assertEqual(s.archive_dir, Path("/x/archive"))
        self.assertEqual(s.inbox_dir, Path("/x/inbox"))
        self.assertEqual(s.trash_dir, Path("/x/trash"))
        self.assertEqual(s.media_dir, Path("/x/media"))
        self.assertEqual(s.backups_dir, Path("/x/backups"))
        self.assertEqual(s.db_path, Path("/x/bot.db"))
        self.assertEqual(s.bot_api_dir, Path("/var/lib/telegram-bot-api"))
        with mock.patch.dict(os.environ, {"BOT_API_DIR": "/y"}):
            self.assertEqual(s.bot_api_dir, Path("/y"))

    def test_overrides(self):
        s = load({**MIN, "LOG_CHAT_ID": "-5", "PRICE_MAX": "20", "RICH_MESSAGES": "1",
                  "LOG_LEVEL": "debug", "PRICE_MAX_X": "", "SUBMIT_PER_DAY": ""})
        self.assertEqual(s.log_chat_id, -5)
        self.assertEqual(s.price_max, 20)
        self.assertEqual(s.submit_per_day, 10)
        self.assertTrue(s.rich_messages)
        self.assertEqual(s.log_level, "DEBUG")

    def test_invalid_number_names_variable(self):
        for key in ("PRICE_MAX", "SUBMIT_MAX_MB", "LOG_CHAT_ID", "STAFF_CHAT_ID", "ADMIN_IDS"):
            with self.subTest(key=key), self.assertRaises(SystemExit) as cm:
                load({**MIN, key: "abc"})
            self.assertIn(key, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
