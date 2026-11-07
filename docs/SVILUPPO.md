# Sviluppo

Per chi vuole modificare il codice del bot.

## Ambiente

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest            # tutti i test, senza rete
```

Per provarlo davvero si usa il **bot beta** con Docker
([`INSTALLAZIONE.md` §3](INSTALLAZIONE.md#3-bot-di-test-beta)): token, canali e
dati separati da produzione.

## Struttura del codice

```
bot/
├── __main__.py      avvio: config, DB, albero, router, job notturno, polling
├── config.py        variabili d'ambiente → Settings (errore chiaro se ne manca una)
├── middlewares.py   registra l'utente su ogni update
├── filters.py       IsAdmin, IsPrivate
├── archive.py       scansione dell'archivio, /reindex, albero in memoria
├── storage.py       canale storage: caricamento unico, invio da file_id
├── keyboards.py     tastiere di navigazione (browse, scelta cartella, staff, gruppi)
├── jobs.py          task notturno
├── db/              TUTTO l'SQL: __init__ (schema, utenti, crediti), nodes, content, inbox, stats
├── texts/           TUTTI i testi: common, browse, inbox, admin
└── handlers/        un router per area
    ├── browse.py    /start, navigazione, ricerca, inline, deep link, preferiti, recenti, novità
    ├── files.py     invio file, acquisto, scarica tutto, segnala
    ├── groups.py    /collega, /scollega, /materiale
    ├── submit.py    invii degli utenti e moderazione
    ├── manage.py    ⚙️ Gestisci (operazioni sull'archivio)
    ├── tickets.py   /feedback, /rimozione, risposte dello staff
    └── admin.py     /reindex, /stats, /crediti_add, /vip, /broadcast, /pending
scripts/migrate_old_db.py   migrazione una tantum dal DB della v1
tests/                      un file per area
```

Ogni modulo in `bot/handlers/` espone `router`, `COMMANDS` e `ADMIN_COMMANDS`;
`__main__.py` li registra e imposta da solo il menu comandi.

## Regole

- **Una sola dipendenza diretta:** `aiogram`. Niente librerie per cose che la
  stdlib fa già (config con `os.environ`, DB con `sqlite3`, test con `unittest`).
- **SQL solo in `bot/db/`**, sempre con parametri `?`. Le scritture avvengono dal
  thread dell'event loop, senza `await` dentro una transazione.
- **Testi solo in `bot/texts/`**, in HTML (`html.escape` sui nomi di file).
- **Funzioni di modulo**, niente classi con soli metodi statici.
- **Ogni callback** risponde sempre (`answer()`) e ricontrolla tutto lato server:
  admin, saldo, prezzo attuale, nodo esistente.
- **Bottoni:** un solo tipo per bottone. Un bottone `disabled` non ha
  `callback_data`.
- **Mai `forward`** dal canale storage e mai la sua didascalia verso gli utenti.
- **Ogni bug corretto** lascia un test che fallirebbe senza la correzione.
- Modifiche allo schema: una nuova voce in fondo a `MIGRATIONS` in
  `bot/db/__init__.py` (versione in `PRAGMA user_version`), mai modificare le
  precedenti.

## Versioni

Tutte fissate, nel file dove si usano. Verificate il 6 novembre 2026.

| Cosa | Versione | Dove |
|---|---|---|
| Python | 3.14.10 (`python:3.14.10-slim-trixie`) | `Dockerfile` |
| aiogram | 3.31.0 (Bot API 10.3) | `requirements.txt` |
| Server Bot API | `aiogram/telegram-bot-api:10.3` | `compose.yaml` |
| Alpine (pulizia bot-api) | 3.24.4 | `compose.yaml` |
| GitHub Actions | `checkout@v7`, `setup-qemu@v4`, `setup-buildx@v4`, `login@v4`, `metadata@v6`, `build-push@v7` | `.github/workflows/docker.yml` |
| gitleaks (pre-commit) | v8.30.1 | `.pre-commit-config.yaml` |

Python 3.15 è uscito, ma aiogram 3.31 dichiara `requires_python <3.15`: si passa
quando aiogram lo supporta.

**Aggiornare:** Dependabot apre le PR ogni mese (`pip`, `docker`,
`github-actions`). aiogram e l'immagine `telegram-bot-api` vanno aggiornati
**insieme** (stessa versione di Bot API) e provati sul beta.

## Rilasciare

1. Test verdi, prova sul beta.
2. Tag `vX.Y.Z` e push del tag: GitHub Actions pubblica l'immagine multi-arch su
   `ghcr.io/kodikasgroup/univrarchive`.
3. Sul server: [`INSTALLAZIONE.md` §4](INSTALLAZIONE.md#4-aggiornare).
