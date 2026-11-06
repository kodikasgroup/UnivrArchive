import unittest
from types import SimpleNamespace

from aiogram.types import BotCommand

from bot import __main__ as entry
from bot.texts import common


class MainTest(unittest.TestCase):
    def test_router_order(self):
        self.assertEqual(entry.ROUTER_MODULES,
                         ("admin", "manage", "tickets", "submit", "groups", "files", "browse"))

    def test_build_commands(self):
        a = SimpleNamespace(COMMANDS=[BotCommand(command="start", description="s")],
                            ADMIN_COMMANDS=[BotCommand(command="stats", description="x")])
        b = SimpleNamespace(COMMANDS=[BotCommand(command="start", description="dup"),
                                      BotCommand(command="help", description="h")],
                            ADMIN_COMMANDS=[])
        default, admin = entry.build_commands([a, b])
        self.assertEqual([c.command for c in default], ["start", "help"])
        self.assertEqual([c.command for c in admin], ["start", "help", "stats"])

    def test_help_donation(self):
        self.assertNotIn("Donazioni", common.help_text(""))
        self.assertIn('href="https://x.y/?a=1&amp;b=2"', common.help_text("https://x.y/?a=1&b=2"))


if __name__ == "__main__":
    unittest.main()
