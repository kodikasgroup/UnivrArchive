# Installazione e gestione del server

Come installare, avviare, aggiornare e fare il backup di UniVrArchive su un
Raspberry Pi (o qualsiasi macchina con Docker). Prima di iniziare: tutto quello
che va preparato su Telegram è in [`REQUISITI.md`](REQUISITI.md).

---

## 1. Cosa gira

| Container | Cosa fa |
|---|---|
| `bot` | il bot (Python 3.14, aiogram 3.31) |
| `telegram-bot-api` | **opzionale** (profilo `local-api`): server Bot API locale, file fino a 2 GB |
| `bot-api-cleaner` | **opzionale** (profilo `local-api`): cancella dopo 24 ore i file scaricati dal server locale |
| `bot-beta` | bot di test, solo con il profilo `beta` |

### Server di Telegram o server locale

| | Server di Telegram (default) | Server locale (`COMPOSE_PROFILES=local-api`) |
|---|---|---|
| File che il bot invia | fino a 50 MB; quelli più grandi restano visibili con 📦 ma non si scaricano | fino a 2 GB |
| File che gli utenti inviano | fino a 20 MB | fino a `SUBMIT_MAX_MB` (default 200) |
| Serve | niente | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (da my.telegram.org) e un `logOut` una tantum |

Si sceglie solo dal `.env`: con `COMPOSE_PROFILES=local-api` partono anche i due
container opzionali e il bot usa il server locale; vuoto, il bot usa quello di
Telegram. Per bot di test e server locale insieme: `COMPOSE_PROFILES=local-api,beta`.

Tutti i dati stanno nella cartella del progetto:

```
data/
├── prod/          archive/ inbox/ trash/ media/ backups/  bot.db
├── beta/          stessa struttura, per il bot di test
└── bot-api/       file del server Bot API (proprietario: utente 101, è normale)
```

Le cartelle esistono già nel repo, vuote. Il loro contenuto non va mai su git.
La configurazione sta solo in `.env`.

### 1.1 Cosa contiene ogni cartella

| Cartella | Contenuto | Chi la scrive | Nel backup? |
|---|---|---|---|
| `prod/archive/` | il materiale, organizzato in cartelle. È la **fonte di verità**: il bot mostra quello che c'è qui dopo `/reindex` | lo staff (SFTP, `rsync`, ⚙️ Gestisci), il bot quando approva un invio | **sì** |
| `prod/bot.db` | database: utenti, crediti, acquisti, indice dei file, invii, ticket | il bot | **sì** (più le copie in `backups/`) |
| `prod/inbox/` | file inviati dagli utenti in attesa di moderazione. Approvati → spostati in `archive/`; rifiutati → cancellati dopo 30 giorni | il bot | sì |
| `prod/trash/` | file eliminati con 🗑 da ⚙️ Gestisci, in `trash/<data>/`. Cancellati dopo 30 giorni | il bot | sì |
| `prod/media/` | `welcome.mp4` (o `welcome.gif`), l'animazione di `/start`, caricata su Telegram all'avvio del bot. Altri file qui vengono ignorati. Il default è in [`assets/`](../assets/README.md) | chi installa | sì |
| `prod/backups/` | copie notturne del database, le ultime 14 | il bot | sì |
| `bot-api/` | cartella di lavoro del server Bot API locale (vedi sotto) | il server Bot API | **no** |

### 1.2 `data/bot-api/`: la cartella del server Bot API

Il bot non parla con i server di Telegram direttamente, ma tramite il server
Bot API locale (container `telegram-bot-api`), che permette file fino a 2 GB.
`data/bot-api/` è la sua cartella di lavoro; il bot non ci scrive niente.

**Cosa contiene:**

- una sottocartella per ogni bot (prod e beta) con la **sessione** del bot verso
  Telegram (database interno del server);
- dentro, `documents/`, `photos/`, … con i file **scaricati** dal server quando
  il bot chiede un file a Telegram. Per UniVrArchive sono i documenti che gli
  utenti inviano al bot.

**Il percorso di un file inviato da un utente:**

