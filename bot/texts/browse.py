"""Testi di navigazione, file, ricerca, crediti e gruppi (HTML)."""

import html
from datetime import UTC, datetime

# --- costanti ---------------------------------------------------------------

# ID dell'effetto messaggio "🎉" (elenco effetti documentato da Telegram).
# DA VERIFICARE a mano sul bot beta: se non si vede l'effetto, correggere qui.
EFFECT_PARTY = "5046509860389126442"

START_TEXT = (
    "📘📗📙📘📗📙📘📗📙📘📗📙\n"
    "Benvenuto/a nel bot <b>UniVrInfoArchive</b>: qui trovi molto materiale per "
    "preparare i tuoi esami. Scegli un corso qui sotto.\n"
    "<blockquote expandable>"
    "Comandi utili:\n"
    "/cerca testo - cerca un file o una cartella\n"
    "/crediti - i tuoi crediti\n"
    "/preferiti - i file che hai salvato\n"
    "/recenti - gli ultimi scaricati\n"
    "/novita - le ultime aggiunte\n"
    "/feedback messaggio - scrivici consigli o segnalazioni\n"
    "/help - tutte le informazioni\n\n"
    "Vuoi inviarci materiale? Mandalo come file direttamente al bot (se sono "
    "tanti, in una cartella compressa). Una volta revisionato riceverai crediti "
    "da usare nell'area ✴EXCLUSIVE✴. Con una donazione si diventa VIP: Exclusive "
    "senza limiti."
    "</blockquote>\n"
    "📕📕📕 Buon Studio 📕📕📕"
)

HOME_BUTTON = "🏠HOME"
BACK_BUTTON = "<< BACK"
EMPTY = "Sembra non ci sia nulla qua"
MOVED = "Questa cartella non esiste più: ti porto al livello più vicino."
FILE_GONE = "Questo file non è più disponibile."
EXCLUSIVE_ENTRY = (
    "Eccoci nel area ⭐️Exclusive⭐\n"
    "Qui i file che trovi hanno un COSTO in crediti indicato al inizio del nome "
    "questo credito verra scalato una volta che si richiede il suddetto file"
    "\n\nSi prega di non condividere i file con gli altri per rispetto degli "
    "sviluppatori e per poter usufruire di file nuovi"
)

HEADER_PICK = "📥 <b>Scegli la cartella</b> dove mettere il tuo file."
HEADER_STAFF = "🗂 <b>Scegli la cartella</b> di destinazione."
HEADER_GROUP = "🔗 <b>Scegli la cartella</b> da collegare a questo gruppo."

# --- testi per livello (depth = profondità della cartella mostrata) ----------


def _general_level(depth: int, n: str) -> str:
    if depth == 1:
        return f"Hai scelto:\n🗄{n}🗄"
    if depth == 2:
        return f"Hai scelto:\n{n}📚📚📚"
    if depth == 3:
        return "⏰Scegli il Materiale⏰"
    if depth == 4:
        return "💥ECCO IL MATERIALE DELLA SEZIONE💥"
    return f"Hai scelto:\n{n}"


def _exclusive_level(depth: int, n: str) -> str:
    # tabella del ramo EXCLUSIVE/, dai testi di ExclusiveButtonHandler v1
    if depth == 1:
        return EXCLUSIVE_ENTRY
    if depth == 2:
        return f"Hai scelto:\n{n}"
    if depth == 3:
        return f"Hai Scelto:\n{n}📚📚📚"
    if depth == 4:
        return "💥ECCO IL MATERIALE DELLA SEZIONE💥"
    return f"Hai scelto:\n{n}"


def level_text(depth: int, name: str, exclusive: bool) -> str:
    """Testo sopra i bottoni di una cartella. `name` è il nome mostrato (non escapato)."""
    n = html.escape(name)
    return _exclusive_level(depth, n) if exclusive else _general_level(depth, n)


# --- formattazione -----------------------------------------------------------


def size(n: int | None) -> str:
    if not n:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{n} B"  # pragma: no cover


_MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre")


