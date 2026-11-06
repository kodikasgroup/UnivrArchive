"""Archivio: regole sui nomi, scansione del disco, reindex con anteprima, albero in RAM."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import stat
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from bot.db import nodes as db_nodes
from bot.db.nodes import NodeWrite

if TYPE_CHECKING:
    from bot.config import Settings

log = logging.getLogger(__name__)

EXCLUSIVE = "EXCLUSIVE"
PRICE_RE = re.compile(r"^(\d+)\.?")  # "5.nome.pdf" e "10NomeFile.pdf"
_IGNORED_NAMES = {"thumbs.db", "desktop.ini"}
_IGNORED_SUFFIXES = (".part", ".tmp", ".crdownload")
IN_COPY_SECONDS = 30
OVER_50MB = 50 * 1024 * 1024
PREVIEW_TTL = 600.0  # secondi: scadenza dell'anteprima (modificabile nei test)
_clock = time.monotonic  # iniettabile nei test
_UTC = timezone.utc
_DT_FORMAT = "%Y-%m-%d %H:%M:%S"


# ───────────────────────── regole sui nomi ─────────────────────────

def parse_name(raw: str, rel_path: str, is_dir: bool) -> tuple[str, int]:
    """Nome da mostrare e prezzo. Il prezzo vale solo per i file sotto EXCLUSIVE/."""
    price = 0
    if not is_dir and rel_path.startswith(EXCLUSIVE + "/"):
        if (m := PRICE_RE.match(raw)) and raw[m.end() :].strip():
            price, raw = int(m.group(1)), raw[m.end() :]
    return raw.replace("_", " ").replace("-", " ").strip(), price


def is_hidden(name: str) -> bool:
    """File da ignorare del tutto (nascosti, temporanei, di sistema)."""
    n = name.lower()
    return n.startswith(".") or n.startswith("~$") or n in _IGNORED_NAMES or n.endswith(_IGNORED_SUFFIXES)


def natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", s)]


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, _UTC)
    return datetime.strptime(value, _DT_FORMAT).replace(tzinfo=_UTC)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(_UTC).strftime(_DT_FORMAT)


# ───────────────────────── albero in RAM ─────────────────────────

@dataclass(frozen=True)
class Node:
    id: int
    parent_id: int | None
    name: str
    raw_name: str
    path: str
    is_dir: bool
    depth: int
    is_exclusive: bool
    price: int
    size: int
    sha256: str | None
    added_at: datetime


def _sort_key(n: Node):
    return (not n.is_dir, natural_key(n.name), n.path)


_version = 0


class Tree:
    """Albero immutabile: solo nodi visibili, più un indice dei padri per i rimossi."""

    def __init__(self, rows: list[tuple] = ()):
        # rows: (id, path, parent_id, is_dir, price, size, sha256, added_at, hidden, removed)
        global _version
        _version += 1
        self.version = _version
        self._parent_of: dict[int, int | None] = {r[0]: r[2] for r in rows}
        nodes: dict[int, Node] = {}
        for r in sorted(rows, key=lambda r: r[1].count("/")):
            id_, path, parent_id, is_dir, price, size, sha, added_at, hidden, removed = r
            if hidden or removed or (parent_id is not None and parent_id not in nodes):
                continue
            raw = path.rpartition("/")[2]
            name, _ = parse_name(raw, path, bool(is_dir))
            nodes[id_] = Node(
                id=id_, parent_id=parent_id, name=name, raw_name=raw, path=path, is_dir=bool(is_dir),
                depth=path.count("/") + 1, is_exclusive=path == EXCLUSIVE or path.startswith(EXCLUSIVE + "/"),
                price=0 if is_dir else price, size=size or 0, sha256=sha, added_at=_utc(added_at),
            )
        self._nodes = nodes
        kids: dict[int | None, list[Node]] = defaultdict(list)
        for n in nodes.values():
            kids[n.parent_id].append(n)
        self._children = {k: tuple(sorted(v, key=_sort_key)) for k, v in kids.items()}
        # data del file più recente contenuto in ogni nodo (per 🆕 sulle cartelle)
        newest: dict[int, datetime] = {}
        for n in nodes.values():
            if n.is_dir:
                continue
            cur: int | None = n.id
            while cur is not None:
                if cur not in newest or newest[cur] < n.added_at:
                    newest[cur] = n.added_at
                cur = nodes[cur].parent_id
        self._newest = newest
        self._by_sha: dict[str, list[Node]] = defaultdict(list)
        for n in nodes.values():
            if n.sha256:
                self._by_sha[n.sha256].append(n)
        self._search_index = [(_normalize(n.name), n) for n in sorted(nodes.values(), key=_sort_key)]

    def get(self, node_id: int) -> Node | None:
        return self._nodes.get(node_id)

    def children(self, node_id: int | None) -> list[Node]:
        return list(self._children.get(node_id, ()))

    def breadcrumb(self, node_id: int) -> list[Node]:
        chain: list[Node] = []
        cur = self._nodes.get(node_id)
        while cur is not None:
            chain.append(cur)
            cur = self._nodes.get(cur.parent_id) if cur.parent_id is not None else None
        return chain[::-1]

    def nearest_visible(self, node_id: int) -> Node | None:
        cur: int | None = node_id
        seen = 0
        while cur is not None and seen < 10_000:
            if cur in self._nodes:
                return self._nodes[cur]
            cur = self._parent_of.get(cur)
            seen += 1
        return None

    def is_new(self, node_id: int, days: int = 7) -> bool:
        newest = self._newest.get(node_id)
        return newest is not None and newest >= datetime.now(_UTC) - timedelta(days=days)

    def new_files(self, days: int = 7) -> list[Node]:
        limit = datetime.now(_UTC) - timedelta(days=days)
        found = [n for n in self._nodes.values() if not n.is_dir and n.added_at >= limit]
        return sorted(found, key=lambda n: (-n.added_at.timestamp(), natural_key(n.name)))

    def free_files(self, node_id: int) -> list[Node]:
        return [n for n in self._children.get(node_id, ()) if not n.is_dir and n.price == 0]

    def search(self, query: str, limit: int = 50, *, include_exclusive: bool) -> list[Node]:
        q = _normalize(query).strip()
        if not q:
            return []
        hits = [
            n for norm, n in self._search_index if q in norm and (include_exclusive or not n.is_exclusive)
        ]
        hits.sort(key=lambda n: n.is_dir)  # prima i file (sort stabile: ordine naturale conservato)
        return hits[:limit]

    def find_by_sha256(self, sha256: str) -> list[Node]:
        return list(self._by_sha.get(sha256, ()))


tree: Tree = Tree()


def load_from_db() -> None:
    """Ricostruisce l'albero dall'indice su DB (non legge il disco)."""
    global tree
    tree = Tree(db_nodes.load_all_for_tree())


# ───────────────────────── anteprima / risultati ─────────────────────────

@dataclass(frozen=True)
class Preview:
    created_at: datetime
    added: list[str]
    modified: list[str]
    moved: list[tuple[str, str]]
    removed: list[str]
    price_changed: list[tuple[str, int, int]]
    hidden_no_price: list[str]
    hidden_over_max: list[tuple[str, int]]
    exclusive_leaks: list[tuple[str, str]]
    removed_with_purchases: list[str]
    in_copy: list[str]
    over_50mb: list[str]
    dirty: bool = False  # cambiamenti non elencati (cartelle, visibilità)

    @property
    def is_empty(self) -> bool:
        """Nessuna modifica da applicare (gli avvisi non contano)."""
        return not (
            self.added or self.modified or self.moved or self.removed or self.price_changed or self.dirty
        )


@dataclass(frozen=True)
class ApplyResult:
    added: int
    modified: int
    moved: int
    removed: int
    to_upload: int


class ReindexBusy(Exception):
    def __init__(self, owner_id: int):
        super().__init__(f"reindex già in corso da {owner_id}")
        self.owner_id = owner_id


class PreviewExpired(Exception):
    pass


class DiskChanged(Exception):
    def __init__(self, preview: Preview):
        super().__init__("il disco è cambiato dopo l'anteprima")
        self.preview = preview


# ───────────────────────── scansione del disco (thread) ─────────────────────────

_Raw = tuple[str, bool, int, float]  # path, is_dir, size, mtime


def _walk(root: Path) -> list[_Raw]:
    out: list[_Raw] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(
            d for d in dirnames if not is_hidden(d) and not os.path.islink(os.path.join(dirpath, d))
        )
        for d in dirnames:
            out.append((prefix + d, True, 0, 0.0))
        for f in sorted(filenames):
            if is_hidden(f):
                continue
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                out.append((prefix + f, False, st.st_size, st.st_mtime))
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class _Scan:
    files: dict[str, tuple[int, float, str]]  # path -> (size, mtime, sha256)
    dirs: set[str]
    in_copy: list[str]
    signature: frozenset


def _scan(
    root: Path,
    known: dict[str, tuple[int, float, str | None]],
    cache: dict[tuple[str, int, float], str],
    progress: Callable[[str], Awaitable[None]] | None,
    loop: asyncio.AbstractEventLoop,
) -> _Scan:
    raw = _walk(root)
    now = time.time()
    files: dict[str, tuple[int, float, str]] = {}
    dirs: set[str] = set()
    in_copy: list[str] = []
    to_hash: list[tuple[str, int, float]] = []
    for path, is_dir, size, mtime in raw:
        if is_dir:
            dirs.add(path)
            continue
        k = known.get(path)
        # ancora in copia: escluso (se già noto, resta com'è). mtime nel futuro = file normale
        if 0 <= now - mtime < IN_COPY_SECONDS:
            in_copy.append(path)
            if k and k[2]:
                files[path] = (k[0], k[1], k[2])
            continue
        if k and k[2] and k[0] == size and k[1] == mtime:
            files[path] = (size, mtime, k[2])
        elif (sha := cache.get((path, size, mtime))) is not None:
            files[path] = (size, mtime, sha)
        else:
            to_hash.append((path, size, mtime))
    last = time.monotonic()
    for i, (path, size, mtime) in enumerate(to_hash, 1):
        try:
            sha = _sha256_file(root / path)
        except OSError as e:
            log.warning("impossibile leggere %s: %s", path, e)
            if (k := known.get(path)) and k[2]:  # già noto: resta com'è, si riprova al prossimo reindex
                files[path] = (k[0], k[1], k[2])
            continue
        cache[(path, size, mtime)] = sha
        files[path] = (size, mtime, sha)
        if progress and time.monotonic() - last >= 5:
            last = time.monotonic()
            asyncio.run_coroutine_threadsafe(progress(f"Hash {i}/{len(to_hash)}…"), loop)
    return _Scan(files, dirs, in_copy, frozenset(raw))


# ───────────────────────── piano (calcolo puro) ─────────────────────────

@dataclass
class _Old:
    id: int
    path: str
    parent_id: int | None
    is_dir: bool
    price: int
    size: int
    mtime: float
    sha: str | None
    hidden: bool


@dataclass
class _Plan:
    writes: list[NodeWrite]
    removed_ids: list[int]
    removed_file_ids: dict[int, str]  # id -> path (solo file)
    preview_fields: dict


def _classify(path: str, is_dir: bool, price_max: int) -> tuple[int, bool, str | None]:
    """(prezzo, nascosto, motivo)."""
    if is_dir or not path.startswith(EXCLUSIVE + "/"):
        return 0, False, None
    _, price = parse_name(path.rpartition("/")[2], path, False)
    if price <= 0:
        return 0, True, "no_price"
    if price > price_max:
        return 0, True, "over_max"
    return price, False, None


def _build_plan(
    old_rows: list[tuple],
    removed_rows: list[tuple],
    scan: _Scan,
    price_max: int,
    first_import: bool,
    now: str,
) -> _Plan:
    old = [_Old(r[0], r[1], r[2], bool(r[3]), r[4], r[5] or 0, r[6] or 0.0, r[7], bool(r[8])) for r in old_rows]
    old_by_id = {o.id: o for o in old}
    old_files = {o.path: o for o in old if not o.is_dir}
    old_dirs = {o.path: o for o in old if o.is_dir}

    assigned: dict[str, int] = {}  # nuovo path -> id esistente
    kind: dict[str, str] = {}  # same | modified | moved | resurrect | inherit
    moved_from: dict[str, str] = {}

    # 1. file con lo stesso percorso
    for p, (_, _, sha) in scan.files.items():
        if (o := old_files.get(p)) is not None:
            assigned[p] = o.id
            kind[p] = "same" if o.sha == sha else "modified"

    # 2. file spostati/rinominati: sparito + nuovo con lo stesso sha256
    gone = {p: o for p, o in old_files.items() if p not in scan.files}
    by_sha: dict[str, list[str]] = defaultdict(list)
    for p in sorted(gone):
        by_sha[gone[p].sha or ""].append(p)
    for p in sorted(q for q in scan.files if q not in assigned):
        cands = by_sha.get(scan.files[p][2])
        if cands:
            base = p.rpartition("/")[2]
            pick = next((c for c in cands if c.rpartition("/")[2] == base), cands[0])
            cands.remove(pick)
            assigned[p] = gone[pick].id
            kind[p] = "moved"
            moved_from[p] = pick

    # 3. percorso già usato da un file rimosso: riuso solo se lo sha256 coincide
    removed_files_at: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
    removed_dirs_at: dict[str, int] = {}
    for id_, path, sha, is_dir in removed_rows:  # dalla più vecchia: l'ultima vince
        if is_dir:
            removed_dirs_at[path] = id_
        else:
            removed_files_at[path].append((id_, sha))
    for p in sorted(q for q in scan.files if q not in assigned):
        for id_, sha in reversed(removed_files_at.get(p, [])):
            if sha == scan.files[p][2]:
                assigned[p] = id_
                kind[p] = "resurrect"
                break

    # 4. cartelle: stesso percorso; poi le nuove, dal basso verso l'alto
    for p in scan.dirs:
        if (o := old_dirs.get(p)) is not None:
            assigned[p] = o.id
            kind[p] = "same"
    gone_dir_ids = {o.id for p, o in old_dirs.items() if p not in scan.dirs}
    children: dict[str, list[str]] = defaultdict(list)
    for p in list(scan.files) + list(scan.dirs):
        children[p.rpartition("/")[0]].append(p)
    claimed: set[int] = set()
    for d in sorted((p for p in scan.dirs if p not in old_dirs), key=lambda p: (-p.count("/"), p)):
        votes: Counter[int] = Counter()
        for c in children.get(d, ()):
            oid = assigned.get(c)
            parent = old_by_id[oid].parent_id if oid in old_by_id else None
            if parent in gone_dir_ids and parent not in claimed:
                votes[parent] += 1
        if votes:
            best = sorted(votes, key=lambda i: (-votes[i], old_by_id[i].path))[0]
            assigned[d], kind[d] = best, "inherit"
            claimed.add(best)
        elif (rid := removed_dirs_at.get(d)) is not None:
            assigned[d], kind[d] = rid, "resurrect"

    used = set(assigned.values())
    removed_old = [o for o in old if o.id not in used]

    # 5. scritture e anteprima
    writes: list[NodeWrite] = []
    added: list[str] = []
    modified: list[str] = []
    moved: list[tuple[str, str]] = []
    price_changed: list[tuple[str, int, int]] = []
    no_price: list[str] = []
    over_max: list[tuple[str, int]] = []
    over_50: list[str] = []
    dirty = bool(removed_old)

    def ts(mtime: float) -> str:
        return _fmt(datetime.fromtimestamp(mtime, _UTC))

    entries = [(p, True) for p in sorted(scan.dirs)] + [(p, False) for p in sorted(scan.files)]
    for p, is_dir in entries:
        size, mtime, sha = (0, 0.0, None) if is_dir else scan.files[p]
        price, hidden, why = _classify(p, is_dir, price_max)
        if why == "no_price":
            no_price.append(p)
        elif why == "over_max":
            over_max.append((p, _parse_price(p)))
        id_ = assigned.get(p)
        k = kind.get(p)
        added_at = None
        if id_ is None or k == "resurrect":
            added_at = ts(mtime) if first_import and not is_dir else now
        if id_ is None:
            op = "insert"
        elif k == "same":
            o = old_by_id[id_]
            if o.price != price or o.hidden != hidden:
                op = "update"
            elif o.size != size or o.mtime != mtime:
                op = "touch"
            else:
                op = "keep"
        else:
            op = "update"
        if op in ("insert", "update"):
            dirty = True
        o = old_by_id.get(id_) if id_ is not None else None
        if o is not None and not is_dir and not o.hidden and not hidden and o.price != price:
            price_changed.append((p, o.price, price))
        if not is_dir:
            if k == "modified":
                modified.append(p)
            elif k == "moved":
                moved.append((moved_from[p], p))
            elif id_ is None or k == "resurrect":
                added.append(p)
            if k != "same" and size > OVER_50MB and k != "moved":
                over_50.append(p)
        writes.append(NodeWrite(p, is_dir, price, size, mtime, sha, hidden, op, id_, added_at))

    # file Exclusive il cui contenuto è anche in una cartella gratuita
    by_content: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for p, (_, _, sha) in scan.files.items():
        by_content[sha][0 if p.startswith(EXCLUSIVE + "/") else 1].append(p)
    leaks = [(e, f) for ex, free in by_content.values() if ex and free for e in sorted(ex) for f in sorted(free)]

    removed_files = {o.id: o.path for o in removed_old if not o.is_dir}
    return _Plan(
        writes=writes,
        removed_ids=[o.id for o in removed_old],
        removed_file_ids=removed_files,
        preview_fields=dict(
            added=sorted(added), modified=sorted(modified), moved=sorted(moved, key=lambda m: m[1]),
            removed=sorted(removed_files.values()), price_changed=sorted(price_changed),
            hidden_no_price=sorted(no_price), hidden_over_max=sorted(over_max), exclusive_leaks=sorted(leaks),
            in_copy=sorted(scan.in_copy), over_50mb=sorted(over_50), dirty=dirty,
        ),
    )


def _parse_price(path: str) -> int:
    m = PRICE_RE.match(path.rpartition("/")[2])
    return int(m.group(1)) if m else 0


# ───────────────────────── reindex: stato, lock, anteprima ─────────────────────────

reindex_lock = asyncio.Lock()


@dataclass
class _State:
    admin_id: int
    settings: Settings
    preview: Preview
    plan: _Plan
    signature: frozenset
    cache: dict
    expires: float


_state: _State | None = None
_owner_id: int | None = None
_timer: asyncio.TimerHandle | None = None
_run: object | None = None  # gettone del reindex in corso: chi ha un gettone vecchio non tocca nulla


def _release(token: object | None = None) -> None:
    """Libera stato e lock. Con `token`, solo se è ancora il reindex in corso."""
    global _state, _owner_id, _timer, _run
    if token is not None and token is not _run:
        return
    _run = None
    _state = None
    _owner_id = None
    if _timer is not None:
        _timer.cancel()
        _timer = None
    if reindex_lock.locked():
        reindex_lock.release()


def _expire_if_stale() -> None:
    if _state is not None and _clock() >= _state.expires:
        _release(_run)


def _arm_timer() -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
    _timer = asyncio.get_running_loop().call_later(PREVIEW_TTL + 1, _expire_if_stale)


def _known(old_rows: list[tuple]) -> dict[str, tuple[int, float, str | None]]:
    return {r[1]: (r[5] or 0, r[6] or 0.0, r[7]) for r in old_rows if not r[3]}


def _check_current(token: object) -> None:
    """Dopo ogni await: se nel frattempo il reindex è stato annullato o è scaduto, non si scrive nulla."""
    if _run is not token:
        raise PreviewExpired()


async def _scan_and_plan(settings, admin_id, progress, cache, token) -> Preview:
    """Scansiona, calcola il piano, registra lo stato. Il chiamante tiene il lock."""
    global _state
    loop = asyncio.get_running_loop()
    old_rows = db_nodes.load_active()
    removed_rows = db_nodes.load_removed()
    first_import = db_nodes.count_nodes() == 0
    now_dt = datetime.now(_UTC)
    now = _fmt(now_dt)

    def work() -> tuple[_Scan, _Plan]:
        scan = _scan(Path(settings.archive_dir), _known(old_rows), cache, progress, loop)
        return scan, _build_plan(old_rows, removed_rows, scan, settings.price_max, first_import, now)

    scan, plan = await asyncio.to_thread(work)
    _check_current(token)
    with_purchases = db_nodes.ids_with_purchases(plan.removed_file_ids)
    fields = dict(plan.preview_fields)
    fields["removed_with_purchases"] = sorted(plan.removed_file_ids[i] for i in with_purchases)
    preview = Preview(created_at=now_dt, **fields)
    touches = [w for w in plan.writes if w.op == "touch"]
    if preview.is_empty:
        if touches:  # solo mtime cambiati: nessuna modifica visibile
            db_nodes.apply_touches(touches)
        _release(token)
        return preview
    _state = _State(admin_id, settings, preview, plan, scan.signature, cache, _clock() + PREVIEW_TTL)
    _arm_timer()
    return preview


async def start_reindex(
    settings: Settings, admin_id: int, progress: Callable[[str], Awaitable[None]] | None = None
) -> Preview:
    """Scansiona il disco e prepara l'anteprima (10 minuti). Con anteprima vuota il lock si libera da solo."""
    global _owner_id, _run
    _expire_if_stale()
    if reindex_lock.locked():
        raise ReindexBusy(_owner_id if _owner_id is not None else 0)
    await reindex_lock.acquire()
    _owner_id = admin_id
    _run = token = object()
    try:
        return await _scan_and_plan(settings, admin_id, progress, {}, token)
    except BaseException:
        _release(token)
        raise