1. l'utente manda un PDF al bot;
2. il server Bot API lo scarica in `data/bot-api/<bot>/documents/`;
3. il bot lo legge da lì (sola lettura), ne calcola l'impronta (sha256) e lo
   **copia** in `data/prod/inbox/`;
4. dopo 24 ore `bot-api-cleaner` cancella la copia in `bot-api/`: quella che
   conta è in `inbox/`.

I file che il bot carica nel canale storage non passano da questa cartella.

**Da sapere:**

- **Proprietario: utente 101.** Al primo avvio il server diventa proprietario
  della cartella: è normale, non cambiarlo. Per questo il bot la monta in sola
  lettura e la pulizia la fa un container separato (`bot-api-cleaner`) con lo
  stesso utente del server.
- **Dati sensibili.** Contiene la sessione dei bot: trattala come il token.
  Non va su git (è ignorata) e non serve nel backup.
- **Si può perdere senza danni.** Se viene cancellata, il server la ricrea al
  prossimo avvio. I file utili sono già in `inbox/` o nell'archivio.

---

## 2. Prima installazione

```bash
git clone https://github.com/kodikasgroup/UnivrArchive.git && cd UnivrArchive
cp .env.example .env            # compilare: ogni variabile è commentata
```

Materiale e media:

```bash
rsync -a /percorso/materiale/ data/prod/archive/   # -a conserva le date dei file
cp assets/welcome.mp4 data/prod/media/            # animazione di /start (opzionale)
```

**Solo con il server locale** (`COMPOSE_PROFILES=local-api`), una volta per ogni
token, prima del primo avvio: scollegare il bot dal server di Telegram,
altrimenti il server locale non riceve gli update. Con il server di Telegram
**non va fatto**.

```bash
curl "https://api.telegram.org/bot<TOKEN>/logOut"
```

Dopo `logOut`, per 10 minuti Telegram non accetta quel token sul server cloud:
se c'è ancora un vecchio bot che lo usa, va fermato prima.

Avvio:

```bash
docker compose up -d --build
docker compose logs -f bot
```

Se manca una variabile obbligatoria, `docker compose` si ferma subito dicendo
quale. Poi, da Telegram, un admin manda **`/reindex`** al bot e preme
**✅ Applica**. Al primo indice il bot calcola l'hash di tutto l'archivio
(qualche minuto) e poi carica i file nel canale storage in background
(circa 1,5–2 ore per 7 GB): nel frattempo funziona normalmente.

---

## 3. Bot di test (beta)

Token, canali e dati separati da produzione (`BETA_*` nel `.env`, cartella
`data/beta/`):

```bash
rsync -a data/prod/archive/ data/beta/archive/     # opzionale: archivio vero per le prove
# solo con il server locale: curl "https://api.telegram.org/bot<TOKEN_BETA>/logOut"
docker compose --profile beta up -d --build
docker compose logs -f bot-beta
```

---

## 4. Aggiornare

```bash
git pull
docker compose up -d --build
```

Il database si aggiorna da solo all'avvio (migrazioni automatiche). Conviene
provare prima sul beta.

**Senza compilare sul Pi:** a ogni tag `v*` GitHub Actions pubblica l'immagine
(arm64 e amd64) su `ghcr.io/kodikasgroup/univrarchive:<versione>`. Nel
`compose.yaml` si sostituisce `build: .` con `image:` e quella versione, poi
`docker compose pull && docker compose up -d`.

---

## 5. Backup

**Database — automatico.** Ogni notte (03:00 UTC) il bot salva una copia in
`data/prod/backups/bot-AAAA-MM-GG.db` e tiene le ultime 14. Nello stesso giro
svuota il cestino e l'inbox dei file scaduti (30 giorni) e cancella i download
più vecchi di 12 mesi. Se il bot era spento a quell'ora, lo fa all'avvio.

**Archivio e backup — da configurare sull'host** (il bot non conosce dischi
esterni): un `rsync` notturno di tutta `data/` su un altro disco o NAS.

