# Requisiti — cosa preparare prima di avviare il bot

Checklist di tutto quello che serve **fuori dal codice**: bot, canali,
credenziali, hardware. Da fare una volta per il bot di produzione e,
se serve, una volta per il bot beta.

> Installazione vera e propria: [`INSTALLAZIONE.md`](INSTALLAZIONE.md). Versioni del software: [`SVILUPPO.md`](SVILUPPO.md#versioni).

---

## 1. Riepilogo

| # | Cosa | Prod | Beta | Finisce in `.env` come |
|---|---|---|---|---|
| 1 | Bot Telegram (@BotFather) | ✅ | opzionale | `BOT_TOKEN` / `BETA_BOT_TOKEN` |
| 2 | Canale privato **storage** | ✅ | ✅ se c'è il beta | `STORAGE_CHAT_ID` / `BETA_STORAGE_CHAT_ID` |
| 3 | Gruppo **staff** | ✅ | ✅ se c'è il beta | `STAFF_CHAT_ID` / `BETA_STAFF_CHAT_ID` |
| 4 | Chat **log errori** | opzionale | — | `LOG_CHAT_ID` |
| 5 | ID Telegram degli admin | ✅ | (stessi) | `ADMIN_IDS` |
| 6 | `api_id` / `api_hash` | opzionale (file > 50 MB) | (stessi) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` |
| 7 | Raspberry Pi + SSD | ✅ | (stesso) | — |
| 8 | Link donazioni | opzionale | — | `DONATION_LINK` |

Prod e beta **non condividono** canali né gruppi: un test non deve mai
toccare dati di produzione.

---

## 2. Bot Telegram (@BotFather)

Per **ogni** bot (prod, ed eventualmente beta):

| Comando in @BotFather | Valore | Perché |
|---|---|---|
| `/newbot` | nome e username | il token va in `BOT_TOKEN` (prod) o `BETA_BOT_TOKEN` |
| `/setinline` | placeholder es. `Cerca materiale…` | attiva la ricerca inline `@bot testo` |
| `/setinlinefeedback` | `Enabled` | serve per contare i download fatti da inline |
| `/setjoingroups` | `Enable` | il bot deve entrare nei gruppi dei corsi |
| `/setprivacy` | `Enable` (default) | nei gruppi il bot riceve solo i comandi, non tutti i messaggi |
| `/setdescription`, `/setabouttext` | testo breve | mostrato a chi apre il bot la prima volta |
| `/setuserpic` | `assets/brand/avatar-640.jpg` | già pensato per il ritaglio circolare di Telegram |
| Privacy policy (Bot Settings) | testo di `/privacy` | richiesto da Telegram per i bot che salvano dati |

**Non** serve impostare i comandi a mano: il bot li registra da solo
all'avvio (`setMyCommands`).

Il **bot di produzione usa lo stesso token del bot attuale**, così gli utenti
non devono cambiare nulla. Solo se si attiva il server Bot API locale serve,
prima del primo avvio, un `logOut` una tantum (procedura in
[`INSTALLAZIONE.md` §2 e §7](INSTALLAZIONE.md#2-prima-installazione)).

**Token:** se un token è mai finito in un commit, rigenerarlo con `/revoke`.

---

## 3. Canale storage (privato)

Deposito dei file: il bot ci carica **una copia di ogni file**, gli utenti non
lo vedono mai.

1. Telegram → Nuovo canale → **Privato**. Nome es. `UniVrArchive · Storage`.
2. Aggiungere il bot come **amministratore** con il permesso **Pubblica
   messaggi** (gli altri permessi non servono).
3. Aggiungere lo staff come membri (sola lettura) se si vuole poterlo consultare.
4. **Revocare il link d'invito** dopo aver aggiunto le persone.
5. Ricavare l'ID (vedi §8) → `STORAGE_CHAT_ID`.

Regole: nessuno scrive o cancella messaggi a mano, mai "fare pulizia".

---

## 4. Gruppo staff

Dove arrivano invii da moderare, segnalazioni, feedback e richieste di rimozione.
Lo staff risponde **con una reply** e il bot gira la risposta all'utente.

1. Nuovo **gruppo** (non canale: servono le reply). Privato.
2. Aggiungere il bot come **amministratore** (serve per leggere le reply anche
   con la privacy mode attiva).
3. Aggiungere lo staff.
4. ID → `STAFF_CHAT_ID`.

Chiunque sia nel gruppo legge tutto, ma **solo chi è in `ADMIN_IDS`** può
approvare, rifiutare, chiudere ticket o rispondere agli utenti.

---

## 5. Chat log errori (opzionale)

Un gruppo o canale privato con solo lo staff tecnico, bot admin. Riceve gli
errori con traceback. ID → `LOG_CHAT_ID`. Se vuoto, gli errori vanno solo nei
log del container.

---

## 6. Admin

`ADMIN_IDS` = ID numerici separati da virgola. Ognuno li scopre scrivendo a
`@userinfobot`. Gli username **non** valgono (cambiano). Gli admin valgono per
prod e beta.

---

## 7. `api_id` e `api_hash` (opzionali: server Bot API locale)

Servono **solo** se si attiva il server Bot API locale (`COMPOSE_PROFILES=local-api`),
che porta il limite dei file da 50 MB a 2 GB (32 file dell'archivio superano i
50 MB) e quello degli invii degli utenti da 20 MB a `SUBMIT_MAX_MB`. Senza, il bot
funziona con il server di Telegram e i file grandi restano visibili ma non
scaricabili (📦). Non danno accesso all'account di chi li crea: identificano solo
il programma (il server) verso Telegram; il bot continua a usare il suo token.

1. https://my.telegram.org → login con il numero di uno degli admin.
2. **API development tools** → crea un'app (nome e descrizione qualsiasi).
3. `api_id` → `TELEGRAM_API_ID`, `api_hash` → `TELEGRAM_API_HASH`.

Sono legati all'account di chi li crea: usare un account dello staff che resterà
nel progetto. Uno per tutti i bot.

---

## 8. Come trovare l'ID di un canale o gruppo

Gli ID di canali e supergruppi sono numeri negativi che iniziano con `-100`.
Il modo più semplice: aggiungere temporaneamente `@RawDataBot` (o inoltrare un
messaggio del canale a `@userinfobot`) e leggere `chat.id`; poi rimuoverlo.

---

## 9. Hardware

| Componente | Minimo | Consigliato |
|---|---|---|
| Raspberry Pi | Pi 3 con 1 GB | Pi 4/5 con 2+ GB |
| Sistema | Raspberry Pi OS **64 bit** (Debian 13 "trixie") | |
| Disco dati | SSD USB ≥ 32 GB (archivio 7,4 GB + inbox + backup) | SSD USB ≥ 128 GB |
| Backup | secondo disco o NAS per `rsync` notturno | |
| Rete | upload ≥ 10 Mbit/s (primo caricamento ≈ 1,5–2 ore) | via cavo |

La cartella del progetto (con `data/`) va **sull'SSD**, non sulla microSD.

---

## 10. Software sul Pi

- Docker Engine + plugin Docker Compose v5 (`docker compose version`).
- `git`.
- Nient'altro: Python, SQLite e il server Bot API girano nei container
  (`bot`, più `telegram-bot-api` e `bot-api-cleaner` se il server locale è attivo).

Le cartelle di `data/` esistono già nel repo (vuote). Al primo avvio il server
Bot API diventa proprietario di `data/bot-api/` (utente 101): è normale, non
va cambiato. Cosa contiene e perché: [`INSTALLAZIONE.md` §1.2](INSTALLAZIONE.md#12-databot-api-la-cartella-del-server-bot-api).

---

## 11. Gruppi dei corsi (dopo l'avvio)

Per ogni gruppo di corso dove si vuole `/materiale`:

1. Aggiungere il bot al gruppo (admin non necessario; admin consigliato per i
   messaggi effimeri fuori dalla finestra di 15 secondi).
2. Un admin di `ADMIN_IDS` scrive `/collega` nel gruppo e sceglie la cartella.

Nei gruppi non collegati il bot non risponde.

---

## 12. Checklist finale prima del primo avvio

- [ ] Bot creato/configurato in @BotFather (inline, inline feedback, gruppi, privacy policy)
- [ ] Canale storage privato, bot admin con "Pubblica messaggi", link d'invito revocato
- [ ] Gruppo staff, bot admin
- [ ] `ADMIN_IDS` raccolti
- [ ] (opzionale, file > 50 MB) `api_id` / `api_hash` da my.telegram.org e `COMPOSE_PROFILES=local-api`
- [ ] `.env` compilato da `.env.example`
- [ ] SSD montato, progetto clonato sull'SSD, `data/prod/archive/` copiato con `rsync -a`
- [ ] (opzionale) animazione di benvenuto: `cp assets/welcome.mp4 data/prod/media/`
- [ ] foto profilo del bot: `assets/brand/avatar-640.jpg` con `/setuserpic`
- [ ] Docker e Compose installati
- [ ] solo con il server locale: `logOut` del token (al momento del passaggio)
