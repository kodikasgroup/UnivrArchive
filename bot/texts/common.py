"""Testi generici (HTML)."""
import html

GENERIC_ERROR = "⚠️ Qualcosa è andato storto. Riprova tra poco."
ONLY_PRIVATE = "Questo comando funziona solo in chat privata con il bot."
COMMAND_UNAVAILABLE = "Questo comando non è disponibile. Usa /help per vedere i comandi."
ADMIN_ONLY = "Comando riservato agli admin."

PRIVACY = (
    "<b>Privacy</b>\n\n"
    "Il bot salva solo quello che serve a farlo funzionare:\n"
    "• il tuo ID Telegram, nome e username (per crediti e acquisti);\n"
    "• i file che scarichi, per 12 mesi (per /recenti e le statistiche); "
    "il totale storico resta come semplice contatore;\n"
    "• i file che invii: finché sono approvati, oppure 30 giorni se vengono rifiutati;\n"
    "• i messaggi di feedback, segnalazioni e richieste di rimozione.\n\n"
    "Niente altro, niente terze parti.\n\n"
    "Per chiedere la cancellazione dei tuoi dati scrivi /feedback seguito dal messaggio."
)

_HELP = (
    "<b>Comandi</b>\n"
    "/start — apri l'archivio\n"
    "/cerca <i>testo</i> — cerca file e cartelle\n"
    "/preferiti — i tuoi preferiti\n"
    "/recenti — gli ultimi file scaricati\n"
    "/novita — i file aggiunti di recente\n"
    "/crediti — il tuo saldo e come guadagnarne\n"
    "/feedback <i>testo</i> — scrivi allo staff\n"
    "/rimozione — richiedi la rimozione di un materiale\n"
    "/privacy — quali dati salva il bot\n\n"
    "<b>Exclusive</b>\n"
    "I file nella cartella EXCLUSIVE si sbloccano con i crediti. "
    "I crediti si ottengono inviando materiale nuovo: scrivi al bot un file e, "
    "dopo la revisione dello staff, ricevi i crediti. Un file comprato resta tuo."
)
_DONATION = '\n\n<b>Donazioni</b>\nSe il progetto ti è utile puoi sostenerlo: <a href="{donation_link}">dona qui</a>.'


def help_text(donation_link: str = "") -> str:
    """Testo di /help; la sezione donazioni compare solo se il link è configurato."""
    if not donation_link:
        return _HELP
    return _HELP + _DONATION.format(donation_link=html.escape(donation_link, quote=True))
