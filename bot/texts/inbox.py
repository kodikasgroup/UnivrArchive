"""Testi di T4: invii, moderazione, Gestisci, ticket (HTML)."""

from html import escape

# --- invio utente --------------------------------------------------------
SEND_BAD_EXT = "Questo tipo di file non è accettato. Formati ammessi: {allowed}."
SEND_TOO_BIG = "Il file è troppo grande (massimo {max_mb} MB)."
SEND_NO_NAME = "Non riesco a leggere il nome del file: rinominalo e riprova."
SEND_RATE = "Hai già {n} invii in attesa di revisione. Riprova quando lo staff li avrà guardati."
SEND_ALREADY = "Grazie, questo file lo abbiamo già."
SEND_ALREADY_LINK = 'Grazie, questo file lo abbiamo già: <a href="{link}">eccolo</a>.'
SEND_ERROR = "Non sono riuscito a scaricare il file, riprova tra poco."
PICK_PROMPT = "📚 <b>Per quale materia?</b>\nScegli la cartella giusta oppure «Non so»."
PICK_UNKNOWN_BTN = "❓ Non so"
PICK_EXPIRED = "Sessione scaduta: rimanda il file."
PICK_NOT_YOURS = "Non è il tuo invio."
SEND_THANKS = "🙏 Grazie! Il tuo materiale è in revisione: ti avviso appena lo staff lo guarda."
SEND_THANKS_N = "🙏 Grazie! I tuoi {n} file sono in revisione: ti avviso appena lo staff li guarda."
BACK_BTN = "↩️ Indietro"

# --- messaggi all'utente dopo la decisione -------------------------------
APPROVED_USER = "🎉 Il tuo file «{name}» è stato approvato: <b>+{credits} crediti</b>!"
REJECTED_USER = "Il tuo file «{name}» non è stato accettato.\nMotivo: {reason}"
REJECT_REASONS = {
    "dup": "è un duplicato",
    "unreadable": "illeggibile",
    "offtopic": "non pertinente",
    "other": "non adatto all'archivio",
}
REJECT_LABELS = {
    "dup": "Duplicato",
    "unreadable": "Illeggibile",
    "offtopic": "Non pertinente",
    "other": "Altro",
}

# --- scheda staff --------------------------------------------------------
CARD_NO_FOLDER = "non so"
SC_OK = "✅ +{n}"
SC_CHANGE = "📂 Cambia cartella"
SC_REJECT = "❌ Rifiuta"
SC_REINDEX = "🔄 Reindex ora"
SC_PRICE_ASK = "💰 La destinazione è in EXCLUSIVE: scegli il prezzo."
STAFF_ALREADY = "Già gestito"
STAFF_NEED_FOLDER = "Scegli prima la cartella"
STAFF_BAD_FOLDER = "Cartella non valida o non più disponibile"
STAFF_MOVE_ERROR = "Errore nello spostamento del file, vedi i log"
STAFF_WRONG_CHAT = "Qui non si può"
STAFF_REJECT_ASK = "Scegli il motivo del rifiuto."
STAFF_DEST_SET = "Destinazione impostata"
ADMIN_SAVED = "✅ Salvato in <code>{path}</code>\n⏳ Visibile al prossimo /reindex."
ADMIN_ASK_PRICE = "💰 Cartella in EXCLUSIVE: che prezzo hanno i file?"
ADMIN_SESSION_LOST = "Sessione scaduta: rimanda il file."


def card(name: str, size: int | None, user_label: str, user_id: int,
         suggested: str | None, chosen: str | None) -> str:
    lines = [f"📄 <b>{escape(name)}</b> · {fmt_size(size)}", f"da: {user_label} ({user_id})"]
    if chosen:
        lines.append(f"📂 → {escape(chosen)}")
    else:
        lines.append(f"suggerita: {escape(suggested) if suggested else CARD_NO_FOLDER}")
    return "\n".join(lines)


def card_approved(base: str, admin: str, credits: int, dest: str) -> str:
    return (f"{base}\n\n✅ Approvato da {admin} · +{credits}\n→ <code>{escape(dest)}</code>\n"
            "⏳ visibile al prossimo /reindex")


def card_rejected(base: str, admin: str, reason: str) -> str:
    return f"{base}\n\n❌ Rifiutato da {admin} · {escape(reason)}"


