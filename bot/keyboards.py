"""Tastiere e testi dei menu di navigazione (contratto §8)."""

import math
from typing import Literal

from aiogram.types import (
    CopyTextButton,
    DisabledButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot import archive
from bot.texts import browse as T

Mode = Literal["browse", "pick", "staff", "group"]

PAGE_SIZE = 10
HOME_PAGE_SIZE = 15  # la HOME dell'archivio reale (11 corsi + EXCLUSIVE) sta in una pagina
LIST_LIMIT = 30      # massimo bottoni nelle liste (ricerca, preferiti, ...)

_username = ""
_cache: dict[tuple, tuple[str, InlineKeyboardMarkup]] = {}
_cache_tree: tuple[int, int] | None = None


def set_bot_username(username: str) -> None:
    """Serve ai link (`t.me/<bot>?start=...`). Impostato da browse al primo uso."""
    global _username
    _username = username


def bot_username() -> str:
    return _username


def deep_link(kind: str, node_id: int) -> str:
    return f"https://t.me/{_username}?start={kind}_{node_id}"


# --- helper ------------------------------------------------------------------


def _btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def enter_data(mode: Mode, ctx: int | None, node_id: int, page: int = 0) -> str:
    """callback_data per entrare in una cartella (o cambiare pagina) nella modalità data."""
    suffix = f":{page}" if page else ""
    if mode == "pick":
        return f"pick:{node_id}{suffix}"
    if mode == "staff":
        return f"dsn:{ctx}:{node_id}{suffix}"
    if mode == "group":
        return f"grp:{node_id}{suffix}"
    return f"n:{node_id}{suffix}"


def short_crumb(node: archive.Node, depth: int = 2) -> str:
    """Ultimi `depth` antenati del nodo (per distinguere file omonimi)."""
    names = [n.name for n in archive.tree.breadcrumb(node.id)[:-1]]
    return " › ".join(names[-depth:])


def _folder_label(node: archive.Node, home: bool, tree: archive.Tree) -> str:
    if home:
        return f"✴{node.raw_name}✴" if node.path == archive.EXCLUSIVE else f"✏{node.name}✏"
    label = node.name
    if tree.is_new(node.id):
        label += " 🆕"
    return label


def _file_label(node: archive.Node) -> str:
    label = f"📖{node.name}📖 · {T.size(node.size)}"
    if node.price > 0:
        label = f"⭐ {label} · {node.price} cr"
    elif tree_is_new(node):
        label += " 🆕"
    return label


def tree_is_new(node: archive.Node) -> bool:
    return archive.tree.is_new(node.id)


# --- menu cartella -------------------------------------------------------------


def folder(node_id: int | None, page: int = 0, *, mode: Mode = "browse",
           ctx: int | None = None, is_admin: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    global _cache_tree
    tree = archive.tree
    admin = bool(is_admin) and mode == "browse"
    stamp = (id(tree), tree.version)
    if stamp != _cache_tree or len(_cache) > 5000:
        _cache.clear()
        _cache_tree = stamp
    key = (node_id or 0, page, mode, ctx, admin, _username)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    result = _build(tree, node_id, page, mode, ctx, admin)
    _cache[key] = result
    return result


def _build(tree: archive.Tree, node_id: int | None, page: int, mode: Mode,
           ctx: int | None, admin: bool) -> tuple[str, InlineKeyboardMarkup]:
    node = tree.get(node_id) if node_id else None
    if node is not None and not node.is_dir:  # un file non è una cartella: si mostra il padre
        node = tree.get(node.parent_id) if node.parent_id else None
    home = node is None
    nid = 0 if home else node.id

    children = tree.children(None if home else node.id)
    if mode != "browse":
        children = [c for c in children if c.is_dir]
    if mode == "pick":
        children = [c for c in children if not c.is_exclusive]

    size = HOME_PAGE_SIZE if home else PAGE_SIZE
    pages = max(1, math.ceil(len(children) / size))
    page = min(max(page, 0), pages - 1)
    chunk = children[page * size:(page + 1) * size]

    # --- testo ---
    parts: list[str] = []
    if not home:
        parts.append("📂 " + T.crumb([n.name for n in tree.breadcrumb(node.id)]))
    header = {"pick": T.HEADER_PICK, "staff": T.HEADER_STAFF, "group": T.HEADER_GROUP}.get(mode)
    if home:
        parts.append(T.START_TEXT if mode == "browse" else header)
    else:
        if header:
            parts.append(header)
        parts.append(T.level_text(node.depth, node.name, node.is_exclusive))
        if not children:
            parts.append(T.EMPTY)
    text = "\n".join(parts)

    # --- bottoni ---
    rows: list[list[InlineKeyboardButton]] = []
    two_cols = (not home) and node.depth == 2 and not node.is_exclusive
    pending: list[InlineKeyboardButton] = []
    for child in chunk:
        if child.is_dir:
            b = _btn(_folder_label(child, home, tree), enter_data(mode, ctx, child.id))
            if two_cols:
                pending.append(b)
                if len(pending) == 2:
                    rows.append(pending)
                    pending = []
                continue
        else:
            b = _btn(_file_label(child), f"n:{child.id}")
        if pending:
            rows.append(pending)
            pending = []
        rows.append([b])
    if pending:
        rows.append(pending)

    if pages > 1:
        rows.append([
            _page_button("◀️", enter_data(mode, ctx, nid, page - 1), page > 0),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop",
                                 disabled=DisabledButton()),
            _page_button("▶️", enter_data(mode, ctx, nid, page + 1), page < pages - 1),
        ])

    # azioni della modalità
    if mode == "browse":
        actions = [InlineKeyboardButton(text=T.BTN_SEARCH, switch_inline_query_current_chat="")]
        if not home and tree.free_files(node.id):
            actions.append(_btn(T.BTN_ALL, f"all:{node.id}"))
        if not home and _username:
            actions.append(InlineKeyboardButton(
                text=T.BTN_LINK_FOLDER,
                copy_text=CopyTextButton(text=deep_link("n", node.id))))
        rows.append(actions)
        if admin:
            rows.append([_btn(T.BTN_ADMIN, f"adm:menu:{nid}")])
    elif mode == "pick":
        if not home:
            rows.append([_btn(T.BTN_PICK_HERE, f"pick:{nid}:ok")])
        rows.append([_btn(T.BTN_PICK_UNKNOWN, "pick:0:ok")])
    elif mode == "staff":
        if not home:
            rows.append([_btn(T.BTN_STAFF_HERE, f"dst:{ctx}:{nid}")])
        rows.append([_btn(T.BTN_MKDIR, f"adm:mkdir:{nid}")])
    elif mode == "group" and not home:
        rows.append([_btn(T.BTN_GROUP_HERE, f"grp:{nid}:ok")])

    # navigazione (v1: al primo livello solo HOME)
    if not home:
        nav = []
        if node.depth > 1:
            nav.append(_btn(T.BACK_BUTTON, enter_data(mode, ctx, node.parent_id or 0)))
        nav.append(_btn(T.HOME_BUTTON, enter_data(mode, ctx, 0), style="primary"))
        rows.append(nav)

    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _page_button(text: str, data: str, enabled: bool) -> InlineKeyboardButton:
    if enabled:
        return _btn(text, data)
    return InlineKeyboardButton(text=text, callback_data="noop", disabled=DisabledButton())


# --- liste di nodi (ricerca, preferiti, recenti, novità) ------------------------


def node_list(title: str, nodes: list[archive.Node]) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for n in nodes[:LIST_LIMIT]:
        icon = "📂" if n.is_dir else "📖"
        where = short_crumb(n)
        label = f"{icon} {n.name}" + (f" — {where}" if where else "")
        if len(label) > 60:
            label = label[:59] + "…"
        rows.append([_btn(label, f"n:{n.id}")])
    rows.append([_btn(T.HOME_BUTTON, "n:0", style="primary")])
    return title, InlineKeyboardMarkup(inline_keyboard=rows)
