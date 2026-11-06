"""Testi (HTML) dei comandi admin, del reindex, del broadcast e del job notturno."""

from __future__ import annotations

from collections import Counter
from html import escape

TG_LIMIT = 4096
MAX_ITEMS = 5

# ── generici ────────────────────────────────────────────────────────────────
USER_NOT_FOUND = "Utente non trovato: usa l'ID numerico."
USER_AMBIGUOUS = "Più utenti con questo username: usa l'ID numerico."
CREDITS_USAGE = "Uso: <code>/crediti_add &lt;id|@username&gt; &lt;n&gt; [motivo]</code>"
VIP_USAGE = "Uso: <code>/vip &lt;id|@username&gt; &lt;giorni|0|off&gt;</code>"
BROADCAST_USAGE = "Rispondi con /broadcast al messaggio da inviare."

# ── crediti / VIP ───────────────────────────────────────────────────────────


def credits_insufficient(n: int) -> str:
    return f"Saldo insufficiente per togliere {abs(n)} crediti."


def credits_done(user_id: int, delta: int, balance: int) -> str:
    return f"✅ {delta:+d} crediti a <code>{user_id}</code>. Saldo: {balance}"


def credits_notify(delta: int, balance: int) -> str:
    verb = "ricevuto" if delta > 0 else "perso"
    return f"💰 Hai {verb} {abs(delta)} crediti. Saldo attuale: {balance}"


def vip_granted(user_id: int, until: str) -> str:
    when = "permanente" if until.startswith("9999") else f"fino al {escape(until)} UTC"
    return f"👑 VIP {when} per <code>{user_id}</code>"


def vip_revoked(user_id: int) -> str:
    return f"VIP revocato a <code>{user_id}</code>"


# ── /pending ────────────────────────────────────────────────────────────────
PENDING_NONE = "✅ Nessun invio in attesa."


def pending_list(rows: list[tuple[str, str]], total: int) -> str:
    """rows = (nome file, link al messaggio staff)."""
    lines = [f"📥 <b>Invii da moderare: {total}</b>"]
    for name, link in rows:
        lines.append(f'• <a href="{escape(link)}">{escape(name)}</a>')
    text = "\n".join(lines)
    if len(text) > TG_LIMIT:
        text = text[: text.rfind("\n", 0, TG_LIMIT - 20)] + "\n…"
    return text


# ── /stats ──────────────────────────────────────────────────────────────────


def stats(o: dict, top: list[tuple[str, int]]) -> str:
    lines = [
        "📊 <b>Statistiche</b>",
        f"👥 Utenti: {o['users']} (bloccati: {o['blocked']})",
        f"🟢 Attivi 7 giorni: {o['active_7']} · 30 giorni: {o['active_30']}",
        f"⬇️ Download: {o['downloads_total']} totali · {o['downloads_30']} negli ultimi 30 giorni",
        f"📥 Invii pendenti: {o['pending']} · 🎫 Ticket aperti: {o['tickets']}",
    ]
    if top:
        lines.append("\n🏆 <b>Top 10 file</b>")
        lines += [f"{i}. {escape(name)} — {n}" for i, (name, n) in enumerate(top, 1)]
    return "\n".join(lines)


# ── reindex ─────────────────────────────────────────────────────────────────
REINDEX_START = "⏳ Scansione dell'archivio…"
REINDEX_APPLYING = "⏳ Applico le modifiche…"
REINDEX_NONE = "✅ Nessuna modifica."
REINDEX_EXPIRED = "⌛ Anteprima scaduta, rilancia /reindex"
REINDEX_CANCELLED = "❌ Reindex annullato."


def reindex_progress(text: str) -> str:
    text = text.strip()
    return escape(text if text.startswith("⏳") else f"⏳ {text}")


def reindex_busy(owner: str) -> str:
    return f"Reindex già in corso da {escape(owner)}"


def upload_progress(base: str, done: int, total: int) -> str:
    return f"{base}\n⬆️ Caricati {done}/{total}"


def reindex_done(r) -> str:
    parts = []
    if r.added:
        parts.append(f"+{r.added} file")
    if r.modified:
        parts.append(f"{r.modified} modificat{'o' if r.modified == 1 else 'i'}")
    if r.moved:
        parts.append(f"{r.moved} spostat{'o' if r.moved == 1 else 'i'}")
    if r.removed:
        parts.append(f"{r.removed} rimoss{'o' if r.removed == 1 else 'i'}")
    return "✅ Archivio aggiornato: " + (", ".join(parts) or "nessuna modifica")