def user_label(username: str | None, first_name: str | None, user_id: int) -> str:
    if username:
        return "@" + escape(username)
    return escape(first_name or str(user_id))


def fmt_size(size: int | None) -> str:
    if not size:
        return "? MB"
    if size < 1024 * 1024:
        return f"{max(1, size // 1024)} KB"
    return f"{size / (1024 * 1024):.1f} MB"


# --- Gestisci ------------------------------------------------------------
M_PANEL = "⚙️ <b>Gestisci</b>: {where}"
M_HOME = "HOME"
M_BTN_MKDIR = "➕ Nuova cartella"
M_BTN_RENAME = "✏️ Rinomina"
M_BTN_MOVE = "📦 Sposta"
M_BTN_PRICE = "💰 Prezzo"
M_BTN_DELETE = "🗑 Elimina"
M_BTN_REINDEX = "🔄 Reindex"
M_BTN_BACK = "⬅️ Indietro"
M_ASK_MKDIR = "Scrivi il nome della nuova cartella in <code>{where}</code> (/annulla per uscire)."
M_ASK_RENAME = "Scrivi il nuovo nome per «{name}» (/annulla per uscire)."
M_DONE = "✅ Fatto. Visibile al prossimo /reindex."
M_CANCELLED = "Operazione annullata."
M_NOTHING = "Non c'è nessuna operazione in corso."
M_NOT_FOUND = "Elemento non trovato (forse già rimosso): rilancia /reindex."
M_PROTECTED = "Questo elemento non si può modificare da qui."
M_CONFLICT = "Esiste già un elemento con questo nome."
M_BAD_NAME = "Nome non valido."
M_DEST_INSIDE = "Non puoi spostare una cartella dentro se stessa."
M_EXCL_FOLDER = "Una cartella non si sposta dentro o fuori da EXCLUSIVE da qui: fallo da SFTP."
M_ASK_PRICE_MOVE = "💰 Il file entra in EXCLUSIVE: scegli il prezzo."
M_PRICE_ONLY_EXCL = "Il prezzo si imposta solo sui file sotto EXCLUSIVE."
M_ASK_PRICE = "💰 Scegli il nuovo prezzo."
M_CONFIRM_DEL = "🗑 Eliminare «{name}»? Va nel cestino, non viene cancellato."
M_BTN_CONFIRM = "✅ Sì, elimina"
M_BTN_CANCEL = "❌ Annulla"
M_ASK_DEST = "📦 Scegli la destinazione per «{name}»."
M_MKDIR_SET = "✅ Cartella creata e scelta come destinazione."

# --- ticket --------------------------------------------------------------
T_FEEDBACK_HELP = ("🗨 Scrivi il tuo messaggio dopo il comando, ad esempio:\n"
                   "<code>/feedback il bot è fantastico, aggiungete…</code>\n\n"
                   "Per chiedere la cancellazione dei tuoi dati scrivi qui la richiesta.")
T_REMOVAL_HELP = ("🚫 Indica il file da rimuovere (link del bot o nome) e il motivo, ad esempio:\n"
                  "<code>/rimozione https://t.me/bot?start=f_123 sono l'autore</code>")
T_THANKS = "Grazie, abbiamo ricevuto la tua segnalazione. Ti risponderemo qui."
T_TITLES = {
    "feedback": "🗨 <b>Feedback</b>",
    "report": "⚠️ <b>Segnalazione</b>",
    "removal": "🚫 <b>Richiesta rimozione</b>",
}
T_CLOSE_BTN = "✅ Chiudi"
T_REPLY_PREFIX = "💬 Risposta dello staff:"
T_CLOSED_TOAST = "Ticket chiuso"
T_ALREADY_CLOSED = "Già chiuso"
T_USER_BLOCKED = "L'utente ha bloccato il bot: risposta non consegnata."
T_REPLY_SENT = "✅ Risposta inviata"


def ticket_card(ticket_id: int, kind: str, user_label: str, user_id: int,
                node_label: str | None, text: str | None) -> str:
    lines = [f"{T_TITLES[kind]} #{ticket_id}", f"da: {user_label} ({user_id})"]
    if node_label:
        lines.append(f"file: {escape(node_label)}")
    if text:
        lines += ["", escape(text)]
    return "\n".join(lines)


def ticket_closed(base: str, admin: str) -> str:
    return f"{base}\n\n✅ Chiuso da {admin}"