```bash
# crontab -e  (alle 05:00 ora locale)
0 5 * * * rsync -a --delete --exclude 'bot-api/' /percorso/UnivrArchive/data/ /mnt/backup/univrarchive/
```

`bot-api/` è esclusa: contiene la sessione dei bot (dato sensibile) e il server
la ricrea da solo ([§1.2](#12-databot-api-la-cartella-del-server-bot-api)).

Il canale storage su Telegram contiene una copia di ogni file, ma **non**
sostituisce questo backup: il materiale segnalato per copyright può sparire.

---

## 6. Ripristinare il database

```bash
docker compose stop bot
cp data/prod/backups/bot-AAAA-MM-GG.db data/prod/bot.db
rm -f data/prod/bot.db-wal data/prod/bot.db-shm
docker compose start bot
```

Poi un admin lancia `/reindex`: l'albero si riallinea all'archivio su disco,
che resta sempre la fonte di verità. Crediti, acquisti e invii successivi al
backup vanno sistemati a mano (`/crediti_add`).

---

## 7. Passaggio dalla v1

La v1 (python-telegram-bot 13) è conservata nel tag git `v1`. Il passaggio usa
lo **stesso token** del vecchio bot, così gli utenti non devono fare nulla.

**Prima, sul beta:** migrare una copia del vecchio database e provare tutto.

```bash
cp /percorso/vecchio/db/UserLogDB.db /tmp/old.db
docker compose run --rm -v /tmp/old.db:/old.db:ro bot-beta \
    python -m scripts.migrate_old_db /old.db /data/bot.db --dry-run   # solo riepilogo
docker compose run --rm -v /tmp/old.db:/old.db:ro bot-beta \
    python -m scripts.migrate_old_db /old.db /data/bot.db
```

Lo script apre il vecchio DB in sola lettura, porta utenti, crediti, VIP
(diventano permanenti) e conteggio download, recupera gli utenti presenti solo
nelle tabelle crediti/download, e si può rilanciare senza duplicare nulla.

**Il giorno del passaggio:**

1. Avvisare gli utenti con il vecchio bot ("manutenzione di 30 minuti").
2. Fermare il vecchio bot.
3. Copia **finale** del vecchio DB e migrazione verso `data/prod/bot.db`.
4. Solo con il server locale: `logOut` del token (§2). Da qui il vecchio bot non
   può ripartire per 10 minuti.
5. `docker compose up -d`, poi `/reindex` → ✅ Applica.
6. Prova veloce: navigazione, un download, un acquisto, un invio.

**Tornare indietro:** fermare il nuovo bot, aspettare i 10 minuti dal `logOut`,
riavviare il vecchio con il suo database (non è stato toccato). Quello che è
successo nel frattempo sul nuovo bot va riportato a mano.

---

## 8. Problemi comuni

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| `required variable … is missing` all'avvio | `.env` incompleto | compilare la variabile indicata |
| Il bot non risponde, nessun errore | manca `logOut` del token, o un altro processo usa lo stesso token | `logOut` (§2), fermare l'altro processo |
| "Configurazione incompleta, mancano: …" nei log | variabile vuota (spesso il beta senza `BETA_*`) | compilare o non avviare il beta |
| File con 📦, "troppo grande" | si usa il server di Telegram (limite 50 MB) | attivare il server locale (§1): `COMPOSE_PROFILES=local-api` + chiavi API, `logOut`, riavvio, `/reindex` |
| File sopra 50 MB non partono con il server locale attivo | server Bot API locale non raggiungibile | `docker compose ps`, `docker compose logs telegram-bot-api` |
| Si torna dal server locale a quello di Telegram | il token è "agganciato" al server locale | togliere `local-api` da `COMPOSE_PROFILES`, `logOut` del token **sul server locale** prima di fermarlo, attendere 10 minuti, riavviare |
| Errori ripetuti | — | arrivano in `LOG_CHAT_ID` se impostato, sempre in `docker compose logs bot` |
| `data/bot-api/` appartiene all'utente 101 | è il server Bot API | normale, non cambiarlo |