def date_tag(dt: datetime) -> str:
    """Data con entità `date_time` (<tg-time>): mostrata nel fuso dell'utente.
    Il testo interno è il ripiego per i client che non la supportano."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    fallback = f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
    return f'<tg-time unix="{int(dt.timestamp())}" format="D">{fallback}</tg-time>'


def crumb(names: list[str], limit: int = 600) -> str:
    text = " › ".join(names)
    if len(text) > limit:
        text = "…" + text[-limit:]
    return html.escape(text)


def file_caption(name: str, names: list[str], file_size: int, added_at: datetime,
                 *, exclusive: bool = False) -> str:
    icon = "⭐" if exclusive else "📄"
    return (
        f"{icon} <b>{html.escape(name)}</b>\n"
        f"📂 {crumb(names)}\n"
        f"{size(file_size)} · aggiunto il {date_tag(added_at)}"
    )


# --- acquisto ----------------------------------------------------------------

HOW_TO_EARN = (
    "📨 <b>Come ottenere crediti</b>: invia al bot materiale utile (appunti, "
    "esami, riassunti). Quando lo staff lo approva ricevi dei crediti."
)


def purchase_card(name: str, file_size: int, price: int, balance: int) -> str:
    text = (
        f"⭐ <b>{html.escape(name)}</b> · {size(file_size)}\n"
        f"Costo: {price} crediti · Il tuo saldo: {balance}"
    )
    if balance < price:
        text += "\n\n" + HOW_TO_EARN
    return text


def buy_button(price: int) -> str:
    return f"✅ Acquista per {price} crediti"


CANCEL = "Annulla"
NOT_ENOUGH = "Crediti insufficienti"
BOUGHT = "✅ Acquistato!"
SEND_ERROR = ("😞 Non sono riuscito a inviarti il file. Riprova tra poco: se lo avevi "
              "acquistato non perdi nulla e non paghi due volte.")
OPEN_PRIVATE = "Questo file te lo mando in privato: aprimi e riprova."
OPEN_PRIVATE_BUTTON = "📩 Apri in privato"
SENT_PRIVATE = "📬 Te l'ho mandato in privato"

# --- azioni sui file ----------------------------------------------------------

BTN_SHARE = "📤 Condividi"
BTN_LINK = "🔗 Copia link"
BTN_SAVE = "⭐ Salva"
BTN_REPORT = "⚠️ Segnala"
FAV_ADDED = "⭐ Aggiunto ai preferiti"
FAV_REMOVED = "Rimosso dai preferiti"
REPORT_ASK = "Cosa c'è che non va?"
REPORT_REASONS = {
    "broken": "File rotto",
    "wrong": "File sbagliato",
    "place": "Nella cartella sbagliata",
}
REPORT_DONE = "✅ Segnalazione inviata, grazie!"
REPORT_ALREADY = "Hai già segnalato questo file."

# --- scarica tutto ------------------------------------------------------------

ALL_BUSY = "Download già in corso"
ALL_NONE = "Qui non ci sono file gratuiti da scaricare."
BTN_ALL = "📥 Scarica tutto"
BTN_SEARCH = "🔍 Cerca"
BTN_LINK_FOLDER = "🔗 Link"
BTN_ADMIN = "⚙️ Gestisci"
BTN_CONFIRM = "✅ Confermo"


def all_confirm(count: int, total: int) -> str:
    return f"Stai per ricevere {count} file ({size(total)}). Confermi?"


def all_progress(done: int, total: int) -> str:
    return f"📥 {done}/{total}…"


def all_done(done: int, total: int) -> str:
    if done == total:
        return f"✅ Fatto: {total} file inviati."
    return f"Finito: {done}/{total} file inviati, gli altri non sono riusciti."


# --- pick / staff / group ------------------------------------------------------

BTN_PICK_HERE = "📥 Metti qui"
BTN_PICK_UNKNOWN = "🤷 Non so"
BTN_STAFF_HERE = "📥 Salva qui"
BTN_MKDIR = "➕ Nuova cartella"
BTN_GROUP_HERE = "🔗 Collega qui"

# --- ricerca e liste -------------------------------------------------------------

SEARCH_USAGE = "Scrivi cosa cerchi dopo il comando, es. <code>/cerca analisi</code>"


def search_results(query: str, count: int) -> str:
    if not count:
        return f"Nessun risultato per <b>{html.escape(query)}</b>."
    return f"🔍 Risultati per <b>{html.escape(query)}</b>:"


FAV_TITLE = "⭐ <b>I tuoi preferiti</b>"
FAV_EMPTY = "Non hai ancora preferiti. Tocca ⭐ Salva sotto un file per aggiungerlo."
RECENT_TITLE = "🕘 <b>Scaricati di recente</b>"
RECENT_EMPTY = "Non hai ancora scaricato nulla."
NEWS_TITLE = "🆕 <b>Novità</b> degli ultimi 7 giorni"
NEWS_EMPTY = "Nessuna novità negli ultimi 7 giorni."


def news_body(groups: list[tuple[str, int]]) -> str:
    lines = [f"📂 {html.escape(p)}: {n}" for p, n in groups[:15]]
    return NEWS_TITLE + "\n" + "\n".join(lines)


# --- crediti -----------------------------------------------------------------------


def credits_text(credits: int, vip_until: str | None, is_vip: bool) -> str:
    text = f"⭐️Crediti -> {credits}"
    if is_vip:
        if vip_until and vip_until.startswith("9999"):
            text += "\n👑 Sei VIP: Exclusive senza limiti."
        else:
            text += f"\n👑 Sei VIP fino al {(vip_until or '')[:10]}."
    text += "\n\n" + HOW_TO_EARN
    return text


# --- gruppi -----------------------------------------------------------------------------

GROUP_LINKED = "✅ Gruppo collegato alla cartella <b>{name}</b>."
GROUP_UNLINKED = "✅ Gruppo scollegato."
GROUP_NOT_LINKED = "Questo gruppo non era collegato."
GROUP_PICK_FIRST = "Scegli prima una cartella."
ONLY_ADMIN = "Solo gli admin possono farlo."
MATERIALE_PRIVATE = "Usa /materiale nei gruppi dei corsi. Qui puoi usare /start."

# --- generici -----------------------------------------------------------------------------

LEGACY_FALLBACK = "Questo comando non esiste più."
NOT_FOUND = "Non trovo quello che cerchi."
