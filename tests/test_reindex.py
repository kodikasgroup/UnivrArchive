import asyncio
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from bot import archive, db
from bot.archive import DiskChanged, PreviewExpired, ReindexBusy
from bot.db import nodes

SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE blobs (sha256 TEXT PRIMARY KEY, file_id TEXT, file_unique_id TEXT, storage_message_id INTEGER);
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, parent_id INTEGER REFERENCES nodes(id),
    is_dir INTEGER NOT NULL, price INTEGER NOT NULL DEFAULT 0, size INTEGER, mtime REAL,
    sha256 TEXT REFERENCES blobs(sha256), added_at TEXT NOT NULL DEFAULT (datetime('now')),
    hidden INTEGER NOT NULL DEFAULT 0, removed INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX nodes_path_active ON nodes(path) WHERE removed = 0;
CREATE TABLE purchases (user_id INTEGER NOT NULL REFERENCES users(id), node_id INTEGER NOT NULL REFERENCES nodes(id),
    price INTEGER NOT NULL, at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (user_id, node_id));
"""
OLD = time.time() - 3600


class ReindexTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "archive"
        self.root.mkdir()
        self.settings = SimpleNamespace(archive_dir=self.root, price_max=50, storage_chat_id=-100)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        db.conn = self.conn
        self.addCleanup(self.conn.close)
        archive._release()
        archive.PREVIEW_TTL = 600.0
        archive._clock = time.monotonic
        archive.load_from_db()

    def tearDown(self):
        archive._release()
        archive.PREVIEW_TTL = 600.0
        archive._clock = time.monotonic

    # ---- helpers
    def put(self, rel: str, content: str = "x", age: float = 3600) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        os.utime(p, (time.time() - age, time.time() - age))
        return p

    async def reindex(self, admin=1):
        pv = await archive.start_reindex(self.settings, admin)
        if not pv.is_empty:
            await archive.apply_reindex(admin)
        return pv

    def row(self, rel: str):
        return self.conn.execute("SELECT id, removed, hidden, price FROM nodes WHERE path = ? ORDER BY id DESC", (rel,)).fetchone()

    def vis(self, rel: str):
        n = next((n for n in archive.tree._nodes.values() if n.path == rel), None)
        return n

    # ---- tests
    async def test_first_import(self):
        self.put("INFO/2°_Anno/a.pdf", "a", age=86400 * 30)
        self.put("INFO/10°_Anno/b.pdf", "b")
        self.put("INFO/vuota/.keep_hidden", "z")
        (self.root / "INFO" / "vuota").mkdir(exist_ok=True)
        self.put(".DS_Store")
        self.put("INFO/~$lock.docx")
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.added, ["INFO/10°_Anno/b.pdf", "INFO/2°_Anno/a.pdf"])
        self.assertFalse(pv.is_empty)
        res = await archive.apply_reindex(1)
        self.assertEqual((res.added, res.to_upload), (2, 2))
        self.assertEqual([n.name for n in archive.tree.children(None)], ["INFO"])
        info = archive.tree.children(None)[0]
        self.assertEqual([n.name for n in archive.tree.children(info.id)], ["2° Anno", "10° Anno", "vuota"])
        a = self.vis("INFO/2°_Anno/a.pdf")
        age = (archive.datetime.now(archive._UTC) - a.added_at).days
        self.assertIn(age, (29, 30))  # added_at = mtime al primo import
        self.assertFalse(archive.tree.is_new(a.id))
        self.assertTrue(archive.tree.is_new(self.vis("INFO/10°_Anno/b.pdf").id))  # mtime di 1 ora fa

    async def test_second_scan_without_changes_is_empty(self):
        self.put("A/f.pdf")
        await self.reindex()
        pv = await archive.start_reindex(self.settings, 1)
        self.assertTrue(pv.is_empty)
        self.assertFalse(archive.reindex_lock.locked())

    async def test_rename_file_keeps_id(self):
        self.put("A/f.pdf", "contenuto")
        await self.reindex()
        fid = self.row("A/f.pdf")[0]
        (self.root / "A" / "f.pdf").rename(self.root / "A" / "g.pdf")
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.moved, [("A/f.pdf", "A/g.pdf")])
        self.assertEqual((pv.added, pv.removed), ([], []))
        await archive.apply_reindex(1)
        self.assertEqual(self.row("A/g.pdf")[0], fid)
        self.assertIsNone(self.row("A/f.pdf"))
        self.assertEqual(archive.tree.get(fid).name, "g.pdf")

    async def test_move_between_folders_keeps_id(self):
        self.put("A/f.pdf", "contenuto")
        await self.reindex()
        fid = self.row("A/f.pdf")[0]
        (self.root / "B").mkdir()
        (self.root / "A" / "f.pdf").rename(self.root / "B" / "f.pdf")
        await self.reindex()
        n = archive.tree.get(fid)
        self.assertEqual(n.path, "B/f.pdf")
        self.assertEqual(archive.tree.get(n.parent_id).name, "B")

    async def test_rename_folder_with_new_file_keeps_folder_id(self):
        for i in range(3):
            self.put(f"C/Vecchia/f{i}.pdf", f"c{i}")
        await self.reindex()
        dir_id = self.row("C/Vecchia")[0]
        (self.root / "C" / "Vecchia").rename(self.root / "C" / "Nuova")
        self.put("C/Nuova/extra.pdf", "extra")
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.added, ["C/Nuova/extra.pdf"])
        self.assertEqual(len(pv.moved), 3)
        self.assertEqual(pv.removed, [])
        await archive.apply_reindex(1)
        self.assertEqual(self.row("C/Nuova")[0], dir_id)
        self.assertIsNone(self.row("C/Vecchia"))

    async def test_nested_folders_renamed_together(self):
        self.put("X/Uno/Due/f.pdf", "f")
        self.put("X/Uno/Due/g.pdf", "g")
        await self.reindex()
        ids = [self.row(p)[0] for p in ("X/Uno", "X/Uno/Due", "X/Uno/Due/f.pdf")]
        (self.root / "X" / "Uno").rename(self.root / "X" / "Primo")
        (self.root / "X" / "Primo" / "Due").rename(self.root / "X" / "Primo" / "Secondo")
        await self.reindex()
        self.assertEqual([self.row(p)[0] for p in ("X/Primo", "X/Primo/Secondo", "X/Primo/Secondo/f.pdf")], ids)

    async def test_modified_content_keeps_id(self):
        p = self.put("A/f.pdf", "uno")
        await self.reindex()
        fid = self.row("A/f.pdf")[0]
        old_sha = archive.tree.get(fid).sha256
        p.write_text("due")
        os.utime(p, (OLD + 5, OLD + 5))
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.modified, ["A/f.pdf"])
        await archive.apply_reindex(1)
        self.assertEqual(self.row("A/f.pdf")[0], fid)
        self.assertNotEqual(archive.tree.get(fid).sha256, old_sha)
        self.assertEqual(nodes.count_to_upload(), 1)  # solo il blob nuovo è usato da un nodo attivo

    async def test_removed_then_different_file_at_same_path(self):
        p = self.put("A/f.pdf", "uno")
        await self.reindex()
        fid = self.row("A/f.pdf")[0]
        p.unlink()
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.removed, ["A/f.pdf"])
        await archive.apply_reindex(1)
        self.assertIsNone(archive.tree.get(fid))
        self.assertEqual(archive.tree.nearest_visible(fid).path, "A")
        self.put("A/f.pdf", "diverso")
        await self.reindex()
        new_id = self.row("A/f.pdf")[0]
        self.assertNotEqual(new_id, fid)
        self.assertEqual(self.conn.execute("SELECT removed FROM nodes WHERE id=?", (fid,)).fetchone()[0], 1)

    async def test_removed_then_same_file_reuses_row(self):
        p = self.put("A/f.pdf", "uno")
        await self.reindex()
        fid = self.row("A/f.pdf")[0]
        p.unlink()
        await self.reindex()
        self.put("A/f.pdf", "uno")
        await self.reindex()
        self.assertEqual(self.row("A/f.pdf")[0], fid)
        self.assertIsNotNone(archive.tree.get(fid))

    async def test_missing_or_huge_price_hidden_keeps_purchases(self):
        self.put("EXCLUSIVE/1°_Anno/5.ok.pdf", "ok")
        self.put("EXCLUSIVE/1°_Anno/senza_prezzo.pdf", "np")
        self.put("EXCLUSIVE/1°_Anno/2021_esame.pdf", "big")
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.hidden_no_price, ["EXCLUSIVE/1°_Anno/senza_prezzo.pdf"])
        self.assertEqual(pv.hidden_over_max, [("EXCLUSIVE/1°_Anno/2021_esame.pdf", 2021)])
        await archive.apply_reindex(1)
        folder = self.vis("EXCLUSIVE/1°_Anno")
        self.assertEqual([n.name for n in archive.tree.children(folder.id)], ["ok.pdf"])
        self.assertEqual(archive.tree.children(folder.id)[0].price, 5)
        hid = self.row("EXCLUSIVE/1°_Anno/senza_prezzo.pdf")
        self.assertEqual((hid[2], hid[3]), (1, 0))
        # acquisto, poi il file viene rinominato con un prezzo: stesso id, visibile, acquisto conservato
        self.conn.execute("INSERT INTO users (id) VALUES (7)")
        self.conn.execute("INSERT INTO purchases (user_id, node_id, price) VALUES (7, ?, 0)", (hid[0],))
        self.conn.commit()
        (self.root / "EXCLUSIVE/1°_Anno/senza_prezzo.pdf").rename(self.root / "EXCLUSIVE/1°_Anno/10.con_prezzo.pdf")
        await self.reindex()
        self.assertEqual(self.row("EXCLUSIVE/1°_Anno/10.con_prezzo.pdf")[0], hid[0])
        self.assertEqual(archive.tree.get(hid[0]).price, 10)
        self.assertTrue(nodes.node_has_purchases(hid[0]))

    async def test_price_change_reported(self):
        self.put("EXCLUSIVE/10.tema.pdf", "t")
        await self.reindex()
        (self.root / "EXCLUSIVE/10.tema.pdf").rename(self.root / "EXCLUSIVE/5.tema.pdf")
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.price_changed, [("EXCLUSIVE/5.tema.pdf", 10, 5)])
        await archive.apply_reindex(1)

    async def test_exclusive_leak(self):
        self.put("EXCLUSIVE/5.segreto.pdf", "stesso")
        self.put("GRATIS/copia.pdf", "stesso")
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.exclusive_leaks, [("EXCLUSIVE/5.segreto.pdf", "GRATIS/copia.pdf")])

    async def test_in_copy_file_not_indexed(self):
        self.put("A/vecchio.pdf", "v")
        self.put("A/nuovo.pdf", "n", age=1)
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(pv.in_copy, ["A/nuovo.pdf"])
        self.assertEqual(pv.added, ["A/vecchio.pdf"])
        await archive.apply_reindex(1)
        self.assertIsNone(self.row("A/nuovo.pdf"))

    async def test_indexed_file_recently_touched_not_removed(self):
        p = self.put("A/f.pdf", "v")
        await self.reindex()
        os.utime(p, None)  # mtime = adesso: sembra ancora in copia
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual((pv.removed, pv.added, pv.in_copy), ([], [], ["A/f.pdf"]))

    async def test_busy_and_cancel(self):
        self.put("A/f.pdf")
        await archive.start_reindex(self.settings, 1)
        with self.assertRaises(ReindexBusy) as cm:
            await archive.start_reindex(self.settings, 2)
        self.assertEqual(cm.exception.owner_id, 1)
        archive.cancel_reindex(2)  # non è il proprietario
        self.assertTrue(archive.reindex_lock.locked())
        archive.cancel_reindex(1)
        self.assertFalse(archive.reindex_lock.locked())
        await archive.start_reindex(self.settings, 2)

    async def test_preview_expires(self):
        self.put("A/f.pdf")
        now = [1000.0]
        archive._clock = lambda: now[0]
        await archive.start_reindex(self.settings, 1)
        now[0] += archive.PREVIEW_TTL + 1
        with self.assertRaises(PreviewExpired):
            await archive.apply_reindex(1)
        self.assertFalse(archive.reindex_lock.locked())
        self.assertIsNone(self.row("A/f.pdf"))

    async def test_expired_lock_does_not_block_others(self):
        self.put("A/f.pdf")
        now = [1000.0]
        archive._clock = lambda: now[0]
        await archive.start_reindex(self.settings, 1)
        now[0] += archive.PREVIEW_TTL + 1
        await archive.start_reindex(self.settings, 2)  # nessun ReindexBusy

    async def test_apply_requires_preview(self):
        with self.assertRaises(PreviewExpired):
            await archive.apply_reindex(1)

    async def test_disk_changed_between_scan_and_apply(self):
        self.put("A/f.pdf")
        await archive.start_reindex(self.settings, 1)
        self.put("A/altro.pdf", "altro")
        with self.assertRaises(DiskChanged) as cm:
            await archive.apply_reindex(1)
        self.assertEqual(cm.exception.preview.added, ["A/altro.pdf", "A/f.pdf"])
        self.assertTrue(archive.reindex_lock.locked())  # il lock resta all'admin
        self.assertIsNone(self.row("A/f.pdf"))
        res = await archive.apply_reindex(1)
        self.assertEqual(res.added, 2)

    async def test_swap_two_files_is_safe(self):
        a = self.put("A/a.pdf", "1")
        b = self.put("A/b.pdf", "2")
        await self.reindex()
        a.write_text("2")
        b.write_text("1")
        for p in (a, b):
            os.utime(p, (OLD + 9, OLD + 9))
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual(sorted(pv.modified), ["A/a.pdf", "A/b.pdf"])
        await archive.apply_reindex(1)

    async def test_future_mtime_is_not_in_copy(self):
        self.put("A/futuro.pdf", "f", age=-3600)  # orologio del NAS avanti di un'ora
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual((pv.in_copy, pv.added), ([], ["A/futuro.pdf"]))

    async def test_unreadable_changed_file_not_removed(self):
        p = self.put("A/f.pdf", "v")
        await self.reindex()
        p.write_text("nuovo contenuto")
        os.utime(p, (OLD + 7, OLD + 7))
        p.chmod(0)
        self.addCleanup(p.chmod, 0o644)
        pv = await archive.start_reindex(self.settings, 1)
        self.assertEqual((pv.removed, pv.added, pv.modified), ([], [], []))

    async def test_apply_claims_preview_and_respects_cancel(self):
        self.put("A/f.pdf")
        await archive.start_reindex(self.settings, 1)
        res = await asyncio.gather(archive.apply_reindex(1), archive.apply_reindex(1), return_exceptions=True)
        self.assertEqual(sorted(type(r).__name__ for r in res), ["ApplyResult", "PreviewExpired"])
        # annullato mentre applica: non scrive e non libera il lock del reindex successivo
        self.put("A/g.pdf", "g")
        await archive.start_reindex(self.settings, 1)
        task = asyncio.create_task(archive.apply_reindex(1))
        await asyncio.sleep(0)  # apply sospeso nel to_thread
        archive.cancel_reindex(1)
        await archive.start_reindex(self.settings, 2)
        with self.assertRaises(PreviewExpired):
            await task
        self.assertIsNone(self.row("A/g.pdf"))
        self.assertTrue(archive.reindex_lock.locked())
        self.assertEqual(archive._owner_id, 2)

    async def test_atomic_tree_swap(self):
        self.put("A/f.pdf")
        before = archive.tree
        await self.reindex()
        self.assertIsNot(archive.tree, before)
        self.assertGreater(archive.tree.version, before.version)


if __name__ == "__main__":
    unittest.main()
