# UniVrArchive

Bot Telegram che distribuisce il materiale di studio dell'Università di Verona,
organizzato per corso, anno e materia.

> **Versione 2** (aiogram 3.31, Python 3.14). La v1 (python-telegram-bot 13)
> è conservata nel tag git `v1`.

## Cosa fa

- **Naviga l'archivio** con i bottoni: corso → anno → materia → file, con
  percorso visibile e pagine da 10.
- **Invia i file all'istante**: ogni file viene caricato su Telegram una sola
  volta, poi parte dal suo `file_id`. File fino a 2 GB.
- **Cerca** ovunque: `@bot analisi` in qualsiasi chat, `/cerca`, link diretti a
  cartelle e file.
- **Preferiti, recenti, novità** (🆕 sui file aggiunti negli ultimi 7 giorni).
- **Exclusive:** materiale che si sblocca con i crediti. I crediti si
  guadagnano **inviando materiale** che lo staff approva. Nessun pagamento.
- **Gruppi dei corsi:** `/materiale` mostra il menu solo a chi lo chiede.
- **Tutto gestibile da Telegram per lo staff:** moderazione, riorganizzazione
  dell'archivio, pubblicazione con anteprima, ticket, broadcast.

## Avvio rapido

Requisiti: Docker con Compose v5, un bot da @BotFather, due chat Telegram
(canale storage e gruppo staff), `api_id`/`api_hash` da my.telegram.org.
Tutti i passaggi in [`docs/REQUISITI.md`](docs/REQUISITI.md).

```bash
git clone https://github.com/kodikasgroup/UnivrArchive.git && cd UnivrArchive
cp .env.example .env                  # compilare: token, admin, chat, api_id/hash
rsync -a /percorso/materiale/ data/prod/archive/   # -a conserva le date
cp /percorso/welcome.mp4 data/prod/media/          # opzionale: animazione di /start
docker compose up -d --build
docker compose logs -f bot
```

Poi, da Telegram, un admin manda `/reindex` al bot e preme **✅ Applica**.

Bot di test (dati e canali separati, in `data/beta/`):

```bash
docker compose --profile beta up -d --build
```

## Struttura

```
bot/                codice del bot
├── handlers/       un modulo per area: browse, files, groups, submit, manage, tickets, admin
├── db/             tutto l'SQL, un modulo per area
└── texts/          tutti i testi mostrati agli utenti
tests/              test (python -m unittest)
scripts/            migrazione una tantum dal database della v1
docs/               documentazione
data/               dati locali — solo la struttura è su git
├── prod/           archive/ inbox/ trash/ media/ backups/ + bot.db
├── beta/           stessa struttura, per il bot di test
└── bot-api/        file del server Bot API locale
Dockerfile, compose.yaml, .env.example, requirements.txt
```

Ogni cartella di `data/` contiene un `.gitignore` che ignora tutto tranne sé
stesso: chi clona trova le cartelle pronte, ma nessun dato può finire su git.
I segreti stanno solo in `.env` (ignorato).

## Documentazione

| Documento | Per chi | Contenuto |
|---|---|---|
| [`docs/REQUISITI.md`](docs/REQUISITI.md) | chi installa | bot, canali, credenziali, hardware da preparare |
| [`docs/GUIDA_ADMIN.md`](docs/GUIDA_ADMIN.md) | staff | comandi, moderazione, reindex, prezzi, ticket |
| [`docs/FLUSSI.md`](docs/FLUSSI.md) | tutti | come funziona, con diagrammi |
| [`docs/ARCHITETTURA.md`](docs/ARCHITETTURA.md) | sviluppatori | scelte tecniche, schema DB, deploy, migrazione |
| [`docs/FUTURO_MINI_APP.md`](docs/FUTURO_MINI_APP.md) | — | idea rimandata dopo la v1 |

## Sviluppo

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest
```

Regole: tutto l'SQL in `bot/db/`, tutti i testi in `bot/texts/`, una sola
dipendenza diretta (`aiogram`), versioni fissate (tabella in
[`ARCHITETTURA.md` §4.1](docs/ARCHITETTURA.md#41-versioni-tutte-le-più-recenti-verificate-il-6-novembre-2026)).

## Privacy e materiale

Il bot salva solo quello che serve (ID Telegram, nome, crediti, acquisti,
download per 12 mesi): dettagli con `/privacy`. Chi detiene i diritti su un
materiale può chiederne la rimozione con `/rimozione`.

## Licenza

[GPL-3.0](LICENSE).
