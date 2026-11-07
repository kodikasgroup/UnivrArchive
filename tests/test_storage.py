import asyncio
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendDocument
from aiogram.types import Chat, Document, Message

from bot import db, storage
from bot.archive import Node
from bot.db import nodes
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE blobs (sha256 TEXT PRIMARY KEY, file_id TEXT, file_unique_id TEXT, storage_message_id INTEGER);
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, parent_id INTEGER REFERENCES nodes(id),
    is_dir INTEGER NOT NULL, price INTEGER NOT NULL DEFAULT 0, size INTEGER, mtime REAL,
    sha256 TEXT REFERENCES blobs(sha256), added_at TEXT NOT NULL DEFAULT (datetime('now')),
    hidden INTEGER NOT NULL DEFAULT 0, removed INTEGER NOT NULL DEFAULT 0);
"""
CHANNEL = -100


def message(chat_id: int, message_id: int, file_id: str) -> Message:
    return Message(
        message_id=message_id, date=datetime.now(timezone.utc), chat=Chat(id=chat_id, type="private"),
        document=Document(file_id=file_id, file_unique_id="u" + file_id, file_name="x"),
    )


class FakeBot:
    def __init__(self):
        self.sent: list[tuple] = []
        self.copied: list[tuple] = []
        self.counter = 0
        self.bad_ids: set[str] = set()
        self.upload_delay = 0.0
        self.retry_once = False
        self.forwarded = False

    async def send_document(self, chat_id, document, **kw):
        self.sent.append((chat_id, document, kw))
        if isinstance(document, str) and document in self.bad_ids:
            raise TelegramBadRequest(method=SendDocument(chat_id=chat_id, document=document), message="Bad Request: wrong file identifier/HTTP URL specified")
        if self.retry_once:
            self.retry_once = False
            raise TelegramRetryAfter(method=SendDocument(chat_id=chat_id, document="x"), message="flood", retry_after=0)
        if self.upload_delay:
            await asyncio.sleep(self.upload_delay)
        self.counter += 1
        return message(chat_id, 1000 + self.counter, f"fid{self.counter}")

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        self.copied.append((chat_id, from_chat_id, message_id, kw))
        return SimpleNamespace(message_id=5000)

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.edited = (chat_id, message_id, reply_markup)
        return message(chat_id, message_id, "COPYFID")

    def __getattr__(self, name):
        if name.startswith("forward"):
            self.forwarded = True
        raise AttributeError(name)


class StorageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "A").mkdir()
        (self.tmp / "A" / "f.pdf").write_text("ciao")
        (self.tmp / "A" / "g.pdf").write_text("ciao2")
        self.settings = SimpleNamespace(archive_dir=self.tmp, storage_chat_id=CHANNEL)
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SCHEMA)
        db.conn = self.conn
        self.addCleanup(self.conn.close)
        storage._locks.clear()
        storage._priority.clear()
        storage._background = None
        storage.UPLOAD_INTERVAL = 0
        self.bot = FakeBot()
        self.f = self.node(1, "A/f.pdf", "s" * 64)
        self.g = self.node(2, "A/g.pdf", "t" * 64)
        for n in (self.f, self.g):
            self.conn.execute("INSERT INTO blobs (sha256) VALUES (?)", (n.sha256,))
            self.conn.execute("INSERT INTO nodes (id, path, is_dir, sha256) VALUES (?, ?, 0, ?)", (n.id, n.path, n.sha256))
        self.conn.commit()

    def node(self, id_, path, sha):
        return Node(id_, None, path.split("/")[-1], path.split("/")[-1], path, False, 2, False, 0, 4, sha, datetime.now(timezone.utc))

    async def test_concurrent_ensure_uploaded_uploads_once(self):
        self.bot.upload_delay = 0.05
        blobs = await asyncio.gather(*(storage.ensure_uploaded(self.bot, self.settings, self.f) for _ in range(5)))
        uploads = [s for s in self.bot.sent if s[0] == CHANNEL]
        self.assertEqual(len(uploads), 1)
        self.assertEqual({b.file_id for b in blobs}, {"fid1"})
        stored = nodes.get_blob(self.f.sha256)
        self.assertEqual((stored.file_id, stored.storage_message_id), ("fid1", 1001))
        self.assertIn("#" + "s" * 12, uploads[0][2]["caption"])
        self.assertIn("A/f.pdf", uploads[0][2]["caption"])

    async def test_send_file_uses_file_id_and_never_forwards(self):
        nodes.set_storage(self.f.sha256, "FID", "U", 77)
        msg = await storage.send_file(self.bot, self.settings, 42, self.f, caption="mia", protect=True)
        self.assertEqual(msg.chat.id, 42)
        chat, doc, kw = self.bot.sent[0]
        self.assertEqual((chat, doc, kw["caption"], kw["protect_content"]), (42, "FID", "mia", True))
        self.assertFalse(self.bot.forwarded)
        self.assertEqual(self.bot.copied, [])

    def count_disk_reads(self):
        reads = []
        real = storage._disk_file

        def spy(settings, path):
            reads.append(path)
            return real(settings, path)
        storage._disk_file = spy
        self.addCleanup(setattr, storage, "_disk_file", real)
        return reads

    async def test_send_file_missing_never_reads_disk_and_delivers_from_queue(self):
        reads = self.count_disk_reads()
        delivered = []
        with self.assertRaises(storage.NotReady):
            await storage.send_file(self.bot, self.settings, 42, self.f, caption="c",
                                    message_effect_id="eff", on_sent=lambda: delivered.append(1))
        # il click è finito: niente disco, niente invii
        self.assertEqual(reads, [])
        self.assertEqual(self.bot.sent, [])
        await storage._background  # il task in background carica e consegna
        self.assertEqual(reads[0], "A/f.pdf")  # prima il file richiesto (poi l'arretrato)
        self.assertEqual(self.bot.sent[0][0], CHANNEL)
        self.assertEqual(self.bot.sent[1][0], 42)
        self.assertEqual(self.bot.sent[1][2]["message_effect_id"], "eff")
        self.assertEqual(delivered, [1])
        self.assertFalse(self.bot.forwarded)

    async def test_priority_request_goes_before_background_backlog(self):
        storage.resume_background_upload(self.bot, self.settings)  # backlog: f e g
        with self.assertRaises(storage.NotReady):
            await storage.send_file(self.bot, self.settings, 42, self.g, caption="c")
        await storage._background
        channel = [s for s in self.bot.sent if s[0] == CHANNEL]
        self.assertTrue(str(channel[0][1].path).endswith("g.pdf"))  # g prima di f

    async def test_invalid_file_id_falls_back_to_copy_with_our_caption(self):
        nodes.set_storage(self.f.sha256, "OLD", "U", 77)
        self.bot.bad_ids.add("OLD")
        msg = await storage.send_file(self.bot, self.settings, 42, self.f, caption="nostra")
        chat, src, mid, kw = self.bot.copied[0]
        self.assertEqual((chat, src, mid, kw["caption"]), (42, CHANNEL, 77, "nostra"))
        self.assertEqual(msg.message_id, 5000)
        self.assertFalse(self.bot.forwarded)
        await asyncio.sleep(0.05)  # refresh del file_id in background
        self.assertNotEqual(nodes.get_blob(self.f.sha256).file_id, "OLD")

    async def test_invalid_file_id_without_channel_copy_reuploads(self):
        nodes.set_file_id(self.f.sha256, "OLD", "U")
        self.bot.bad_ids.add("OLD")
        reads = self.count_disk_reads()
        with self.assertRaises(storage.NotReady):
            await storage.send_file(self.bot, self.settings, 42, self.f, caption="c")
        self.assertEqual(reads, [])
        await storage._background
        self.assertEqual(self.bot.copied, [])
        to_user = [s for s in self.bot.sent if s[0] == 42]
        self.assertEqual(to_user[-1][1], nodes.get_blob(self.f.sha256).file_id)
        self.assertNotEqual(to_user[-1][1], "OLD")

    async def test_remember_file_id_then_background_posts_without_disk(self):
        (self.tmp / "A" / "f.pdf").unlink()  # il disco non serve
        storage.remember_file_id(self.f.sha256, "TGID", "TU")
        blob = await storage.ensure_uploaded(self.bot, self.settings, self.f)
        self.assertEqual(self.bot.sent[0][:2], (CHANNEL, "TGID"))
        self.assertEqual(blob.storage_message_id, 1001)

    async def test_resume_background_upload_idempotent_and_progress(self):
        calls = []

        async def progress(done, total):
            calls.append((done, total))

        self.bot.upload_delay = 0.01
        t1 = storage.resume_background_upload(self.bot, self.settings, progress)
        t2 = storage.resume_background_upload(self.bot, self.settings, progress)
        self.assertIs(t1, t2)
        await t1
        self.assertEqual(calls[-1], (2, 2))
        self.assertEqual(len([s for s in self.bot.sent if s[0] == CHANNEL]), 2)
        self.assertEqual(nodes.count_to_upload(), 0)
        self.assertIsNone(storage.resume_background_upload(self.bot, self.settings))

    async def test_background_survives_retry_after_and_missing_file(self):
        (self.tmp / "A" / "g.pdf").unlink()
        self.bot.retry_once = True
        task = storage.resume_background_upload(self.bot, self.settings)
        await task
        self.assertEqual(nodes.count_to_upload(), 1)  # g non si può caricare, f sì (dopo il retry)
        self.assertIsNotNone(nodes.get_blob(self.f.sha256).storage_message_id)


    async def test_background_picks_up_blobs_added_while_running(self):
        calls = []

        async def progress(done, total):
            calls.append((done, total))

        self.bot.upload_delay = 0.02
        task = storage.resume_background_upload(self.bot, self.settings)
        await asyncio.sleep(0)
        (self.tmp / "A" / "h.pdf").write_text("ciao3")  # aggiunto da un /reindex durante il giro
        self.conn.execute("INSERT INTO blobs (sha256) VALUES (?)", ("u" * 64,))
        self.conn.execute("INSERT INTO nodes (id, path, is_dir, sha256) VALUES (3, 'A/h.pdf', 0, ?)", ("u" * 64,))
        self.conn.commit()
        self.assertIs(storage.resume_background_upload(self.bot, self.settings, progress), task)
        await task
        self.assertEqual(nodes.count_to_upload(), 0)
        self.assertEqual(calls[-1], (3, 3))  # il nuovo callback non viene perso

    async def test_concurrent_invalid_file_id_reuploads_once(self):
        nodes.set_file_id(self.f.sha256, "OLD", "U")
        self.bot.bad_ids.add("OLD")
        self.bot.upload_delay = 0.02
        results = await asyncio.gather(
            *(storage.send_file(self.bot, self.settings, 42, self.f, caption="c") for _ in range(2)),
            return_exceptions=True)
        self.assertTrue(all(isinstance(r, storage.NotReady) for r in results))
        await storage._background
        f_uploads = [s for s in self.bot.sent if s[0] == CHANNEL and str(getattr(s[1], "path", "")).endswith("f.pdf")]
        self.assertEqual(len(f_uploads), 1)
        self.assertEqual(len([s for s in self.bot.sent if s[0] == 42 and s[1] != "OLD"]), 2)

    async def test_missing_file_id_recovered_by_copy_without_disk(self):
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        (self.tmp / "A" / "f.pdf").unlink()  # il disco non serve
        self.conn.execute("UPDATE blobs SET storage_message_id = 77 WHERE sha256 = ?", (self.f.sha256,))
        self.conn.commit()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="x", callback_data="x")]])
        msg = await storage.send_file(self.bot, self.settings, 42, self.f, caption="nostra", reply_markup=kb)
        chat, src, mid, kw = self.bot.copied[0]
        self.assertEqual((chat, src, mid, kw["caption"]), (42, CHANNEL, 77, "nostra"))
        self.assertEqual(self.bot.sent, [])  # niente upload
        self.assertFalse(self.bot.forwarded)
        self.assertEqual(self.bot.edited, (42, 5000, kb))
        self.assertEqual(msg.message_id, 5000)
        blob = nodes.get_blob(self.f.sha256)
        self.assertEqual((blob.file_id, blob.storage_message_id), ("COPYFID", 77))

if __name__ == "__main__":
    unittest.main()