async def apply_reindex(admin_id: int) -> ApplyResult:
    global _state
    _expire_if_stale()
    st = _state
    if st is None:
        raise PreviewExpired()
    if st.admin_id != admin_id:
        raise ReindexBusy(st.admin_id)
    # si prende l'anteprima prima del primo await: un secondo click trova PreviewExpired
    _state = None
    token = _run
    try:
        # il disco è cambiato tra anteprima e click? (stat veloce, niente hash)
        current = await asyncio.to_thread(lambda: frozenset(_walk(Path(st.settings.archive_dir))))
        _check_current(token)
        if current != st.signature:
            preview = await _scan_and_plan(st.settings, admin_id, None, st.cache, token)
            raise DiskChanged(preview)
        plan = st.plan
        db_nodes.apply_changes(plan.removed_ids, plan.writes, _fmt(datetime.now(_UTC)))
        load_from_db()
        p = st.preview
        result = ApplyResult(
            added=len(p.added), modified=len(p.modified), moved=len(p.moved), removed=len(p.removed),
            to_upload=db_nodes.count_to_upload(),
        )
    except DiskChanged:
        raise
    except BaseException:
        _release(token)
        raise
    _release(token)
    return result


def cancel_reindex(admin_id: int) -> None:
    if _owner_id == admin_id:
        _release(_run)
