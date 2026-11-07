# Installazione e gestione del server

Come installare, avviare, aggiornare e fare il backup di UniVrArchive su un
Raspberry Pi (o qualsiasi macchina con Docker). Prima di iniziare: tutto quello
che va preparato su Telegram è in [`REQUISITI.md`](REQUISITI.md).

---

## 1. Cosa gira

| Container | Cosa fa |
|---|---|
| `bot` | il bot (Python 3.14, aiogram 3.31) |
| `telegram-bot-api` | server Bot API locale: file fino a 2 GB (il server cloud si ferma a 50 MB) |
| `bot-api-cleaner` | cancella dopo 24 ore i file scaricati dal server Bot API |
| `bot-beta` | bot di test, solo con `--profile beta` |

Tutti i dati stanno nella cartella del progetto:

```
data/
├── prod/          archive/ inbox/ trash/ media/ backups/  bot.db
├── beta/          stessa struttura, per il bot di test
└── bot-api/       file del server Bot API (proprietario: utente 101, è normale)
```

Le cartelle esistono già nel repo, vuote. Il loro contenuto non va mai su git.
La configurazione sta solo in `.env`.

---

## 2. Prima installazione

```bash
git clone https://github.com/kodikasgroup/UnivrArchive.git && cd UnivrArchive
cp .env.example .env            # compilare: ogni variabile è commentata
```

Materiale e media:

```bash
rsync -a /percorso/materiale/ data/prod/archive/   # -a conserva le date dei file
cp /percorso/welcome.mp4 data/prod/media/          # opzionale: animazione di /start
```

**Una sola volta per ogni token**, prima del primo avvio: scollegare il bot dal
server cloud di Telegram, altrimenti il server locale non riceve gli update.

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
curl "https://api.telegram.org/bot<TOKEN_BETA>/logOut"
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
0 5 * * * rsync -a --delete /percorso/UnivrArchive/data/ /mnt/backup/univrarchive/
```

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
4. `logOut` del token (§2). Da qui il vecchio bot non può ripartire per 10 minuti.
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
| File sopra 50 MB non partono | server Bot API locale non raggiungibile | `docker compose ps`, `docker compose logs telegram-bot-api` |
| Errori ripetuti | — | arrivano in `LOG_CHAT_ID` se impostato, sempre in `docker compose logs bot` |
| `data/bot-api/` appartiene all'utente 101 | è il server Bot API | normale, non cambiarlo |