def _short(path: str, limit: int = 90) -> str:
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def _listing(items: list[str], n: int) -> list[str]:
    """Al massimo n righe di dettaglio, poi '…e altri N'."""
    if n == 0:
        return []
    lines = [f"   <code>{escape(_short(i))}</code>" for i in items[:n]]
    if len(items) > n:
        lines.append(f"   …e altri {len(items) - n}")
    return lines


def _added_groups(paths: list[str], n: int) -> str:
    if n == 0:
        return ""
    counts = Counter(p.rpartition("/")[0] or "(radice)" for p in paths)
    body = ", ".join(f"{escape(_short(d, 45))}: {c}" for d, c in counts.most_common(n))
    if len(counts) > n:
        body += ", …"
    return f"  ({body})"


def _build_preview(p, n: int) -> str:
    out = ["🗂 <b>Anteprima reindex</b>"]
    out.append(f"+{len(p.added)} file" + (_added_groups(p.added, n) if p.added else ""))
    if p.modified:
        out.append(f"~{len(p.modified)} modificat{'o' if len(p.modified) == 1 else 'i'}")
        out += _listing(p.modified, n)
    if p.moved:
        out.append(f"↪ {len(p.moved)} spostati/rinominati (ID conservati)")
        out += _listing([f"{a} → {b}" for a, b in p.moved], n)
    if p.removed:
        out.append(f"−{len(p.removed)} rimossi")
        out += _listing(p.removed, n)
    if p.removed_with_purchases:
        out.append(f"⚠ {len(p.removed_with_purchases)} rimossi con acquisti")
        out += _listing(p.removed_with_purchases, n)
    if p.hidden_no_price:
        out.append(f"⚠ {len(p.hidden_no_price)} file Exclusive senza prezzo (nascosti)")
        out += _listing(p.hidden_no_price, n)
    if p.hidden_over_max:
        out.append(f"⚠ {len(p.hidden_over_max)} prezzo oltre il massimo (nascosti)")
        out += _listing([f"{a} → {b}" for a, b in p.hidden_over_max], n)
    if p.exclusive_leaks:
        out.append(f"⚠ {len(p.exclusive_leaks)} Exclusive presenti anche tra i gratuiti")
        out += _listing([f"{a} = {b}" for a, b in p.exclusive_leaks], n)
    if p.price_changed:
        out.append(f"💰 {len(p.price_changed)} prezzo cambiato")
        out += _listing([f"{a}: {o} → {c}" for a, o, c in p.price_changed], n)
    if p.over_50mb:
        out.append(f"⚠ {len(p.over_50mb)} file oltre 50 MB")
        out += _listing(p.over_50mb, n)
    if p.in_copy:
        out.append(f"⏳ {len(p.in_copy)} file ancora in copia, rilancia /reindex tra poco")
    return "\n".join(out)


def reindex_preview(p) -> str:
    """Anteprima formattata, sempre <= 4096 caratteri (si riducono i dettagli)."""
    text = ""
    for n in (MAX_ITEMS, 3, 2, 1, 0):
        text = _build_preview(p, n)
        if len(text) <= TG_LIMIT:
            return text
    return text[: TG_LIMIT - 1] + "…"  # non raggiungibile in pratica


# ── broadcast ───────────────────────────────────────────────────────────────
BROADCAST_BUSY = "Un broadcast è già in corso."
BROADCAST_EXPIRED = "Richiesta scaduta: rilancia /broadcast."
BROADCAST_CANCELLED = "❌ Broadcast annullato."
BROADCAST_STARTED = "📣 Broadcast avviato…"


def broadcast_confirm(n: int) -> str:
    return f"Inviare a {n} utenti?"


def broadcast_progress(done: int, total: int, blocked: int) -> str:
    return f"📣 Inviati {done}/{total} · bloccati {blocked}"


def broadcast_summary(sent: int, blocked: int, errors: int) -> str:
    return f"✅ Broadcast concluso\nInviati: {sent}\nBloccati: {blocked}\nErrori: {errors}"


# ── primo avvio e job notturno ──────────────────────────────────────────────
EMPTY_INDEX = "🗂 L'archivio non è ancora indicizzato: lancia /reindex."


def stale_pending(ids: list[int]) -> str:
    shown = ", ".join(f"#{i}" for i in ids[:20])
    more = f" …e altri {len(ids) - 20}" if len(ids) > 20 else ""
    return f"⏰ {len(ids)} invii in attesa da oltre 30 giorni: {shown}{more}. Usa /pending."


def nightly_failed(steps: list[str]) -> str:
    return "⚠️ Job notturno: passi falliti: " + ", ".join(escape(s) for s in steps)
