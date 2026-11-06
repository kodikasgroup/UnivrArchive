# UniVrArchive — Analisi e architettura per la riscrittura

> Documento tecnico: cosa fa oggi il bot e come lo rifarei da zero
> per essere veloce, leggero su un Raspberry Pi, facile da configurare e sicuro
> come progetto open source.

---

## Indice

1. [Cosa fa oggi il bot](#1-cosa-fa-oggi-il-bot)
2. [Come lo fa: flusso attuale](#2-come-lo-fa-flusso-attuale)
3. [Principi della nuova architettura](#3-principi-della-nuova-architettura)
4. [Stack tecnologico](#4-stack-tecnologico)
5. [Struttura del progetto](#5-struttura-del-progetto)
6. [L'archivio: dove sta, come si indicizza, come si naviga](#6-larchivio)
7. [Cache lato Telegram: file_id e trucchi](#7-cache-lato-telegram)
8. [Database: schema e meno scritture](#8-database)
9. [Navigazione, funzioni sui file e UX](#9-navigazione-funzioni-sui-file-e-ux)
10. [Crediti, Exclusive, VIP, donazioni](#10-crediti-exclusive-vip-donazioni)
11. [Invio materiale dagli utenti (moderazione)](#11-invio-materiale-dagli-utenti)
12. [Amministrazione e broadcast](#12-amministrazione-e-broadcast)
13. [Configurazione e segreti (open source senza leak)](#13-configurazione-e-segreti)
14. [Deploy: Docker o Raspberry diretto](#14-deploy)
15. [Logging, backup, monitoraggio](#15-logging-backup-monitoraggio)
16. [Limiti della Bot API da ricordare](#16-limiti-della-bot-api)
17. [Piano di migrazione passo per passo](#17-piano-di-migrazione)
18. [Checklist finale](#18-checklist-finale)

---

## 1. Cosa fa oggi il bot

UniVrArchive è un bot Telegram che distribuisce materiale di studio
dell'Università di Verona organizzato in cartelle.

| Funzione | Comando / azione | Dove nel codice |
|---|---|---|
| Benvenuto + menu corsi | `/start` | `Handlers.start_handler` |
| Navigazione corso → anno → materia → sezione → file | bottoni inline | `Utils.send_buttons`, `MainButtonsGenerator` |
| Sezione EXCLUSIVE a pagamento in crediti | bottone `✴EXCLUSIVE✴` | `ExclusiveButtonHandler`, `ExclusiveButtonGenerator` |
| Saldo crediti | `/credits` | `Handlers.credits_handler` |
| Feedback verso un canale staff | `/feedback testo` | `Handlers.feedback_handler` |
| Invio materiale da parte degli utenti | mandare un documento al bot | `Handlers.material_receiver_handler` |
| Info Exclusive / donazioni | `/exclusive`, `/donation`, `/info` | `Handlers` |
| Admin: login, statistiche, crediti, VIP, messaggi, rimozione utenti | `/root`, `/stats`, `/givecredits`, `/givevip`, `/sendmessage`, `/remove` | `Handlers` |

**Sorgente dei file:** la cartella locale `archive/` (in `.gitignore`), con
struttura tipica `archive/<Corso>/<Anno>/<Materia>/<Sezione>/<file>` ma
profondità variabile (vedi §6.2). La sezione Exclusive è la cartella
`archive/EXCLUSIVE/...`, dove il prezzo in crediti è il numero iniziale del
nome file (`5.nome.pdf`).

**Persistenza:** SQLite `db/UserLogDB.db` con tre tabelle senza chiavi:
`User(chat_id, f_name, username, state)`, `Reserved(chat_id, Vip, Credit)`,
`Download(chat_id, n_download)`.

**Libreria:** `python-telegram-bot` v13 (API sincrona, `Updater`, `use_context=True`).

---

## 2. Come lo fa: flusso attuale

### 2.1 Click su un bottone

```
utente clicca
  └─ inline_button_handler
       ├─ string matching su callback_data ('HOME', 'BACK', 'EXCLUSIVE', '__file', '__course'...)
       ├─ HashHandler.get_corresponding_text(md5)   ← dizionario in RAM
       ├─ os.listdir(archive/...)                    ← disco a ogni click
       ├─ crea N nuovi md5 e li salva nel dizionario
       ├─ delete_message(messaggio vecchio)          ← 1 chiamata API
       └─ send_message(nuovo menu)                   ← 1 chiamata API
```

Il percorso viene trasformato in MD5 perché `callback_data` ha un limite di
64 byte. La mappa `md5 → percorso` vive solo in RAM.

### 2.2 Download di un file

```
Utils.send_file
  ├─ FileHandler.files[path]   ← cache file_id in RAM
  ├─ se assente: open(path) e upload (se > 7 MB avvisa "10-30 secondi")
  ├─ salva file_id in RAM
  ├─ UPDATE Download ...       ← scrittura DB
  └─ UPDATE User SET state ... ← scrittura DB
```

L'idea di riusare il `file_id` è giusta, ma la cache si perde a ogni riavvio.

---

## 3. Principi della nuova architettura

1. **Il disco si legge solo su comando.** L'archivio viene indicizzato solo con
   `/reindex`; all'avvio l'albero si carica dal DB (§6.3). I click non toccano
   mai il filesystem.
2. **Ogni file si carica su Telegram una sola volta nella vita.** Il `file_id`
   viene salvato su DB e sopravvive ai riavvii.
3. **Un click = una chiamata API** (`edit_message_text`) + `answer_callback_query`.
4. **ID stabili e corti nei bottoni** (`n:142`), persistiti su DB: i bottoni
   vecchi funzionano anche dopo un riavvio o un aggiornamento.
5. **Scritture minime:** nessuna scrittura nei percorsi di sola lettura
   (navigazione); contatori aggregati; `last_seen` aggiornato al massimo una
   volta l'ora.
6. **Un solo modello di dati:** la cartella `EXCLUSIVE` resta dov'è, ma nel
   codice è un ramo dell'albero come gli altri; i suoi file hanno solo un
   attributo `price` in più. Stesso codice di navigazione per tutto.
7. **L'archivio esistente si usa così com'è:** nessun file da rinominare o
   spostare (vedi §6.2).
8. **Codice e dati separati:** il repo contiene solo codice. Lo stato (DB,
   archivio, file in attesa, backup) vive in `data/`; i segreti in `.env` nella
   radice del progetto. Entrambi ignorati da git.
9. **Async ovunque:** un upload lento non blocca gli altri utenti.

---

## 4. Stack tecnologico

| Componente | Scelta | Perché |
|---|---|---|
| Python | **3.14.10** | l'ultima che aiogram 3.31 supporta (`requires_python <3.15`). La 3.15.2 è uscita, ma oggi aiogram non la dichiara compatibile: si passa alla 3.15 quando lo farà |
| Libreria bot | **aiogram 3.31** | supporta già la **Bot API 10.3** (agosto 2026): bottoni colorati e disabilitati, messaggi effimeri, rich messages (§9). Async nativo, router, filtri, middleware. Aggiorna l'API in pochi giorni dal rilascio di Telegram |
| Alternativa | python-telegram-bot 22.8 | il team la conosce già, ma a oggi si ferma alla Bot API 10.0: niente rich messages, messaggi effimeri, bottoni disabilitati. Dato che si riscrive comunque tutto, non conviene restarci |
| DB | SQLite (modulo `sqlite3` della stdlib) in modalità WAL | zero servizi da gestire, perfetto su Raspberry, query in microsecondi |
| Config | variabili d'ambiente + `.env` (lettura con `os.environ`) | niente librerie in più; Docker passa `.env` nativamente |
| Deploy | Docker Compose (consigliato) oppure systemd | vedi §14 |

### 4.1 Versioni (tutte le più recenti, verificate il 6 novembre 2026)

Ogni versione è **fissata** e scritta nel file dove si usa: niente `latest`,
niente versioni implicite. Fonti: PyPI, Docker Hub, GitHub Releases.

| Cosa | Versione | Dove si scrive | Note |
|---|---|---|---|
| Python | `3.14.10` | `Dockerfile` (`FROM`) | 3.15.2 esiste ma aiogram richiede `<3.15` |
| Immagine base | `python:3.14.10-slim-trixie` | `Dockerfile` | Debian 13 "trixie", multi-arch (arm64 per il Pi) |
| aiogram | `3.31.0` (25/08/2026) | `requirements.txt` | supporto completo **Bot API 10.3** |
| Server Bot API locale | `aiogram/telegram-bot-api:10.3` | `compose.yaml` | stessa versione di Bot API della libreria; multi-arch |
| Docker Compose | v5 (spec senza campo `version:`) | — | il compose è validato con v5.1.1 |
| `actions/checkout` | `v7` (7.0.1) | `.github/workflows/docker.yml` | |
| `docker/setup-qemu-action` | `v4` (4.4.0) | workflow | build arm64 su runner amd64 |
| `docker/setup-buildx-action` | `v4` (4.4.1) | workflow | |
| `docker/login-action` | `v4` (4.8.0) | workflow | login a GHCR |
| `docker/metadata-action` | `v6` (6.2.0) | workflow | tag immagine da git |
| `docker/build-push-action` | `v7` (7.4.0) | workflow | `platforms: linux/arm64,linux/amd64` |
| pre-commit | `4.7.0` | `.pre-commit-config.yaml` | opzionale |
| gitleaks | `v8.30.1` | `.pre-commit-config.yaml` | opzionale, blocca commit con token |
| Raspberry Pi OS | 64 bit, base Debian 13 "trixie" | — | stessa base Debian dell'immagine Docker |

Scartata: **python-telegram-bot 22.8** (ultima versione) supporta solo fino alla
Bot API 10.0 (vedi tabella sopra).

`requirements.txt` (unico file di dipendenze, niente `pyproject.toml`: il bot
non è una libreria da pubblicare):

```text
aiogram==3.31.0
```

Una sola dipendenza diretta. `python-decouple` e `pympler` del vecchio bot non
servono più. Le dipendenze indirette (aiohttp, pydantic, …) le sceglie pip
secondo i vincoli di aiogram. Per avere build identiche al byte, opzionale:
generare un `requirements.lock` con `pip freeze` dal container e installare da
quello.

**Regola di aggiornamento:** una volta al mese (o quando Telegram rilascia una
Bot API nuova) si controllano le versioni di questa tabella, si aggiornano
**insieme** aiogram e `aiogram/telegram-bot-api` (stessa versione di Bot API),
si prova sul bot beta e poi si porta in produzione. Dependabot su GitHub può
aprire le PR da solo (`pip`, `docker`, `github-actions`).

> Perché `sqlite3` sincrono e non `aiosqlite`: le query sono su file locale e
> impiegano microsecondi; il collo di bottiglia è la rete verso Telegram, non il
> DB. Se un giorno servirà, si passa ad `aiosqlite` cambiando un solo modulo.

---

## 5. Struttura del progetto

```
UnivrArchive/
├── bot/
│   ├── __main__.py      # crea Bot e Dispatcher, registra i router, avvia polling e job
│   ├── config.py        # legge le env var, valida, espone Settings
│   ├── middlewares.py   # registrazione utente su ogni update, last_seen
│   ├── filters.py       # IsAdmin, chat privata, gruppo collegato
│   ├── archive.py       # scansione, diff, spostamenti, albero in RAM, reindex
│   ├── storage.py       # canale storage: ensure_uploaded, upload in background, invio file
│   ├── keyboards.py     # tastiere: cartelle (più modalità), paginazione, breadcrumb
│   ├── jobs.py          # task notturno (backup, pulizie, rebuild albero)
│   ├── db/              # UNICO punto con SQL, un modulo per area
│   │   ├── __init__.py  #   connessione, PRAGMA, schema, migrazioni, users, crediti, kv
│   │   ├── nodes.py     #   nodes, blobs
│   │   ├── content.py   #   purchases, favorites, downloads, group_folders
│   │   ├── inbox.py     #   submissions, tickets
│   │   └── stats.py     #   query aggregate per /stats e task notturno
│   ├── texts/           # tutti i testi, un modulo per area
│   │   ├── common.py    #   errori, help, privacy, start
│   │   ├── browse.py    #   navigazione, file, acquisto, gruppi
│   │   ├── inbox.py     #   invii, moderazione, ticket, gestione archivio
│   │   └── admin.py     #   comandi admin, reindex, broadcast
│   └── handlers/        # ognuno espone `router`
│       ├── browse.py    # /start, /help, /privacy, /crediti, navigazione, ricerca, inline, deep link, preferiti, recenti, novità
│       ├── files.py     # invio file, acquisto, scarica tutto, segnala
│       ├── groups.py    # /collega, /scollega, /materiale effimero
│       ├── submit.py    # ricezione materiale + moderazione
│       ├── manage.py    # ⚙️ Gestisci (operazioni su disco)
│       ├── tickets.py   # /feedback, /rimozione, reply dello staff, chiusura
│       └── admin.py     # /stats, /crediti_add, /vip, /broadcast, /reindex, /pending
├── scripts/
│   └── migrate_old_db.py   # migrazione una tantum dal vecchio UserLogDB.db
├── tests/               # un file per area, eseguibili con `python -m unittest`
├── data/                # ⚠ IGNORATA da git — dettaglio in §13.2
│   ├── prod/            #    archive/, inbox/, trash/, media/, backups/, bot.db
│   ├── beta/            #    stessa struttura, opzionale
│   └── bot-api/         #    server Bot API locale
├── .env.example         # template di configurazione, versionato
├── Dockerfile
├── compose.yaml
├── requirements.txt     # aiogram==3.31.0, unica dipendenza (§4.1)
├── .github/workflows/docker.yml   # build multi-arch → GHCR (§14.2)
└── README.md            # come configurare e avviare in 5 minuti
```

Regole:

- **Niente classi con soli `@staticmethod`**: funzioni di modulo. Più corte,
  più leggibili, nessun singleton artificiale.
- **Tutto l'SQL in `bot/db/`**, sempre con parametri `?`.
- **Tutti i testi in `bot/texts/`**: niente stringhe sparse negli handler.
- **Test con `unittest` della stdlib** (`python -m unittest`): nessuna
  dipendenza in più (niente pytest).
- Interfacce tra moduli: ogni modulo documenta le sue funzioni pubbliche nei
  docstring; ogni file in `bot/handlers/` espone `router`, `COMMANDS`,
  `ADMIN_COMMANDS`.
- `.idea/` fuori dal repo (aggiungerla al `.gitignore`).

---

## 6. L'archivio

### 6.1 Dove tenerlo

L'archivio **non va mai nel repository** (diritti d'autore sul materiale,
dimensioni, privacy).

**Scelta: disco + canale Telegram di archivio.**

| Dove | Cosa contiene | A cosa serve |
|---|---|---|
| **Cartella su disco** `data/prod/archive/` (dentro il progetto, su SSD) | i file originali, organizzati in cartelle | **struttura**: è il posto dove lo staff aggiunge, sposta e rinomina; `/reindex` legge da qui |
| **Canale privato di archivio** (`STORAGE_CHAT_ID`) | una copia di ogni file, caricata **una sola volta** | **consegna**: gli utenti ricevono i file da Telegram, all'istante; ed è un backup permanente gratuito |

Il disco decide **cosa** si vede e **dove**; il canale decide **da dove arriva**
il file. Gli utenti non vedono mai il canale: è un deposito privato dove sono
membri solo il bot e lo staff. Dettagli in §7.3.

Alternativa scartata: usare **solo** il canale, senza disco. Si risparmiano i
7,4 GB sul Raspberry, ma la struttura a cartelle andrebbe gestita a mano dentro
il bot invece che con un normale file manager.

L'archivio attuale pesa **7,4 GB**: sul Raspberry serve un disco dedicato.
Tenere `data/` su **SSD USB**, non sulla microSD (più veloce e
non si usura).

Percorso: sempre `data/<bot>/archive/` dentro il progetto (in container
`/data/archive`, fisso). Nessuna variabile da configurare (§13.2).

### 6.2 Struttura delle cartelle: 1:1 con l'archivio attuale

L'archivio di oggi **si copia in `data/prod/archive/` così com'è**: niente da
rinominare, niente da spostare. Il nuovo bot non fa ipotesi sul numero di
livelli: ogni cartella è un nodo, ogni file è una foglia, a qualsiasi profondità.

**Com'è fatto l'archivio reale** (analizzato: 11 corsi, ~1.600 file, 7,4 GB):

```
archive/
├── INFORMATICA/                      ← corso (livello 1)
│   ├── 1°_Anno/                      ← anno (livello 2)
│   │   ├── ALGORITMI/                ← materia (livello 3)
│   │   │   ├── Esami/                ← sezione (livello 4)
│   │   │   │   └── esame_2021.pdf    ← file (livello 5)
│   │   │   └── ...                   ← a volte altri sottolivelli (fino a 9)
├── TOLC/
│   └── Il Test CISIA ... .pdf        ← file già al livello 1
├── INGLESE/ESERCIZI/10 facts.doc     ← file al livello 2
└── EXCLUSIVE/
    └── 3°_Anno/Fondamenti/Riassunti/
        ├── 5.(E)manuale fondamenti(soppravivenza).pdf   ← 5 crediti
        └── 10.(E)BIBBIA_FONDAMENTI.pdf                  ← 10 crediti
```

Quindi lo schema "corso/anno/materia/sezione" è solo **la forma più comune**:
alcuni corsi hanno meno livelli, alcune materie ne hanno di più, e ci sono file
anche nei livelli intermedi. Un albero generico gestisce tutti i casi senza codice
speciale. Il codice attuale di Exclusive invece ha 4 livelli fissi, quindi le
cartelle più profonde (es. `EXCLUSIVE/2°_Anno/Sistemi_Operativi/Lab/MentOS`)
vengono mostrate come se fossero file.

**Regole per restare 1:1 con quello che vede l'utente oggi:**

| Aspetto | Oggi | Nuovo bot |
|---|---|---|
| Menu iniziale | una riga per corso: `✏INFORMATICA✏`, `✴EXCLUSIVE✴` | identico |
| Nome visualizzato | `_` e `-` diventano spazi (`1°_Anno` → `1° Anno`) | identico, solo in visualizzazione: su disco i nomi non cambiano |
| Icona file | `📖nome📖` | identico (più ⭐ e prezzo per i file a pagamento) |
| Testo per livello | 1: `Hai scelto: 🗄X🗄` · 2: `Hai scelto: X📚📚📚` · 3: `⏰Scegli il Materiale⏰` · 4: `💥ECCO IL MATERIALE DELLA SEZIONE💥` · oltre: `Hai scelto: X` | identico, tabella `depth → testo` in `texts.py`. **Il ramo `EXCLUSIVE/` ha una tabella sua**, con i testi attuali di `ExclusiveButtonHandler` (ingresso "Eccoci nel area ⭐️Exclusive⭐…", poi quelli per anno/materia/file) |
| Colonne | 2 colonne al livello 2 (le materie), 1 altrove | identico |
| Indietro / Home | `<< BACK` + `🏠HOME` | identico; Indietro va al nodo padre |
| Cartella vuota | "Sembra non ci sia nulla qua" | identico (12 cartelle vuote nell'archivio reale) |
| Ordine | quello restituito da `os.listdir` (casuale, cambia tra macOS e Linux) | **naturale e stabile**: cartelle prima, poi file; `1°_Anno` < `2°_Anno` < `10°…` |
| File nascosti | `.DS_Store` appare come bottone | ignorati (`.*`, `Thumbs.db`) |

**Exclusive, 1:1:**

- Resta la cartella di primo livello `EXCLUSIVE`, con lo stesso bottone e lo
  stesso messaggio di ingresso ("Eccoci nel area ⭐️Exclusive⭐ ...").
- Un file ha un prezzo **solo se si trova sotto `EXCLUSIVE/`**. Fuori da lì
  un nome come `10 facts.doc` resta gratuito.
- Il prezzo è il **numero iniziale** del nome. Nell'archivio reale ci sono due
  formati e vanno accettati entrambi:
  - `5.(E)manuale fondamenti.pdf` → 5 crediti, nome mostrato `(E)manuale fondamenti.pdf`
  - `10ArchitetturaTemaEsame090718.pdf` (senza punto, 6 file) → 10 crediti.
    Il codice attuale fa `int(nome.split('.')[0])` e su questi file va in errore.
- **Prezzo non valido → file non pubblicato.** Un file sotto `EXCLUSIVE/` senza
  numero iniziale, oppure con prezzo oltre `PRICE_MAX` (default 50, oggi il
  massimo usato è 20), **non viene mostrato agli utenti** e compare come ⚠
  nell'anteprima del `/reindex` finché lo staff non lo rinomina. Motivo: la
  regola "numero iniziale = prezzo" legge qualsiasi numero (`2021_esame.pdf` →
  2021 crediti), e un file senza prezzo trattato come gratuito regalerebbe
  materiale a pagamento. Nascondere non vende per errore e non regala per errore.
  Il nodo **resta** in `nodes` con `hidden = 1` (stesso ID, acquisti conservati):
  quando lo staff corregge il nome torna visibile, e chi l'aveva comprato lo
  ritrova. Mentre è nascosto non lo vede nessuno, nemmeno chi l'ha comprato.
- **Stesso contenuto dentro e fuori `EXCLUSIVE/`** (stesso sha256): l'anteprima
  avvisa "⚠ contenuto Exclusive anche in cartella gratuita: …", altrimenti il
  file a pagamento sarebbe scaricabile gratis dall'altra cartella.
- Inviati con `protect_content=True`, come chiede il messaggio "non condividere".

**Cosa cambia solo in meglio, senza toccare l'archivio:** breadcrumb sopra il
menu (`📂 INFORMATICA › 2° Anno › ALGORITMI`), paginazione se una cartella ha
più di ~10 elementi, dimensione del file nel bottone.

### 6.3 Indicizzazione manuale

**Obiettivo:** lo staff aggiunge, rinomina o cancella file e cartelle in
`data/prod/archive/` con il metodo che preferisce (SFTP, Samba, `rsync`, sync MEGA,
chiavetta). Quando ha finito, un admin lancia **`/reindex`** e il bot si allinea
al disco, senza riavvii. Il disco è l'unica fonte di verità: dopo un `/reindex`,
quello che c'è nelle cartelle è esattamente quello che si vede nel bot.

**Sempre manuale, mai automatica.** Il bot non legge mai l'archivio da solo:
né a intervalli, né con watcher del filesystem. Così lo staff può riorganizzare
le cartelle con calma, anche in più passaggi, e gli utenti non vedono mai uno
stato intermedio. Il costo non è un problema: una scansione completa dell'archivio
reale (1.682 file) richiede **~10 ms** misurati, sul Raspberry meno di 100 ms.

**All'avvio** il bot carica l'albero dall'ultimo indice salvato su DB (tabella
`nodes`), **senza leggere il disco**. Un riavvio quindi non cambia mai cosa
vedono gli utenti. Al primissimo avvio l'indice è vuoto e il bot ricorda agli
admin di lanciare `/reindex`.

**`/reindex` in due passi, con anteprima:**

1. Il bot scansiona il disco e mostra all'admin le differenze **senza applicarle**:
   ```
   🗂 Anteprima reindex
   +12 file  (INFORMATICA/2° Anno/RETI: 9, TOLC: 3)
   ~1 modificato
   ↪ 5 spostati/rinominati (ID conservati)
   −3 rimossi
   ⚠ 1 file Exclusive senza prezzo (nascosto): EXCLUSIVE/.../EsameNuovo.pdf
   ⚠ 1 prezzo oltre 50 (nascosto): EXCLUSIVE/.../2021_esame.pdf → 2021
   ⚠ 2 file oltre 50 MB
   💰 1 prezzo cambiato: 10 → 5  EXCLUSIVE/.../TemaEsame.pdf
   [✅ Applica]  [❌ Annulla]
   ```
2. Solo con **✅ Applica** le modifiche diventano visibili agli utenti.

L'anteprima serve a evitare incidenti: se per errore sparisce una cartella
intera, l'admin vede "−300 rimossi" e annulla prima che succeda qualcosa.

**Cosa fa la scansione:**

1. `os.walk` sull'archivio, saltando file nascosti e temporanei
   (`.*`, `~$*`, `*.part`, `*.tmp`, `*.crdownload`, `Thumbs.db`).
2. **File ancora in copia → esclusi.** Un file con `mtime` più recente di 30
   secondi viene escluso e segnalato nell'anteprima ("⏳ 2 file ancora in copia,
   rilancia /reindex tra poco"). Così un PDF da 80 MB a metà upload non finisce
   mai nel bot troncato.
3. Confronto con l'indice attuale tramite `(path, size, mtime)`:
   - **se non è cambiato nulla**, l'anteprima dice "Nessuna modifica" e non si
     scrive niente su DB;
   - **file nuovo** → nuovo nodo con nuovo ID, `added_at = now`;
   - **file modificato** (stesso path, `size`/`mtime` diversi) → stesso ID, nuovo
     hash: dopo ✅ Applica si carica nel canale in background (§7.3);
   - **file sparito** → `removed = 1` (la riga resta, così statistiche e acquisti
     non si rompono);
   - **file spostato o rinominato** → un file "sparito" e un file "nuovo" con lo
     **stesso sha256** sono lo stesso file: si aggiorna `path`/`parent_id` della
     riga esistente e **l'ID resta lo stesso**. Deep link, preferiti, recenti e
     bottoni vecchi continuano a funzionare. Se ci sono più candidati con lo
     stesso hash (copie identiche), si abbina per nome file, poi per ordine.
   - **cartella spostata o rinominata** → si decide **dopo** i file, dal basso
     verso l'alto (prima le cartelle più profonde): una cartella "nuova" eredita
     l'ID della cartella "sparita" da cui proviene **la maggioranza** dei suoi
     figli già riconosciuti (file e sottocartelle). File nuovi aggiunti nella
     stessa operazione non impediscono il riconoscimento. Una cartella vuota
     rinominata non si riconosce: nuovo ID.
   - **percorso già usato da un nodo rimosso** → si riusa quella riga (stesso
     ID, `removed = 0`) solo se lo sha256 coincide; altrimenti la vecchia riga
     resta rimossa e il nuovo file ha un nuovo ID. Il vincolo di unicità vale
     solo sui nodi attivi (§8.1).
   - **limite noto:** un file modificato **e** spostato nello stesso `/reindex`
     non si riconosce (path e hash diversi) → rimosso + nuovo. Lo staff fa le due
     cose in due `/reindex` separati.
4. Viene mostrata l'anteprima. Il risultato della scansione resta in memoria
   finché l'admin non sceglie, **al massimo 10 minuti**: poi l'anteprima scade
   ("⌛ Anteprima scaduta, rilancia /reindex"), il lock si libera e nulla viene
   applicato.

Scansione e calcolo degli hash girano in un thread (`asyncio.to_thread`): leggere
7,4 GB nell'event loop bloccherebbe le risposte a tutti gli utenti.

**Con ✅ Applica:**

1. Tutte le modifiche in **una sola transazione** SQLite.
2. Si costruisce il **nuovo albero in RAM** (figli ordinati, tastiere pronte) e
   lo si sostituisce al vecchio con una sola assegnazione. Chi sta navigando in
   quell'istante vede o tutto il vecchio o tutto il nuovo, mai un albero a metà.
3. Il messaggio di anteprima viene modificato in
   `✅ Archivio aggiornato: +12 file, 1 modificato, 3 rimossi`.

Se il disco è cambiato di nuovo tra l'anteprima e il click (es. lo staff ha
copiato altri file), il bot rifà la scansione e mostra un'anteprima aggiornata
invece di applicare dati vecchi.

**`file_id` legato al contenuto, non al percorso.** Ai file nuovi o modificati
(solo a quelli) si calcola lo SHA-256. Il `file_id` di Telegram si salva in una
tabella `blobs(sha256 → file_id)`. Conseguenze:

- spostare o rinominare un file o un'intera cartella **non richiede nuovi upload**;
- copie identiche dello stesso file in cartelle diverse si caricano una volta sola;
- sostituire un file con una versione nuova cambia l'hash → nuovo upload, corretto.

Il primo `/reindex` deve calcolare l'hash dell'intero archivio (7,4 GB): sul
Raspberry richiede qualche minuto, gira in background e il bot aggiorna il
messaggio con l'avanzamento. Dai `/reindex` successivi si calcola solo sui file
nuovi o modificati, quindi l'anteprima arriva in un attimo.

**Bottoni di messaggi vecchi:** l'ID nel bottone (`n:142`) resta valido anche se
il nodo è stato spostato o rinominato (vedi sopra). Se il nodo è stato
**rimosso**, il bot risponde con un toast "Questo contenuto è stato rimosso" e
mostra la cartella antenata più vicina che esiste ancora (si risale `parent_id`
fino a un nodo con `removed = 0`, al limite la HOME). L'utente non resta mai
bloccato.

**Novità visibili agli utenti:** grazie ad `added_at`, i file aggiunti negli
ultimi 7 giorni hanno 🆕 nel bottone, e anche le cartelle che li contengono,
così si capisce subito dove c'è materiale nuovo. Le tastiere sono precalcolate,
quindi il 🆕 scadrebbe solo al prossimo `/reindex`: per questo il **task
notturno** (§15) ricostruisce l'albero in RAM ogni notte, senza leggere il disco. Comando `/novita`: i file con
`added_at` negli ultimi 7 giorni (stessa regola del 🆕), raggruppati per cartella.

**`added_at` al primo import:** al primissimo `/reindex` (tabella `nodes` vuota)
`added_at` = `mtime` del file, non `now`; altrimenti tutti i 1.682 file
risulterebbero 🆕 per una settimana. Per questo la copia iniziale va fatta
preservando le date (`rsync -a`, `cp -p`). Dai `/reindex` successivi
`added_at = now`.

**Aggiungere file direttamente dal bot:** vedi §11. Un admin che invia un
documento al bot segue lo stesso flusso del materiale degli utenti, saltando la
moderazione.

```python
# bot/archive.py — schema essenziale
import os, re
from dataclasses import dataclass, field

EXCLUSIVE = "EXCLUSIVE"
PRICE_RE = re.compile(r"^(\d+)\.?")      # "5.nome.pdf" e "10NomeFile.pdf"
HIDDEN = {"Thumbs.db", "desktop.ini"}

@dataclass
class Node:
    id: int
    parent_id: int | None
    name: str          # nome visualizzato (_ e - → spazio, senza prezzo)
    path: str          # relativo ad ARCHIVE_DIR, identico al disco
    is_dir: bool
    depth: int         # 1 = corso; decide testo e colonne (§6.2)
    price: int = 0
    size: int = 0
    children: list[int] = field(default_factory=list)

def parse_name(raw: str, rel_path: str, is_dir: bool) -> tuple[str, int]:
    """Nome da mostrare e prezzo. Il prezzo vale solo per i file sotto EXCLUSIVE/."""
    price = 0
    if not is_dir and rel_path.startswith(EXCLUSIVE + "/"):
        if m := PRICE_RE.match(raw):
            price, raw = int(m.group(1)), raw[m.end():]
    return raw.replace("_", " ").replace("-", " "), price

def is_hidden(name: str) -> bool:
    return name.startswith(".") or name in HIDDEN

def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
```

Ordinamento dei figli: `sorted(children, key=lambda n: (not n.is_dir, natural_key(n.name)))`.

Test minimo da tenere in `tests/test_archive.py`, con i casi presi dall'archivio reale:

```python
assert parse_name("5.(E)manuale.pdf", "EXCLUSIVE/3°_Anno/F/R/5.(E)manuale.pdf", False) == ("(E)manuale.pdf", 5)
assert parse_name("10Luglio21.pdf", "EXCLUSIVE/1°_Anno/A/T/10Luglio21.pdf", False) == ("Luglio21.pdf", 10)
assert parse_name("10 facts.doc", "INGLESE/ESERCIZI/10 facts.doc", False) == ("10 facts.doc", 0)
assert parse_name("2°_Anno", "INFORMATICA/2°_Anno", True) == ("2° Anno", 0)
```

Costo: la scansione richiede pochi millisecondi e l'albero in RAM qualche MB.
**Durante la navigazione non si legge mai il disco**: i click usano solo l'albero
in memoria, aggiornato **solo** da un `/reindex` applicato.

### 6.4 Callback data

```
n:142          apri nodo 142 (cartella → menu, file → invio)
n:142:2        cartella 142, pagina 2
buy:571        conferma acquisto file 571
fav:571        aggiungi/togli dai preferiti
rep:571        segnala file (poi rep:571:<motivo>)
all:142        scarica tutto della cartella 142 (all:142:ok = confermato)
noop           riservato: risponde solo con answer(). I bottoni `disabled` NON hanno
               callback_data (`disabled` è un tipo di bottone: uno solo per bottone)
pick:142[:2]   invio utente: naviga le cartelle per scegliere la destinazione
pick:142:ok    invio utente: "metti qui"
sub:12:ok:5    approva submission 12 con +5 crediti   (solo ADMIN_IDS)
sub:12:no      rifiuta submission 12                  (solo ADMIN_IDS)
dsn:12:142[:2] staff: naviga le cartelle per la submission 12 (solo ADMIN_IDS)
dst:12:142     staff: "salva qui" la submission 12      (solo ADMIN_IDS)
tk:7:ok        chiudi ticket 7 (segnalazione/feedback) (solo ADMIN_IDS)
grp:142        /collega: questo gruppo apre la cartella 142 (solo ADMIN_IDS)
rx:ok / rx:no  applica / annulla /reindex             (solo ADMIN_IDS)
bc:ok / bc:no  conferma / annulla broadcast           (solo ADMIN_IDS)
adm:<op>:142   gestione archivio da Telegram (§11.3)  (solo ADMIN_IDS)
```

Regola: **ogni callback rifà i controlli lato server** (admin, saldo, prezzo
attuale, nodo esistente). Un bottone `disabled` è solo estetica: un client
vecchio può cliccarlo lo stesso.

Sempre ben sotto i 64 byte, leggibile nei log, **valido per sempre** perché
l'ID è nel DB. Il bottone "Indietro" punta semplicemente a `n:<parent_id>`:
niente manipolazione di stringhe, niente hash.

> aiogram offre anche le `CallbackData` tipizzate (`class NodeCb(CallbackData, prefix="n")`):
> si possono usare per comodità, ma il contenuto resta lo stesso, cioè l'ID intero del nodo.

---

## 7. Cache lato Telegram

Questo è il punto che dà il guadagno maggiore.

### 7.1 Il `file_id` è la cache

Quando il bot invia un file, Telegram restituisce un `file_id`. Rispedire lo
stesso `file_id` è **istantaneo**: non si trasferisce un byte, il server
Telegram ha già il file. Quindi:

- ogni file si carica **una volta sola**, nel canale di archivio (§7.3);
- il `file_id` va salvato **su DB** (tabella `blobs`, per hash del contenuto),
  non in RAM;
- `file_unique_id` serve per riconoscere duplicati (es. due utenti che
  mandano lo stesso PDF).

> ⚠ Il `file_id` è **valido solo per il bot che l'ha ottenuto**. Prod e beta
> hanno token, DB e canale storage separati (§13.2), quindi non condividono
> nulla. Lo `storage_message_id` serve per un'altra cosa: se un giorno il token
> di produzione cambia, il nuovo bot (aggiunto al canale) ricava i suoi `file_id`
> con `copy_message`, senza ricaricare 7,4 GB.

```python
# bot/handlers/files.py — invio: sempre da Telegram, il disco solo come riserva
from aiogram.exceptions import TelegramBadRequest

async def send_node_file(bot, chat_id: int, node, protect: bool):
    blob = db.get_blob(node.sha256)          # file_id + message_id nel canale
    if blob and blob.file_id:
        try:
            await bot.send_document(chat_id, blob.file_id, protect_content=protect)
            return
        except TelegramBadRequest:           # file_id non più valido: si ricava di nuovo
            pass
    blob = await storage.ensure_uploaded(bot, node)   # carica nel canale se manca
    await bot.send_document(chat_id, blob.file_id, protect_content=protect)
```

### 7.2 Media di benvenuto

Stessa regola per la GIF/video di `/start` (file `data/<bot>/media/welcome.mp4`,
o il primo file della cartella; senza media il bot manda solo il testo): al primo invio si salva il
`file_id` in una tabella `kv` (`key='welcome_media'`). Da quel momento ogni
`/start` costa zero banda. Ancora meglio: **un solo messaggio** con
`send_animation(file_id, caption=testo_breve, reply_markup=menu)` invece di due.
(La caption ha un limite di 1024 caratteri: il testo di benvenuto va accorciato,
il resto va in `/help`.)

### 7.3 Canale di archivio: i file restano su Telegram

**Come funziona:**

1. Si crea un **canale privato** (es. "UniVrArchive · Storage"), si aggiunge il
   bot come admin e si mette l'ID in `STORAGE_CHAT_ID`.
2. Dopo **✅ Applica** di un `/reindex`, il bot carica **in background** nel
   canale ogni file nuovo o modificato (per hash: se lo stesso contenuto è già
   nel canale, non lo ricarica). Per ogni file salva in `blobs`:
   `sha256 → (file_id, file_unique_id, storage_message_id)`.
   Il messaggio dell'admin mostra l'avanzamento: `⬆️ Caricati 120/340`.
   Nessun comando separato da ricordare.
3. Ogni messaggio nel canale ha come didascalia il percorso del file
   (`INFORMATICA/2° Anno/RETI/esame.pdf`) e l'hash, così il canale si legge
   anche a mano ed è un indice di backup. **Questa didascalia è solo interna.**

**Nessuna traccia del canale verso gli utenti.** Il canale storage non deve mai
essere visibile o deducibile da chi riceve un file:

- invio singolo: `send_document(file_id, caption=<testo nostro>)`. Un invio da
  `file_id` è un messaggio nuovo del bot: niente "inoltrato da", niente
  didascalia del canale;
- "Scarica tutto": un `send_document(file_id, caption=<nostra>)` per file
  (§9.4), quindi stessa garanzia dell'invio singolo;
- recupero di un `file_id` scaduto: `copy_message` dal canale **con
  `caption=<nostra>`**, mai la didascalia originale;
- **mai** `forward_message`/`forwardMessages` dal canale (mostrerebbero il nome
  del canale);
- mai l'ID o il link del canale in testi, errori, log inviati agli utenti o
  `LOG_CHAT_ID` pubblici;
- il canale è privato, senza link d'invito attivi; `STORAGE_CHAT_ID` sta solo nel
  `.env`.
4. Gli utenti ricevono **sempre** il file tramite `file_id`: invio istantaneo,
   zero banda del Raspberry. Se un utente clicca un file nuovo prima che sia
   stato caricato, il bot lo carica in quel momento (stessa funzione
   `ensure_uploaded`) e l'utente aspetta solo quella volta. `ensure_uploaded`
   ha un **lock per sha256**: se due utenti (o l'upload in background) chiedono
   lo stesso file insieme, si carica una volta sola e gli altri aspettano lo
   stesso risultato.

**Tempi del primo caricamento:** 1.682 file. Telegram limita i messaggi di un
bot nella stessa chat (circa 20 al minuto nei gruppi/canali), quindi servono
**circa 1,5 ore** come minimo, di più se la banda in upload del Pi è bassa
(7,4 GB a 10 Mbit/s ≈ 1 h 40 min). Gira in background, riprende da dove era
dopo un riavvio (§12.1), e nel frattempo il bot funziona: i file non ancora
caricati partono al primo click.

**Sono permanenti?** In pratica sì, con alcune precisazioni:

- I messaggi di un canale **non scadono**: restano finché qualcuno non li
  cancella o il canale non viene eliminato. Il cloud Telegram non ha limiti di
  spazio.
- Il `file_id` **non ha una scadenza documentata**, ma Telegram non ne garantisce
  formalmente la durata. Per questo si salva anche lo `storage_message_id`: se un
  `file_id` smette di funzionare, il bot fa `copy_message` dal canale e ricava un
  `file_id` nuovo, senza ricaricare niente dal disco.
- Lo `storage_message_id` vale per **qualsiasi bot** membro del canale: se un
  giorno cambia il token, il nuovo bot ottiene i propri `file_id` con
  `copy_message`, senza rifare 7,4 GB di upload. (Da provare una volta prima di
  contarci: aggiungere temporaneamente il bot beta al canale di prod e fare una
  `copy_message`.)
- **Rischio reale:** materiale protetto da copyright può essere segnalato e
  rimosso da Telegram, e in quel caso sparisce anche dal canale. Per questo il
  **disco resta l'originale** e va comunque copiato su un backup (§15): dal disco
  si ricarica tutto con un `/reindex`.

**Regole per il canale:**

- **Nessuno** ci scrive o cancella a mano: solo il bot. Lo staff lo può leggere.
- Mai eliminare messaggi dal canale per "fare ordine": romperebbe gli
  `storage_message_id`. I file rimossi dall'archivio restano nel canale e non
  danno fastidio (non sono visibili agli utenti).
- File oltre 50 MB: per caricarli nel canale serve il server Bot API locale (§7.4).

### 7.4 Altri trucchi della Bot API

| Trucco | Effetto |
|---|---|
| `edit_message_text` invece di delete + send | 1 chiamata invece di 2, nessun lampeggio, la chat resta pulita |
| `answer_callback_query()` subito, come prima istruzione | toglie il caricamento dal bottone; con `text=` mostra un toast, con `show_alert=True` un popup |
| `send_document` da `file_id` in sequenza | bottone "📥 Scarica tutto": ordine dell'archivio, nessuna traccia del canale (§9.4) |
| `protect_content=True` | i file Exclusive non si possono inoltrare né salvare (rispetta il "non condividere") |
| **Inline mode** + `InlineQueryResultCachedDocument` | l'utente scrive `@UniVrInfoArchive_bot analisi` in qualsiasi chat e riceve i file; funziona solo grazie ai `file_id` salvati; `cache_time` fa cachare i risultati ai server Telegram |
| `allowed_updates` limitati in `start_polling` (`dp.resolve_used_update_types()`) | Telegram non manda tipi di update che il bot ignora |
| `link_preview_options` disattivate | messaggi più leggeri, niente fetch di anteprime |
| `set_my_commands` all'avvio | menu comandi nativo con descrizioni, l'utente non deve ricordare nulla |
| Tastiere costruite all'indicizzazione e tenute in RAM | zero lavoro per click (la pagina della cartella è già pronta) |
| **Local Bot API server** (`telegram-bot-api`) | upload fino a 2 GB e trasferimenti locali. **Serve davvero:** l'archivio reale ha 32 file oltre i 50 MB, che con la Bot API cloud non si possono inviare. È un container in più nel `compose.yaml` (immagine `aiogram/telegram-bot-api`, richiede `api_id`/`api_hash` da my.telegram.org); in aiogram basta `AiohttpSession(api=TelegramAPIServer.from_base("http://telegram-bot-api:8081", is_local=True))` |

---

## 8. Database

### 8.1 Schema

Le tre tabelle attuali (`User`, `Reserved`, `Download`) diventano una sola
tabella utenti, più le tabelle che servono davvero. Chiavi primarie, vincoli e
indici: niente più righe mancanti.

```sql
PRAGMA journal_mode = WAL;        -- letture e scritture concorrenti, meno fsync
PRAGMA synchronous = NORMAL;      -- sicuro con WAL, molte meno scritture fisiche
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,         -- Telegram user id
    username    TEXT,
    first_name  TEXT,
    credits     INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
    vip_until   TEXT,                        -- NULL = non VIP; '9999-12-31' = permanente
    downloads   INTEGER NOT NULL DEFAULT 0,  -- totale storico (include quelli migrati dal vecchio DB)
    blocked     INTEGER NOT NULL DEFAULT 0,  -- l'utente ha bloccato il bot
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT
);
CREATE INDEX IF NOT EXISTS users_username ON users(username COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS nodes (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL,           -- relativo ad ARCHIVE_DIR
    parent_id       INTEGER REFERENCES nodes(id),
    is_dir          INTEGER NOT NULL,
    price           INTEGER NOT NULL DEFAULT 0,
    size            INTEGER,
    mtime           REAL,
    sha256          TEXT REFERENCES blobs(sha256),   -- contenuto del file (NULL per le cartelle);
                                             -- la riga in blobs (anche senza file_id) si crea
                                             -- nella stessa transazione, prima del nodo
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),  -- per il badge 🆕
    hidden          INTEGER NOT NULL DEFAULT 0,  -- prezzo Exclusive non valido (§6.2): invisibile ma conservato
    removed         INTEGER NOT NULL DEFAULT 0
);
-- unico solo tra i nodi attivi: un nodo rimosso non blocca il suo vecchio percorso
CREATE UNIQUE INDEX IF NOT EXISTS nodes_path_active ON nodes(path) WHERE removed = 0;
CREATE INDEX IF NOT EXISTS nodes_sha256 ON nodes(sha256);

CREATE TABLE IF NOT EXISTS blobs (           -- un contenuto = un upload nel canale di archivio
    sha256              TEXT PRIMARY KEY,
    file_id             TEXT,                -- valido solo per questo bot
    file_unique_id      TEXT,
    storage_message_id  INTEGER              -- messaggio nel canale: vale per qualsiasi bot
);

CREATE TABLE IF NOT EXISTS purchases (       -- un file comprato resta tuo
    user_id  INTEGER NOT NULL REFERENCES users(id),
    node_id  INTEGER NOT NULL REFERENCES nodes(id),  -- l'ID sopravvive a rinomine, spostamenti
                                             -- (§6.3), modifiche del contenuto e cambi di prezzo
    price    INTEGER NOT NULL,               -- prezzo pagato in quel momento
    at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, node_id)
);

CREATE TABLE IF NOT EXISTS credit_log (      -- audit: chi ha dato/tolto crediti e perché
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    delta   INTEGER NOT NULL,
    reason  TEXT NOT NULL,                   -- 'purchase:<node_id>', 'submission:<id>', 'admin:<admin_id>:<motivo>'
    at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS submissions (    -- materiale inviato dagli utenti (§11)
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    file_id          TEXT NOT NULL,          -- del documento ricevuto: riusabile, niente re-upload
    file_unique_id   TEXT NOT NULL,
    file_name        TEXT NOT NULL,          -- nome originale (sanificato prima di toccare il disco)
    size             INTEGER,
    sha256           TEXT,                   -- calcolato alla ricezione: dedup vero
    inbox_path       TEXT,                   -- copia in data/<bot>/inbox/ finché si decide
    duplicate_of     INTEGER REFERENCES nodes(id),   -- se il contenuto è già nell'archivio
    hint_node_id     INTEGER REFERENCES nodes(id),   -- cartella suggerita dall'utente
    user_message_id  INTEGER,                -- per reazioni 👀/👍 sul messaggio dell'utente
    staff_message_id INTEGER,                -- messaggio nel canale staff da editare
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected','duplicate')),
    credits          INTEGER NOT NULL DEFAULT 0,     -- crediti dati all'approvazione
    dest_path        TEXT,                   -- dove è stato salvato su disco
    reviewed_by      INTEGER,                -- admin che ha deciso
    reviewed_at      TEXT,
    at               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS submissions_unique ON submissions(file_unique_id);

CREATE TABLE IF NOT EXISTS favorites (       -- ⭐ /preferiti (file e cartelle)
    user_id  INTEGER NOT NULL REFERENCES users(id),
    node_id  INTEGER NOT NULL REFERENCES nodes(id),
    at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, node_id)
);

CREATE TABLE IF NOT EXISTS downloads (       -- 🕘 /recenti e "top file" in /stats
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    node_id  INTEGER NOT NULL REFERENCES nodes(id),
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS downloads_user ON downloads(user_id, at DESC);
CREATE INDEX IF NOT EXISTS downloads_node ON downloads(node_id);
-- conservati 12 mesi (task notturno, §15); users.downloads tiene il totale storico

CREATE TABLE IF NOT EXISTS tickets (         -- feedback, segnalazioni, richieste di rimozione
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    kind             TEXT NOT NULL CHECK (kind IN ('feedback','report','removal')),
    node_id          INTEGER REFERENCES nodes(id),   -- per report/removal
    text             TEXT,
    staff_message_id INTEGER NOT NULL,       -- messaggio nel canale staff: le reply lì
                                             -- vengono girate all'utente (§12.3)
    status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    closed_by        INTEGER,
    at               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS tickets_staff_msg ON tickets(staff_message_id);

CREATE TABLE IF NOT EXISTS group_folders (   -- gruppi dei corsi collegati con /collega (§9.9)
    chat_id   INTEGER PRIMARY KEY,
    node_id   INTEGER NOT NULL REFERENCES nodes(id),
    linked_by INTEGER NOT NULL,
    at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);  -- welcome_media file_id, ecc.

PRAGMA user_version = 1;   -- versione schema per migrazioni future
```

Migrazioni: `PRAGMA user_version` + una lista di script SQL in `db.py`,
applicati in ordine all'avvio. Nessun framework necessario.

### 8.2 Registrazione utente in una query

```sql
INSERT INTO users (id, username, first_name, last_seen)
VALUES (?, ?, ?, datetime('now'))
ON CONFLICT(id) DO UPDATE SET
    username   = excluded.username,
    first_name = excluded.first_name,
    blocked    = 0,
    last_seen  = excluded.last_seen;
```

Elimina il `SELECT` + `INSERT` attuale e il bug delle righe mancanti.

**Quando:** su **qualsiasi** update con un utente (messaggio, click, ricerca
inline, gruppo, deep link), tramite un middleware di aiogram, non solo su
`/start`. Chi usa solo la ricerca inline o i gruppi altrimenti non sarebbe in
`users`, e il suo primo download o preferito violerebbe la foreign key. Per non
scrivere a ogni click, il middleware fa l'upsert solo se l'utente non è nel
dizionario in RAM o se l'ultimo aggiornamento ha più di 1 ora (§8.3).

**`@username` nei comandi admin:** lo username si cerca tra gli utenti con
`last_seen` più recente; se ce ne sono più di uno, o nessuno, il bot risponde
"Ambiguo/non trovato, usa l'ID numerico". L'ID numerico funziona sempre.

### 8.3 Meno scritture (importante su SD/SSD)

| Oggi | Domani |
|---|---|
| 2 `UPDATE` per ogni download (`Download`, `User.state`) | 1 `INSERT INTO downloads` + `UPDATE users SET downloads = downloads + 1`, nella **stessa transazione** (un solo fsync) |
| scrittura di `state` a ogni download | `last_seen` aggiornato solo se l'ultimo aggiornamento in RAM è più vecchio di 1 ora (dizionario `user_id → timestamp`) |
| `file_id` riscritto a ogni invio | scritto **una volta** quando manca |
| log DEBUG su file | log INFO su stdout (gestito da Docker/journald con rotazione) |
| commit dopo ogni query | WAL + `synchronous=NORMAL`; operazioni multiple in un'unica transazione |

Opzionale, solo se i numeri lo giustificano: contatori download accumulati in
RAM e scritti ogni 60 secondi con un job. Con qualche centinaio di utenti non serve.

---

## 9. Navigazione, funzioni sui file e UX

Riferimento: **Bot API 10.3** (agosto 2026), supportata da aiogram 3.31 (§4).
Accanto a ogni funzione c'è la versione dell'API che l'ha introdotta. I client
Telegram vecchi non vedono sempre le novità (es. i colori dei bottoni): ogni
funzione va scelta in modo che, se il client non la supporta, il bot resti
comunque usabile.

### 9.1 Funzioni Telegram usate e dove

| Funzione | API | Dove la usiamo |
|---|---|---|
| `answerCallbackQuery` (toast / alert) | storica | ogni click: niente più caricamento sul bottone |
| `editMessageText` | storica | navigazione: un solo messaggio che cambia |
| **Bottoni colorati** `style`: `primary` (blu), `success` (verde), `danger` (rosso) | 9.4 | Acquista = verde, Annulla = rosso, Home = blu |
| **Icona custom emoji** sui bottoni `icon_custom_emoji_id` | 9.4 | opzionale: richiede che il proprietario del bot abbia Telegram Premium (o un username comprato su Fragment) |
| **Bottone disabilitato** `disabled` | 10.3 | indicatore pagina `2/5`, file Exclusive non acquistabili |
| **Bottone copia testo** `copy_text` (max 256 caratteri) | 7.11 | "🔗 Copia link" di file e cartelle |
| `switch_inline_query_chosen_chat` | storica | "📤 Condividi": l'utente sceglie la chat e invia il file |
| `switch_inline_query_current_chat` | storica | "🔍 Cerca" nel menu: apre la ricerca inline nella stessa chat |
| Inline mode + `InlineQueryResultCachedDocument` | storica | ricerca e condivisione in qualsiasi chat, file da `file_id` |
| `protect_content` | storica | file Exclusive: niente inoltro né salvataggio |
| **Rich messages** con blocchi documento, tabelle, sezioni espandibili, bottoni | 10.1 / 10.3 | indice cartella e "scarica tutto" in un unico messaggio (sperimentale, §9.5) |
| **Messaggi e comandi effimeri** | 10.2 / 10.3 | nei gruppi dei corsi: menu visibile solo a chi lo chiede (§9.9) |
| **Effetti messaggio** `message_effect_id` | 7.4 | 🎉 su acquisto riuscito e materiale approvato (solo chat private) |
| **Reazioni** `setMessageReaction` | 7.0 | 👀 sul file inviato da un utente, poi 👍 quando viene approvato |
| Citazione espandibile (`expandable_blockquote`) | 7.4 | testi lunghi di `/start` e `/help` chiusi di default |
| Entità `date_time` | 9.5 | "aggiunto il …" mostrato nel fuso orario dell'utente |
| `setMyCommands` con scope | storica | menu comandi utenti e menu admin separati |
| Deep link `?start=` | storica | link diretti a cartelle e file |
| Topic nelle chat private | 9.3 / 9.4 | dopo la v1, da provare sul beta (§9.10) |
| Mini App | 7.x / 8.0 | rimandata, vedi `FUTURO_MINI_APP.md` |

Non servono qui: **pagamenti e Telegram Stars** (scelta: nessun pagamento nel
bot, §10.3), paid media, checklist, regali, storie, business account.

### 9.2 Navigazione: un solo messaggio che cambia

```
📂 INFORMATICA › 2° Anno › ALGORITMI
⏰Scegli il Materiale⏰

[Esami]
[Appunti 🆕]
[📖Formulario.pdf📖 · 1.2 MB]
[◀️]  [2/3]  [▶️]                    ← "2/3" è un bottone disabilitato
[<< BACK]  [🏠HOME]                  ← HOME in blu (primary)
[🔍 Cerca]  [📥 Scarica tutto]  [🔗 Link]
```

- **Testi, icone e colonne identici a oggi** (tabella in §6.2): chi usa il bot
  non deve reimparare nulla.
- **Breadcrumb** sopra il testo: l'utente sa sempre dove si trova.
- **Paginazione** a **10 elementi per pagina**; l'indicatore di pagina è un
  bottone con **solo** `disabled=DisabledButton()`. Niente `callback_data`
  insieme: per la Bot API ogni bottone ha esattamente un tipo, e `disabled` è
  uno di questi.
- **🆕** su file e cartelle con materiale aggiunto negli ultimi 7 giorni (§6.3).
- **🔍 Cerca** apre la ricerca inline nella chat (`switch_inline_query_current_chat`).
- **🔗 Link** copia negli appunti il link diretto alla cartella
  (`copy_text`: `https://t.me/<bot>?start=n_142`): perfetto da incollare nei
  gruppi del corso.
- I file **vengono inviati come nuovi messaggi** sotto il menu; il menu resta.

```python
# bot/handlers/browse.py (aiogram 3)
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

router = Router()

@router.callback_query(F.data.startswith("n:"))
async def on_node(q: CallbackQuery):
    _, node_id, *page = q.data.split(":")
    node = archive.get(int(node_id))
    if node is None:                                  # rimosso o spostato
        await q.answer(texts.MOVED, show_alert=True)
        return await show_folder(q, archive.nearest_existing_parent(int(node_id)))
    if not node.is_dir:
        return await files.open_file(q, node)        # risponde lui alla query
    await q.answer()
    await show_folder(q, node, page=int(page[0]) if page else 0)

async def show_folder(q: CallbackQuery, node, page: int = 0):
    text, kb = keyboards.folder(node, page)
    try:
        await q.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:                  # doppio tap: contenuto identico
        if "message is not modified" not in str(e):
            raise
```

Un handler per la navigazione sostituisce `inline_button_handler`,
`send_buttons`, `MainButtonsHandler` e tutto `ExclusiveButtonHandler`.

### 9.3 Cosa succede quando si tocca un file

**File gratuito:** il bot risponde alla query e invia subito il documento (da
`file_id`, istantaneo). Sotto il documento ci sono le azioni sul file:

```
📄 Formulario.pdf
📂 INFORMATICA › 2° Anno › ALGORITMI
1.2 MB · aggiunto il 3 novembre                  ← entità date_time

[📤 Condividi]  [🔗 Copia link]
[⭐ Salva]      [⚠️ Segnala]
```

| Bottone | Tipo | Cosa fa |
|---|---|---|
| 📤 Condividi | `switch_inline_query_chosen_chat` con query `f:571` | l'utente sceglie una chat (amico, gruppo) e il file parte via inline mode, da `file_id` |
| 🔗 Copia link | `copy_text` con `https://t.me/<bot>?start=f_571` | link diretto al file: chi lo apre riceve il file dal bot |
| ⭐ Salva | callback | aggiunge/toglie dai **preferiti** (`/preferiti`) |
| ⚠️ Segnala | callback | "file rotto / sbagliato / nella cartella sbagliata" → messaggio nel canale staff con percorso e utente |

**File Exclusive (prezzo > 0):**

1. Se l'utente è VIP o l'ha già acquistato → invio diretto con `protect_content=True`.
2. Altrimenti il bot mostra una scheda di conferma (edit del menu, non un nuovo messaggio):
   ```
   ⭐ (E)EsameEsi.pdf · 2.3 MB
   Costo: 5 crediti · Il tuo saldo: 12

   [✅ Acquista per 5 crediti]   ← style "success" (verde)
   [Annulla]                     ← style "danger" (rosso)
   ```
3. Saldo insufficiente → il bottone Acquista è `disabled` e sotto compare
   "📨 Come ottenere crediti" (spiega che si guadagnano inviando materiale, §11).
4. Acquisto riuscito → file inviato con `protect_content=True` e
   **effetto 🎉** (`message_effect_id`). Nessun bottone Condividi sui file
   Exclusive; il link copiato porta alla scheda di acquisto, non al file.

### 9.4 Scaricare una cartella intera

Bottone **📥 Scarica tutto** (solo per i file gratuiti della cartella):

1. **Solo i file diretti** della cartella, non le sottocartelle (ognuna ha il
   suo bottone). Il bottone non compare se la cartella non ha file gratuiti.
2. Sopra i 20 file chiede conferma: "Stai per ricevere 37 file (210 MB). Confermi?".
3. Invio **nell'ordine dell'archivio** (lo stesso dei bottoni): un
   `send_document(file_id)` per file, circa 1 al secondo (limite Telegram per
   singola chat), come task in background. Un messaggio di stato
   "📥 12/37…" si aggiorna ogni 10 file.
   `copyMessages` è stato scartato: accetta gli ID solo in ordine crescente,
   quindi i file arriverebbero nell'ordine in cui sono stati caricati nel
   canale, non in quello della cartella.
4. Un solo "Scarica tutto" attivo per utente alla volta; un secondo click
   risponde con toast "Download già in corso".
5. I file Exclusive della cartella non sono inclusi: vanno acquistati uno per uno.
6. Ogni file inviato conta come download (tabella `downloads`), come il click
   singolo.

### 9.5 Rich messages (sperimentale)

I **rich messages** (10.1, documenti dalla 10.3) sono messaggi strutturati in
blocchi: titoli, paragrafi, tabelle, sezioni espandibili (`details`), gruppi di
bottoni e **blocchi documento** con i file allegati. Limiti: 500 blocchi, 50
allegati, 32.768 caratteri. I file si possono riusare da `file_id` già caricati.

Due usi ideali per l'archivio:

- **Indice cartella:** una tabella `Nome | Dimensione | Aggiunto` con le
  sottocartelle come sezioni espandibili. Utile per materie con tanti file,
  dove la lista di bottoni diventa lunga.
- **"Scarica tutto" in un unico messaggio** (fino a 50 file): titolo con il
  breadcrumb, una sezione espandibile per sottocartella, dentro i documenti con
  la loro didascalia. Un solo messaggio ordinato invece di 50 documenti in fila.

**Prudenza:** sono funzioni di pochi mesi fa e i client non aggiornati
potrebbero non mostrarle bene. Vanno dietro un'opzione (`RICH_MESSAGES=1` nel
`.env`), con l'invio in sequenza (§9.4) come comportamento di default, e provate su
Android, iOS e Desktop prima di attivarle per tutti. La navigazione principale
resta con la tastiera inline normale, che funziona ovunque.

### 9.6 Ricerca

- **Inline mode** (`@bot analisi` in qualsiasi chat, o dal bottone 🔍 Cerca):
  ricerca nei nomi dei nodi, risultati `InlineQueryResultCachedDocument` dal
  `file_id` del canale di archivio. I file Exclusive e quelli nascosti non
  compaiono **mai**: il filtro sta nell'handler inline, quindi vale anche per
  la query `f:<id>` del bottone Condividi scritta a mano con l'ID di un file
  Exclusive (risultato vuoto). Max 50 risultati per risposta, poi `next_offset`.
  `cache_time` fa memorizzare i risultati ai server Telegram.
  I download via inline si contano con `chosen_inline_result` (va attivato una
  volta con `/setinlinefeedback` su @BotFather).
- I nodi `hidden` o `removed` non compaiono in nessuna ricerca.
- **`/cerca testo`** in chat: risultati come bottoni `n:<id>` con breadcrumb
  breve (`ALGORITMI › Esami`), così si distinguono file con lo stesso nome.
- Per poche migliaia di nodi basta una ricerca in RAM (`casefold()` + `in`,
  senza accenti con `unicodedata`). Se l'archivio cresce molto: tabella FTS5.

### 9.7 Preferiti, recenti, novità

- **⭐ Preferiti:** tabella `favorites(user_id, node_id)`, comando `/preferiti`.
  Si possono salvare file e cartelle (es. la cartella della propria materia).
  Restano validi dopo spostamenti/rinomine perché l'ID si conserva (§6.3);
  i nodi rimossi non vengono mostrati.
- **🕘 Recenti:** gli ultimi 10 file scaricati (tabella `downloads`), comando
  `/recenti`.
- **🆕 Novità:** comando `/novita` con i file aggiunti negli ultimi 7 giorni
  (stessa regola del badge 🆕), raggruppati per cartella.

### 9.8 Deep link

| Link | Effetto |
|---|---|
| `t.me/<bot>?start=n_142` | apre la cartella 142 |
| `t.me/<bot>?start=f_571` | invia il file 571 (o la scheda di acquisto se è Exclusive) |
| `t.me/<bot>?start=s_<base64url>` | apre la ricerca con il testo codificato |

Il parametro di `?start=` accetta solo `A-Z a-z 0-9 _ -` e al massimo 64
caratteri: la query di ricerca va codificata in base64url senza `=` finali
(`analisi matematica` → `s_YW5hbGlzaSBtYXRlbWF0aWNh`), il che limita la ricerca
a ~45 caratteri. Un parametro non valido apre semplicemente la HOME.

Lo staff può fissare nei gruppi di ogni corso il link alla cartella del corso.

### 9.9 Nei gruppi dei corsi: messaggi effimeri

Dalla 10.2 un bot in un gruppo può mandare **messaggi effimeri**: li vede solo
l'utente destinatario, gli altri membri no. Il bot può rispondere così entro 15
secondi da un'azione dell'utente (comando o click); se è admin del gruppo, anche
in qualsiasi momento. Non sono permanenti: possono sparire dopo un po' o al
riavvio dell'app, e la consegna non è garantita.

Uso per UniVrArchive:

- Il bot viene aggiunto ai gruppi dei corsi.
- **Collegamento:** un admin (di `ADMIN_IDS`) scrive `/collega` nel gruppo e
  sceglie dall'albero la cartella del corso (`grp:<node_id>`), salvata in
  `group_folders`. `/scollega` lo rimuove. **In un gruppo non collegato il bot
  non risponde a nulla**: chi lo aggiunge a un gruppo qualsiasi non ottiene
  niente. Se la cartella collegata viene rimossa, si usa la cartella antenata
  più vicina (stessa regola dei bottoni vecchi, §6.3).
- `/materiale` è un **comando effimero** (`BotCommand.is_ephemeral = True`):
  il comando stesso non compare nel gruppo.
- Il bot risponde con il menu della cartella collegata **visibile solo a chi
  l'ha chiesto**; la navigazione modifica quel messaggio effimero
  (`editEphemeralMessageText`). Si può risalire fino alla HOME.
- Toccando un file, il bot lo manda **in privato** all'utente, così resta nella
  sua chat. Se l'utente non ha mai avviato il bot, il messaggio effimero dice
  "Aprimi in privato" con un deep link.

Risultato: il bot è utile nei gruppi senza riempirli di messaggi.

### 9.10 Topic nella chat privata (dopo la v1, da provare sul beta)

Dalla 9.3/9.4 i bot possono avere **topic nelle chat private**: la chat col bot
diventa divisa in sezioni, per esempio `📚 Archivio`, `⭐ Exclusive`,
`📨 Invia materiale`, `💬 Feedback`. I file scaricati finirebbero nel topic
Archivio, le conversazioni con lo staff in Feedback. È ordinato, ma cambia molto
l'aspetto della chat a cui gli utenti sono abituati: da provare sul bot BETA con
qualche utente prima di decidere.

### 9.11 Mini App — rimandata

Fuori dalla v1. Analisi, costi e condizioni per riprenderla in
[`FUTURO_MINI_APP.md`](FUTURO_MINI_APP.md). Nessuna parte della v1 deve
prepararla in anticipo.

### 9.12 `/start`, menu e messaggi

- **`/start`:** un solo messaggio (animazione da `file_id` + caption breve +
  menu). Le parti lunghe (comandi, donazioni, VIP) dentro una **citazione
  espandibile**, chiusa di default.
- **🏠 HOME** fa **edit** del messaggio, non un nuovo `/start`.
- **Menu comandi** (`setMyCommands`): `/start`, `/cerca`, `/preferiti`,
  `/recenti`, `/novita`, `/crediti`, `/feedback`, `/help`, `/privacy`,
  `/rimozione`. Gli admin vedono anche i loro comandi (scope per chat).
- **Testi in HTML** invece di MarkdownV2: basta `html.escape()` sui nomi, molto
  meno fragile.
- **Errori come toast/alert** sulla callback, non come nuovi messaggi in chat.
- **Materiale inviato dagli utenti:** invece di un messaggio di conferma, il bot
  mette la **reazione 👀** sul file ("ricevuto, in revisione") e la cambia in
  **👍** quando viene approvato, più un messaggio con effetto 🎉 e i crediti
  ricevuti. Meno messaggi, stato sempre visibile sul file stesso.
- **Error handler globale** (`@router.errors()`): logga con traceback e notifica
  in `LOG_CHAT_ID`, senza far crashare nulla.
- `/feedback` senza testo → "Scrivi il messaggio dopo il comando, es. `/feedback ...`".
  Con testo → ticket `feedback` nel canale staff; lo staff risponde con una
  reply e l'utente la riceve (§12.3).

---

## 10. Crediti, Exclusive, VIP, donazioni

### 10.1 Come si decide il prezzo

**Lo decide lo staff, file per file, scrivendolo nel nome del file.** È la stessa
regola di oggi, quindi l'archivio attuale funziona senza modifiche:

- solo i file dentro `EXCLUSIVE/` hanno un prezzo;
- il prezzo è il **numero all'inizio del nome**: `5.(E)EsameEsi.pdf` costa
  5 crediti, `10Luglio21.pdf` ne costa 10 (§6.2);
- il bot non calcola né suggerisce prezzi: legge quello che c'è scritto.

**Prezzi in uso oggi** (archivio reale, 17 file Exclusive):

| Prezzo | File | Che tipo di materiale |
|---|---|---|
| 5 crediti | 4 | riassunti, singoli esami |
| 10 crediti | 11 | temi d'esame di Architettura, la "bibbia" di Fondamenti |
| 20 crediti | 2 | codice C del laboratorio di Sistemi Operativi |

Conviene scrivere nel README una regola semplice per lo staff, partendo da
questa tabella (es. 5 = riassunto o esame singolo, 10 = raccolta di esami
risolti, 20 = progetti e codice), così prezzi simili valgono per materiale simile.

**Come si guadagnano i crediti** — solo due modi, nessun acquisto con denaro:

1. **inviando materiale** che viene approvato (§11): l'admin sceglie +5 / +10 /
   +20 nel bottone di approvazione;
2. **a mano da un admin** con `/crediti_add` (correzioni, premi, ex rimborsi).

Se un materiale approvato vale ~5–10 crediti, un file Exclusive da 10 costa
"un contributo": chi dà, riceve.

**Cambiare il prezzo di un file:** si rinomina (`10.Esame.pdf` → `5.Esame.pdf`)
e si lancia `/reindex`. L'anteprima mostra la riga `💰 prezzo cambiato: 10 → 5`
e con ✅ Applica vale da subito per i nuovi acquisti.

- **Chi l'aveva già comprato non perde nulla:** gli acquisti sono legati
  all'**ID del nodo**, che si conserva quando il file viene rinominato, spostato
  (riconosciuto via sha256, §6.3), corretto (stesso path, nuovo contenuto) o
  cambia prezzo. Chi l'ha comprato riceve sempre la versione aggiornata.
- **Unico limite:** modificare **e** spostare lo stesso file nello stesso
  `/reindex` lo fa risultare "rimosso + nuovo", e gli acquirenti perdono
  l'accesso. Regola per lo staff (da scrivere nel README): prima si corregge e
  si fa `/reindex`, poi si sposta e si fa un altro `/reindex`. L'anteprima avvisa
  quando un file Exclusive con acquisti risulta rimosso.
- **Nessun rimborso automatico** se il prezzo scende: in `purchases` resta il
  prezzo pagato, quindi un admin può verificarlo e restituire la differenza a
  mano, se vuole.
- **Rendere gratuito un file:** si toglie il numero dal nome, oppure lo si
  sposta fuori da `EXCLUSIVE/`.

### 10.2 Flusso di acquisto

1. Click su file con `price > 0`:
   - VIP o già acquistato → invio diretto.
   - Altrimenti → `answer` + edit con la scheda di conferma (bottoni verde/rosso,
     Acquista disabilitato se il saldo non basta: dettagli in §9.3).
2. Click su `buy:<id>` → transazione atomica:

```python
# bot/db.py
def buy(user_id: int, node) -> bool:
    price = node.price          # prezzo letto ADESSO dall'albero, non dalla scheda mostrata prima
    with conn:  # transazione: tutto o niente
        if conn.execute("SELECT 1 FROM purchases WHERE user_id=? AND node_id=?",
                        (user_id, node.id)).fetchone():
            return True                                      # già comprato: gratis
        cur = conn.execute(
            "UPDATE users SET credits = credits - ? WHERE id = ? AND credits >= ?",
            (price, user_id, price))
        if cur.rowcount == 0:
            return False                                     # saldo insufficiente
        conn.execute("INSERT INTO purchases (user_id, node_id, price) VALUES (?,?,?)",
                     (user_id, node.id, price))
        conn.execute("INSERT INTO credit_log (user_id, delta, reason) VALUES (?,?,?)",
                     (user_id, -price, f"purchase:{node.id}"))
    return True
```

3. Invio del file (con `protect_content=True`). Se l'invio fallisce, il
   file risulta comunque acquistato: l'utente riclicca e lo riceve gratis. Nessun
   credito perso, nessun doppio addebito.

### 10.3 VIP, donazioni, correzioni

**Nessun pagamento dentro il bot.** Niente Telegram Stars, invoice o
abbonamenti: i crediti non si comprano. Motivi: niente denaro legato a materiale
di cui non si detengono i diritti, niente gestione di rimborsi e contestazioni.

- **VIP** = `users.vip_until > now`. Lo dà solo un admin:
  `/vip @utente 30` → 30 giorni (si somma alla scadenza attuale se ancora valida),
  `/vip @utente 0` → permanente (`'9999-12-31'`), `/vip @utente off` → revoca.
  Scade da solo: nessun job, il controllo è al momento del click.
- **Donazioni:** solo il link esterno `DONATION_LINK`, mostrato in `/start` e
  `/help`. Il bot non sa chi ha donato; se lo staff vuole premiare un donatore
  usa `/crediti_add` o `/vip` a mano.
- **Rimborsi:** non esistono come funzione. Ogni correzione è manuale:
  `/crediti_add @utente 5 motivo` (o negativo). Sempre registrata in `credit_log`
  con `reason='admin:<id>:<motivo>'`. Il saldo non scende mai sotto zero
  (`CHECK`): un `/crediti_add` negativo oltre il saldo viene rifiutato.

---

## 11. Invio materiale dagli utenti

Oggi: forward nel canale staff, poi un admin deve dare i crediti a mano con
`/givecredits @utente#N` e copiare il file nell'archivio a mano.

Obiettivo: **tutto da Telegram**, dall'invio al file nell'archivio, senza che lo
staff debba aprire SFTP. Il disco resta l'unica fonte di verità: il bot scrive
su disco, e il file diventa visibile agli utenti al `/reindex` come ogni altro.

### 11.1 Flusso completo

```
UTENTE                       BOT                                  CANALE STAFF (solo ADMIN_IDS agiscono)
──────                       ───                                  ─────────────
manda documento ───────────▶ 1. controlli (estensione, dimensione, rate)
                             2. dedup veloce: file_unique_id già inviato?
                             3. download subito (server locale) → copia in
                                data/<bot>/inbox/<sub_id>.<ext>, sha256
                             4. dedup vero: sha256 già nell'archivio?
                                → status 'duplicate', "Grazie, questo file lo
                                  abbiamo già" con link al file. Fine.
                             5. "Per quale materia?" ◀── albero (pick:…), senza EXCLUSIVE
sceglie cartella ──────────▶    o "Non so" (anche dopo 10 min senza risposta)
                             6. riga submissions (pending), reazione 👀
                             7. copy_message nel canale staff ──▶ 📄 file + scheda:
                                                                   da: @utente (id) · 2.3 MB
                                                                   suggerita: INFORMATICA › 2° Anno › RETI
                                                                   [✅ +5] [✅ +10] [✅ +20]
                                                                   [📂 Cambia cartella] [❌ Rifiuta]
                             8. admin clicca ✅ +10 ◀──────────────
                             9. sposta inbox/… → archive/<cartella>/<nome>
                            10. transazione: status, crediti, credit_log
                            11. blob: sha256 → file_id già noto
                                (copia nel canale storage in background)
◀─────────────────────────── 12. reazione 👍 + "🎉 +10 crediti"
                            13. scheda staff editata: ──────────▶ "✅ Approvato da @admin · +10
                                                                   → .../RETI/esame.pdf
                                                                   ⏳ visibile al prossimo /reindex"
                                                                   [🔄 Reindex ora]
```

Il download avviene **alla ricezione** (passo 3), non all'approvazione: così
i duplicati si scartano subito e lo staff non si vede annullare un'approvazione
già data. Fino alla decisione il file sta in `data/<bot>/inbox/`, fuori
dall'archivio: non può finire nel bot per sbaglio con un `/reindex`.

**Più file insieme (album):** i documenti arrivati con lo stesso
`media_group_id` sono **un solo invio**: una sola domanda "Per quale materia?",
una scheda staff per file (crediti per file), una sola risposta all'utente.

**Rifiuto:** `❌ Rifiuta` → motivo a scelta (`Duplicato`, `Illeggibile`,
`Non pertinente`, `Altro`) → reazione 👎 e messaggio all'utente con il motivo.
Nulla entra nell'archivio; il file resta in `inbox/` 30 giorni (per eventuali
ripensamenti) e poi lo cancella il task notturno (§15).

**Invii mai moderati:** `/pending` li elenca; dopo 30 giorni in `pending` il task
notturno li segnala nel canale staff, non li cancella.

**Admin che invia un documento:** stesso flusso, ma salta i passi 6–8 e 12:
sceglie subito la cartella (anche `EXCLUSIVE/`, con prezzo) e il file viene
salvato. Nessun credito.

### 11.2 Dove va il file approvato

- La cartella la propone **l'utente** (passo 5, mai `EXCLUSIVE/`: cosa diventa
  a pagamento lo decide solo lo staff) e la conferma o cambia **l'admin**
  (`📂 Cambia cartella` apre lo stesso albero: `dsn:` per entrare nelle
  cartelle, `dst:` per "📥 Salva qui", più `➕ Nuova cartella`). Nessuno deve
  indovinare il percorso.
- I crediti si danno all'approvazione, anche se poi lo staff decide di non
  pubblicare il file: l'utente ha fatto la sua parte.
- Nome su disco: quello originale, **sanificato** (§11.4). Se esiste già un file
  con quel nome nella cartella → suffisso ` (2)`, ` (3)`… mai sovrascrivere.
- Destinazione in `EXCLUSIVE/`: il bot chiede il prezzo (`[5] [10] [20]`) e
  scrive il file come `<prezzo>.<nome>`, così la regola dei prezzi (§10.1) resta
  una sola.
- Il file è su disco ma **non ancora visibile**: compare al prossimo `/reindex`
  (bottone `🔄 Reindex ora` direttamente nella scheda). Così lo staff può
  approvare 10 file e pubblicarli tutti insieme, controllando l'anteprima.
- Il `file_id` del documento ricevuto è già valido per il bot: al `/reindex` il
  blob con quello sha256 esiste già, quindi **nessun upload** da rifare.

**Si può gestire tutto da Telegram?** Sì. Il server Bot API locale (già nel
compose, §14.2) toglie il limite di 20 MB in download: `get_file` restituisce
un percorso locale nella cartella `data/bot-api/` condivisa con il container del
bot, che **copia** il file in `inbox/` e poi lo sposta nell'archivio. La copia
in `data/bot-api/` non serve più: il task notturno svuota i file scaricati più
vecchi di 1 giorno. Senza server locale i file sopra i 20 MB non si potrebbero
salvare dal bot.

### 11.3 Gestione dell'archivio da Telegram (admin)

Per non dover mai aprire SFTP, gli admin vedono in ogni cartella una riga in più:
`[⚙️ Gestisci]` → pannello sul nodo corrente:

| Azione | Effetto su disco |
|---|---|
| ➕ Nuova cartella | `mkdir` nella cartella corrente (nome chiesto in chat) |
| ✏️ Rinomina | `rename` di file o cartella (l'ID si conserva al reindex, §6.3). Sotto `EXCLUSIVE/` l'admin scrive solo il nome: il prefisso del prezzo viene rimesso dal bot |
| 📦 Sposta | scegli la destinazione con l'albero → `rename` |
| 💰 Prezzo | solo sotto `EXCLUSIVE/`: riscrive il prefisso numerico del nome |
| 🗑 Elimina | sposta in `data/<bot>/trash/<data>/…`, **mai** cancellazione vera |
| 🔄 Reindex | lancia `/reindex` (anteprima + conferma come sempre) |

Ogni azione tocca solo il disco e scrive una riga di log con l'admin che l'ha
fatta; gli utenti vedono le modifiche solo dopo `/reindex` → ✅ Applica. Lo staff
può continuare a usare SFTP/Samba: il risultato è lo stesso.
Input testuale (nomi) con la FSM di aiogram, `MemoryStorage` basta: se il bot
si riavvia a metà, l'admin ripete l'operazione.

### 11.4 Sicurezza (i file arrivano da sconosciuti)

- **Nome file:** `os.path.basename`, via `/`, `\`, `..`, caratteri di controllo e
  `:*?"<>|`; max 120 caratteri; mai vuoto. Il percorso finale va verificato con
  `Path.resolve().is_relative_to(ARCHIVE_DIR)` prima di scrivere.
- **Estensioni ammesse** (lista in `config`): `pdf, doc, docx, ppt, pptx, xls,
  xlsx, odt, txt, md, zip, c, h, java, py, png, jpg`. Il resto → rifiuto immediato.
- **Dimensione massima:** `SUBMIT_MAX_MB` (default 200).
- **Rate limit:** max `SUBMIT_PER_DAY` invii pendenti per utente (default 10),
  contro lo spam di crediti.
- Il bot **non apre, non esegue e non estrae** mai i file ricevuti: li copia e
  basta. Gli zip restano zip.
- **Dedup in due passi, entrambi alla ricezione:** `file_unique_id` (stesso file
  già inviato) e `sha256` (stesso contenuto già nell'archivio o in un invio
  pendente, anche se caricato da un'altra persona) → `status='duplicate'`,
  "Grazie, questo file lo abbiamo già", nessun credito, nessuna scheda staff.
- Approva/Rifiuta/Gestisci: il filtro `ADMIN_IDS` vale **anche sulle callback**,
  non solo sui comandi. Chiunque altro sia nel canale staff può solo leggere.
- Doppio click su Approva: l'`UPDATE ... WHERE status='pending'` con controllo di
  `rowcount` garantisce che i crediti si assegnino una volta sola.

---

## 12. Amministrazione e broadcast

### 12.1 Admin

- **Nessuna password.** `ADMIN_IDS=11111,22222` nel `.env`.
- Router admin con filtro `admin.message.filter(F.from_user.id.in_(settings.admin_ids))`:
  per chiunque altro i comandi semplicemente non esistono.
- Comandi admin impostati con `set_my_commands(..., scope=BotCommandScopeChat(chat_id=admin_id))`:
  gli admin vedono il loro menu, gli utenti no.

| Comando | Funzione |
|---|---|
| `/stats` | utenti totali, attivi 7/30 giorni, download, top file (tabella `downloads`) |
| `/crediti_add <id\|@username> <n> [motivo]` | crediti (anche negativi) con riga in `credit_log` |
| `/vip <id\|@username> <giorni\|0\|off>` | VIP a tempo, permanente (`0`) o revoca (§10.3) |
| `/broadcast` (in risposta a un messaggio) | anteprima + conferma, poi invio |
| `/reindex` | scansiona l'archivio, mostra l'anteprima, con ✅ Applica aggiorna il bot e carica i file nuovi nel canale di archivio |
| `/pending` | invii ancora da moderare, con link alle schede nel canale staff |
| `/collega` · `/scollega` (nel gruppo) | collega il gruppo a una cartella del corso (§9.9) |

**Solo nomi nuovi**, nessun alias: `/credits`, `/givecredits`, `/givevip`,
`/sendmessage`, `/root`, `/remove`, `/exclusive`, `/donation`, `/info` spariscono.
Le loro funzioni sono coperte da `/crediti`, `/crediti_add`, `/vip`,
`/broadcast`, `ADMIN_IDS`, `/help` (Exclusive, donazioni, info). Il menu comandi
(`setMyCommands`) mostra i nuovi nomi; un vecchio comando digitato risponde con
`/help`. `/remove` non serve: gli utenti non si cancellano, si marcano `blocked`.

Concorrenza: **un solo `/reindex` alla volta** (un `asyncio.Lock`). Se un altro
admin lo lancia mentre è in corso: "Reindex già in corso da @admin". Il lock si
libera ad Applica, Annulla o alla scadenza dell'anteprima (10 minuti, §6.3). Anche
l'upload in background nel canale è riprendibile: si caricano i blob senza
`storage_message_id`, quindi dopo un riavvio basta un nuovo `/reindex`.

### 12.2 Broadcast corretto

- Si risponde con `/broadcast` al messaggio da inviare → il bot fa
  `copy_message` (mantiene formattazione, foto, documenti).
- Gira come **task in background** (`asyncio.create_task`): il bot resta reattivo.
- **Ritmo controllato:** ~25 messaggi al secondo (`asyncio.sleep(0.04)` tra un
  invio e l'altro), sotto il limite di ~30/s. Su `TelegramRetryAfter` si aspetta
  `e.retry_after` secondi e si riprova lo stesso utente.
- `TelegramForbiddenError` (utente ha bloccato il bot) → `users.blocked = 1`.
  **Mai cancellare utenti** per un errore di rete.
- Un messaggio di progresso editato ogni 100 invii: "Inviati 300/737 · bloccati 12".
- Destinatari: utenti con `blocked = 0`. Gli utenti mai passati da una chat
  privata (solo inline o gruppi) falliscono con `Forbidden` e vengono marcati
  `blocked`: è il comportamento corretto.

### 12.3 Feedback, segnalazioni, rimozioni (ticket)

Un solo meccanismo per `/feedback`, `⚠️ Segnala` e `/rimozione` (§12.4):

1. Il bot crea una riga in `tickets` e pubblica nel canale staff una scheda
   (`🗨 Feedback` / `⚠️ Segnalazione: <percorso>` / `🚫 Richiesta rimozione`),
   con l'utente e il bottone `[✅ Chiudi]` (`tk:<id>:ok`).
2. Un admin **risponde con una reply** alla scheda nel canale staff: il bot
   copia la risposta all'utente ("💬 Risposta dello staff: …"). Più risposte
   sono possibili finché il ticket è aperto. La reply si collega al ticket
   tramite `staff_message_id`.
3. `✅ Chiudi` → scheda editata "Chiuso da @admin", l'utente non riceve altro.
   Le reply a un ticket chiuso vengono ignorate con un toast all'admin.

Reply di chi non è in `ADMIN_IDS`: ignorate.

### 12.4 Privacy e richieste di rimozione

- **`/privacy`:** cosa salva il bot e perché, in poche righe: ID Telegram,
  nome e username (per crediti e acquisti), download (12 mesi, per `/recenti`
  e statistiche), file inviati (finché approvati o 30 giorni se rifiutati),
  ticket. Niente altro, niente terze parti. Come chiedere la cancellazione dei
  propri dati: `/feedback`. Lo stesso testo va impostato come privacy policy
  del bot su @BotFather.
- **`/rimozione`:** chi detiene i diritti di un materiale (o chi l'ha inviato)
  apre un ticket `removal` indicando il file (link `f_…` o nome). Lo staff
  valuta e, se va rimosso, usa `🗑 Elimina` (§11.3) + `/reindex`: il file va nel
  cestino e sparisce dal bot. Il messaggio nel canale storage resta ma non è
  raggiungibile da nessun utente (§7.3).
- **Conservazione:** il task notturno (§15) cancella le righe di `downloads`
  più vecchie di 12 mesi; `users.downloads` mantiene solo il totale.

---

## 13. Configurazione e segreti

### 13.1 Cosa sta nel repo e cosa no

| Nel repo | Fuori dal repo (`data/` o `.env`) |
|---|---|
| codice, `Dockerfile`, `compose.yaml` | token del bot |
| `.env.example` con valori finti e commenti | ID canali e admin |
| README con istruzioni | database |
| test | archivio materiale |
| | media di benvenuto (`data/<bot>/media/welcome.mp4`) |
| | planning interno (`docs/tasks/`), file di editor e strumenti (`.idea/`, `.claude/`) |

**Struttura di `data/` versionata, contenuto mai.** Ogni cartella di `data/`
contiene un `.gitignore` che ignora tutto tranne sé stesso:

```gitignore
*
!.gitignore
!*/
```

Così chi clona il progetto trova già `data/prod/archive/`, `inbox/`, `trash/`,
`media/`, `backups/`, `data/beta/…` e `data/bot-api/`, ma nessun file di dati può
finire su git per sbaglio. Il `.gitignore` della radice copre il resto (Python,
`.env*` tranne `.env.example`, `*.db`, editor, `.claude/`, `docs/tasks/`).

### 13.2 Cartella `data/`: tutto dentro il progetto

Niente volumi Docker con nome, niente percorsi assoluti: **tutto lo stato vive in
`./data/` dentro la cartella del progetto** (ignorata da git). Si vede con un
normale file manager, si copia con `rsync`, si fa backup di una cartella sola.

```
UnivrArchive/
└── data/                    ⚠ in .gitignore
    ├── prod/                bot di produzione  → montata come /data nel container
    │   ├── archive/         materiale (quello che lo staff gestisce)
    │   ├── inbox/           file inviati dagli utenti in attesa di moderazione (§11.1)
    │   ├── trash/           file eliminati da ⚙️ Gestisci (§11.3)
    │   ├── media/           gif/video di benvenuto
    │   ├── backups/         backup notturni del DB
    │   └── bot.db           database
    ├── beta/                bot di test (opzionale), stessa struttura, isolato
    └── bot-api/             server Bot API locale, condiviso da tutti i bot
```

Prod e beta **non condividono niente** tranne il server Bot API: DB, archivio e
canali separati. Così un test non tocca mai crediti, acquisti o canale storage
di produzione. Per provare beta con dati veri:
`rsync -a data/prod/archive/ data/beta/archive/`.

Dentro il container i percorsi sono **fissi** (`/data/archive`, `/data/bot.db`,
…): non stanno nel `.env`, così nessuno li sbaglia.

### 13.3 `.env.example`

Un solo file `.env` per tutto il progetto. Contiene **solo** segreti e scelte
dello staff; ogni variabile ha un commento. Il compose passa a ogni container
solo le variabili che gli servono (il bot di prod non vede il token beta e
viceversa).

```dotenv
# ═══ UniVrArchive — configurazione ═══════════════════════════════════════
# Copia questo file in .env e compila. Il file .env NON va mai su git.
# Obbligatorie: quelle senza "(opzionale)". Se ne manca una, `docker compose`
# si ferma subito dicendo quale.

# ─── Token dei bot (da @BotFather) ───────────────────────────────────────
# Bot di produzione.
BOT_TOKEN=
# (opzionale) Bot di test, si avvia solo con: docker compose --profile beta up -d
BETA_BOT_TOKEN=

# ─── Admin ───────────────────────────────────────────────────────────────
# ID numerici Telegram separati da virgola (scoprili con @userinfobot).
# Valgono per entrambi i bot.
ADMIN_IDS=

# ─── Chat del bot di produzione (il bot deve esserne admin, ID tipo -100…) ─
# Gruppo/canale staff: riceve materiale da moderare, segnalazioni e feedback.
STAFF_CHAT_ID=
# Canale privato dove il bot deposita una copia di ogni file. Mai mostrato agli utenti.
STORAGE_CHAT_ID=
# (opzionale) Chat dove arrivano gli errori del bot.
LOG_CHAT_ID=

# ─── (opzionale) Chat del bot beta: canali propri, mai quelli di produzione ─
BETA_STAFF_CHAT_ID=
BETA_STORAGE_CHAT_ID=

# ─── Server Bot API locale (file fino a 2 GB) ────────────────────────────
# Da https://my.telegram.org → API development tools. Uno solo per tutti i bot.
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# ─── Regole (i valori qui sotto sono i default) ──────────────────────────
# Prezzo massimo di un file Exclusive: oltre, il file resta nascosto (§10.1).
PRICE_MAX=50
# Dimensione massima di un file inviato dagli utenti, in MB.
SUBMIT_MAX_MB=200
# Invii in attesa di moderazione per utente al giorno.
SUBMIT_PER_DAY=10
# (opzionale) Link esterno per le donazioni, mostrato in /start e /help.
DONATION_LINK=
# Rich messages sperimentali (§9.5): 0 = spenti, 1 = accesi.
RICH_MESSAGES=0
# DEBUG, INFO, WARNING
LOG_LEVEL=INFO
```

Al posto di `ACTIVE_MODE` + `TOKEN`/`BETA_TOKEN`/`DEPLOY_TOKEN` + `ROOT_PASSWORD`
del vecchio bot: **un token per bot**, ognuno nel suo container, e gli admin per
ID. Niente modalità da cambiare a mano.

### 13.4 `config.py`

Il container riceve sempre gli stessi nomi (`BOT_TOKEN`, `STAFF_CHAT_ID`, …):
è il compose che mappa `BETA_BOT_TOKEN` → `BOT_TOKEN` per il bot beta. Il codice
non sa se è prod o beta.

```python
import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("BOT_TOKEN", "ADMIN_IDS", "STAFF_CHAT_ID", "STORAGE_CHAT_ID")

@dataclass(frozen=True)
class Settings:
    token: str
    admin_ids: frozenset[int]
    staff_chat_id: int
    storage_chat_id: int
    log_chat_id: int | None
    bot_api_url: str
    data_dir: Path
    price_max: int
    submit_max_mb: int
    submit_per_day: int
    donation_link: str
    rich_messages: bool
    log_level: str

    # percorsi derivati: un solo valore da configurare (DATA_DIR)
    @property
    def archive_dir(self): return self.data_dir / "archive"
    @property
    def trash_dir(self):   return self.data_dir / "trash"
    @property
    def media_dir(self):   return self.data_dir / "media"
    @property
    def db_path(self):     return self.data_dir / "bot.db"

def load() -> Settings:
    env = os.environ
    if missing := [k for k in REQUIRED if not env.get(k)]:
        raise SystemExit(f"Configurazione incompleta, mancano: {', '.join(missing)} "
                         f"(vedi .env.example)")
    def opt_int(k): return int(env[k]) if env.get(k) else None
    return Settings(
        token=env["BOT_TOKEN"],
        admin_ids=frozenset(int(x) for x in env["ADMIN_IDS"].split(",") if x.strip()),
        staff_chat_id=int(env["STAFF_CHAT_ID"]),
        storage_chat_id=int(env["STORAGE_CHAT_ID"]),
        log_chat_id=opt_int("LOG_CHAT_ID"),
        # in Docker non si toccano; senza Docker si sovrascrivono nell'ambiente
        bot_api_url=env.get("BOT_API_URL", "http://telegram-bot-api:8081"),
        data_dir=Path(env.get("DATA_DIR", "/data")),
        price_max=int(env.get("PRICE_MAX") or 50),
        submit_max_mb=int(env.get("SUBMIT_MAX_MB") or 200),
        submit_per_day=int(env.get("SUBMIT_PER_DAY") or 10),
        donation_link=env.get("DONATION_LINK", ""),
        rich_messages=env.get("RICH_MESSAGES") == "1",
        log_level=env.get("LOG_LEVEL") or "INFO",
    )
```

Un errore di configurazione ferma il bot all'avvio con **tutti** i nomi mancanti
in una riga, non al primo click di un utente. Se il bot beta viene avviato con
`BETA_BOT_TOKEN` vuoto: "Configurazione incompleta, mancano: BOT_TOKEN".

### 13.5 Protezione extra

- Abilitare **GitHub secret scanning / push protection** sul repo.
- Un hook `pre-commit` con `gitleaks` (opzionale) blocca commit con token:

  ```yaml
  # .pre-commit-config.yaml  (pre-commit 4.7.0)
  repos:
    - repo: https://github.com/gitleaks/gitleaks
      rev: v8.30.1
      hooks:
        - id: gitleaks
  ```
- Il vecchio `.env` con `ROOT_PASSWORD` e token: **rigenerare i token** da
  @BotFather (`/revoke`) se sono mai finiti in un commit.

---

## 14. Deploy

### 14.1 Polling o webhook?

Su un Raspberry dietro NAT di casa/università: **long polling**. Nessuna porta
aperta, nessun certificato, latenza praticamente identica per un bot di queste
dimensioni. Il webhook ha senso solo con un server pubblico HTTPS.

### 14.2 Docker (consigliato)

`Dockerfile`:

```dockerfile
FROM python:3.14.10-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot/ bot/
CMD ["python", "-m", "bot"]
```

L'utente non è fissato nell'immagine: lo decide il compose (`user:`), uguale a
quello dell'host, così i file creati in `./data` (DB, file approvati) restano
dell'utente che gestisce il Raspberry e si aprono senza `sudo`.

`compose.yaml` (verificato con `docker compose config`, Compose v5):

```yaml
# Tutto punta a ./data dentro la cartella del progetto: niente volumi nascosti di Docker.
x-bot: &bot
  build: .
  user: "${UID:-1000}:${GID:-1000}"          # stesso utente dell'host: i file in ./data restano tuoi
  depends_on: [telegram-bot-api]
  restart: unless-stopped
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }   # log ruotati

services:
  bot:
    <<: *bot
    environment:
      BOT_TOKEN: ${BOT_TOKEN:?manca BOT_TOKEN nel file .env}
      ADMIN_IDS: ${ADMIN_IDS:?manca ADMIN_IDS nel file .env}
      STAFF_CHAT_ID: ${STAFF_CHAT_ID:?manca STAFF_CHAT_ID nel file .env}
      STORAGE_CHAT_ID: ${STORAGE_CHAT_ID:?manca STORAGE_CHAT_ID nel file .env}
      LOG_CHAT_ID: ${LOG_CHAT_ID:-}
      PRICE_MAX: ${PRICE_MAX:-50}
      SUBMIT_MAX_MB: ${SUBMIT_MAX_MB:-200}
      SUBMIT_PER_DAY: ${SUBMIT_PER_DAY:-10}
      DONATION_LINK: ${DONATION_LINK:-}
      RICH_MESSAGES: ${RICH_MESSAGES:-0}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    volumes:
      - ./data/prod:/data
      - ./data/bot-api:/var/lib/telegram-bot-api:ro   # file scaricati dal server locale (§11.2)

  bot-beta:                                    # solo con: docker compose --profile beta up -d
    <<: *bot
    profiles: [beta]
    environment:
      BOT_TOKEN: ${BETA_BOT_TOKEN:-}           # vuoto → il bot si ferma con errore chiaro
      ADMIN_IDS: ${ADMIN_IDS:?manca ADMIN_IDS nel file .env}
      STAFF_CHAT_ID: ${BETA_STAFF_CHAT_ID:-}
      STORAGE_CHAT_ID: ${BETA_STORAGE_CHAT_ID:-}
      LOG_CHAT_ID: ${LOG_CHAT_ID:-}
      PRICE_MAX: ${PRICE_MAX:-50}
      SUBMIT_MAX_MB: ${SUBMIT_MAX_MB:-200}
      SUBMIT_PER_DAY: ${SUBMIT_PER_DAY:-10}
      DONATION_LINK: ${DONATION_LINK:-}
      RICH_MESSAGES: ${RICH_MESSAGES:-0}
      LOG_LEVEL: DEBUG
    volumes:
      - ./data/beta:/data
      - ./data/bot-api:/var/lib/telegram-bot-api:ro

  telegram-bot-api:                            # server Bot API locale: file fino a 2 GB, serve tutti i bot
    image: aiogram/telegram-bot-api:10.3       # versione fissata (multi-arch, anche arm64): aggiornare a mano
    environment:
      TELEGRAM_API_ID: ${TELEGRAM_API_ID:?manca TELEGRAM_API_ID nel file .env}
      TELEGRAM_API_HASH: ${TELEGRAM_API_HASH:?manca TELEGRAM_API_HASH nel file .env}
      TELEGRAM_LOCAL: "1"
    volumes:
      - ./data/bot-api:/var/lib/telegram-bot-api
    restart: unless-stopped
    # nessuna porta pubblicata: lo raggiungono solo i bot, sulla rete interna di compose

  bot-api-cleaner:                             # cancella i file scaricati dal server dopo 1 giorno
    image: alpine:3.24.4                       # (il bot li ha già copiati in inbox/, §11.2)
    user: "101:101"                            # stesso utente del server Bot API: solo lui può cancellare i suoi file;
                                               # i bot montano data/bot-api in sola lettura
    volumes:
      - ./data/bot-api:/var/lib/telegram-bot-api
    command: ["sh", "-c", "while true; do find /var/lib/telegram-bot-api -path '*/documents/*' -type f -mmin +1440 -delete; sleep 3600; done"]
    restart: unless-stopped
```

**Perché un container a parte per la pulizia:** il server Bot API gira come
utente `101` e diventa proprietario di `data/bot-api/`. Il bot (utente `1000`)
può leggere quei file ma non cancellarli. Invece di dare al bot permessi di
scrittura sui file del server, un container minimo (Alpine) con lo stesso utente
del server cancella i documenti scaricati più vecchi di 24 ore.

`.dockerignore`: l'immagine contiene solo `bot/` e `requirements.txt`. Senza,
`docker build` invierebbe al daemon anche `data/` (gigabyte).

Cosa è stato verificato:

- senza `.env` → `docker compose` si ferma con
  `required variable BOT_TOKEN is missing a value: manca BOT_TOKEN nel file .env`;
- con le sole variabili obbligatorie partono `bot` + `telegram-bot-api`; il beta
  non parte e non richiede variabili finché non si usa `--profile beta`;
- il container `bot` riceve solo le sue variabili: niente token beta, niente
  `TELEGRAM_API_HASH`;
- il tag `aiogram/telegram-bot-api:10.3` esiste ed è multi-arch (`linux/arm64` compreso).

Da verificare al primo avvio reale: che i file scritti dal server Bot API in
`data/bot-api/` siano leggibili dall'utente del bot (permessi `644`); se non lo
sono, si allinea l'utente dei due container.

Avvio per chiunque cloni il progetto:

```bash
git clone https://github.com/kodikasgroup/UnivrArchive.git && cd UnivrArchive
cp .env.example .env                  # compilare token, admin, chat, api_id/hash
mkdir -p data/prod/archive data/bot-api
rsync -a /percorso/vecchio/archive/ data/prod/archive/   # -a conserva le date (§6.3)
docker compose up -d --build
docker compose logs -f bot
```

Bot di test, quando serve:

```bash
mkdir -p data/beta/archive
docker compose --profile beta up -d --build
```

**Una tantum, prima del primo avvio con il server locale:** ogni bot va
"scollegato" dal server cloud di Telegram chiamando `logOut`, altrimenti non è
garantito che riceva gli update dal server locale:

```bash
curl "https://api.telegram.org/bot<TOKEN>/logOut"
```

(Va rifatto solo se un giorno si torna al cloud e poi di nuovo al locale.)

Immagine per Raspberry: `python:3.14.10-slim-trixie` è multi-arch, quindi
`docker compose build` funziona direttamente sul Pi (arm64). Per non compilare
sul Pi: una GitHub Action costruisce l'immagine per arm64 e amd64 e la pubblica
su GHCR, il Pi fa solo `docker compose pull && docker compose up -d`
(nel compose `image: ghcr.io/kodikasgroup/univrarchive:<tag>` al posto di `build: .`).

```yaml
# .github/workflows/docker.yml — versioni più recenti al 6/11/2026 (§4.1)
name: docker
on:
  push:
    tags: ["v*"]
permissions:
  contents: read
  packages: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-qemu-action@v4
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ github.repository }}
      - uses: docker/build-push-action@v7
        with:
          platforms: linux/arm64,linux/amd64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

Si pubblica solo sui tag `v*` (release), non a ogni push: sul Pi si installa
sempre una versione precisa.

### 14.3 Raspberry senza Docker (systemd)

Possibile ma sconsigliato: il server Bot API locale va compilato a mano
(`tdlib/telegram-bot-api`, C++, lungo su un Pi) o avviato comunque come
container. Stessi nomi di variabili; in più `DATA_DIR` e `BOT_API_URL`, che in
Docker sono fissi:

```ini
# /etc/systemd/system/univrarchive.service
[Unit]
Description=UniVrArchive bot
After=network-online.target
Wants=network-online.target

[Service]
User=bot
WorkingDirectory=/opt/univrarchive
EnvironmentFile=/opt/univrarchive/.env
Environment=DATA_DIR=/opt/univrarchive/data/prod
Environment=BOT_API_URL=http://127.0.0.1:8081
ExecStart=/opt/univrarchive/.venv/bin/python -m bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Python 3.14 va installato a parte: trixie include la 3.13 di sistema
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo systemctl enable --now univrarchive
journalctl -u univrarchive -f
```

**Raccomandazione:** Docker Compose. Stessa procedura su Pi, PC dello sviluppatore
e qualsiasi VPS; è il modo più semplice per un progetto open source "clona e avvia".

### 14.4 Note specifiche Raspberry

- Raspberry Pi OS **64 bit**, base Debian 13 "trixie" (la stessa dell'immagine Docker).
- `data/` su **SSD USB**, non su microSD.
- RAM richiesta dal bot: ~60–100 MB. Va bene anche un Pi 3/4 con 1 GB.
- Upload di file grandi: la velocità è quella della connessione in upload del
  Pi. Ogni file si carica nel canale di archivio una volta sola (§7.3).

---

## 15. Logging, backup, monitoraggio

- **Logging:** `logging.basicConfig(level=LOG_LEVEL)` su stdout, livello INFO.
  Abbassare il logger `aiogram.event` a WARNING (altrimenti logga ogni update ricevuto).
- **Errori:** error handler globale (`@router.errors()`) → log + messaggio in `LOG_CHAT_ID`.
- **Task notturno nel bot** (alle 03:00 UTC, cioè 04:00/05:00 in Italia; un solo task asyncio, nessun cron
  sull'host, niente da installare sul Pi):
  1. **backup DB** senza fermare il bot: `VACUUM INTO
     '/data/backups/bot-<data>.db'`; si tengono gli ultimi 14;
  2. **cestino:** cancella da `trash/` le cartelle più vecchie di 30 giorni;
  3. **inbox:** cancella i file degli invii `rejected`/`duplicate` più vecchi di
     30 giorni; segnala nel canale staff gli invii `pending` da oltre 30 giorni;
  4. **invii orfani:** gli invii rimasti `pending` senza scheda nel gruppo staff
     (riavvio durante la scelta della materia, scheda non pubblicata) vengono
     ripubblicati, o chiusi se il file non c'è più (lo stesso controllo gira
     all'avvio);
  5. **privacy:** cancella le righe di `downloads` più vecchie di 12 mesi (§12.4);
  6. **albero in RAM:** ricostruito dal DB, così il badge 🆕 scade (§6.3).

  I file scaricati dal server Bot API in `data/bot-api/` **non** li pulisce il
  bot (non ne ha i permessi): ci pensa il servizio `bot-api-cleaner` (§14.2).

  Se il bot era spento a quell'ora, il task parte all'avvio se l'ultimo giro
  (salvato in `kv`) ha più di 24 ore.
- **Ripristino del DB** (da scrivere nel README):
  ```bash
  docker compose stop bot
  cp data/prod/backups/bot-AAAA-MM-GG.db data/prod/bot.db
  rm -f data/prod/bot.db-wal data/prod/bot.db-shm
  docker compose start bot
  ```
  Dopo il ripristino si lancia `/reindex`: l'archivio su disco è sempre la
  fonte di verità per l'albero.
- **Backup archivio:** `rsync -a data/ /mnt/backup/univrarchive/` su un altro
  disco/NAS (cron sull'host, l'unica cosa fuori dal bot: il bot non deve
  conoscere dischi esterni). Il canale storage Telegram è un ulteriore backup
  gratuito, ma non sostituisce questo.
- **Health:** opzionale, comando `/ping` admin o un job che aggiorna un file
  heartbeat usato dall'`healthcheck` Docker.

---

## 16. Limiti della Bot API

| Limite | Valore | Impatto |
|---|---|---|
| `callback_data` | 64 byte | ID interi corti (§6.4) |
| Upload file (Bot API cloud) | 50 MB | 32 file dell'archivio reale lo superano → **local Bot API server, incluso nel compose** (§14.2): fino a 2 GB |
| Download file dal bot (`getFile`) | 20 MB (cloud) | col server locale nessun limite: i file inviati dagli utenti si salvano tutti (§11) |
| Messaggi | ~30/s globali, ~1/s per chat, 20/min per gruppo | broadcast a ~25/s con gestione di `TelegramRetryAfter` |
| Testo messaggio | 4096 caratteri | |
| Caption | 1024 caratteri | `/start` con testo breve |
| `?start=` dei deep link | max 64 caratteri, solo `A-Z a-z 0-9 _ -` | query di ricerca codificata in base64url (§9.8) |
| Messaggi nella stessa chat privata | ~1/s | "Scarica tutto" in sequenza a ~1 file/s (§9.4) |
| `file_id` | valido solo per il bot che l'ha ricevuto | un DB per bot |

---

## 17. Piano di migrazione

**Passo 1 — Scheletro.** `requirements.txt` con le versioni di §4.1,
`config.py`, `.env.example`, `Dockerfile`, `compose.yaml`, `__main__.py` con
aiogram 3.31 e `/start` funzionante.

**Passo 2 — Archivio + navigazione.** `archive.py` (scansione, ID stabili,
prezzi, ordinamento), `keyboards.py` (paginazione, breadcrumb), handler unico
`n:`. Test su `archive.py`.

**Passo 3 — File e cache.** Invio con `file_id` persistente, media di benvenuto
cachato, `protect_content` per i file a pagamento, canale di archivio con
`blobs` (`file_id` + `storage_message_id`), `/reindex` con anteprima.

**Passo 4 — Migrazione dati.** Script una tantum che legge il vecchio DB e
popola `users`:

```sql
ATTACH 'old/UserLogDB.db' AS old;
INSERT OR IGNORE INTO users (id, username, first_name, last_seen)
    SELECT chat_id, username, f_name, state FROM old.User;
-- utenti che esistono solo in Reserved o Download (righe mancanti in User):
-- senza queste due righe perderebbero crediti e VIP
INSERT OR IGNORE INTO users (id) SELECT DISTINCT chat_id FROM old.Reserved;
INSERT OR IGNORE INTO users (id) SELECT DISTINCT chat_id FROM old.Download;
UPDATE users SET
    credits   = COALESCE((SELECT MAX(Credit) FROM old.Reserved r WHERE r.chat_id = users.id), 0),
    vip_until = CASE WHEN (SELECT MAX(Vip) FROM old.Reserved r WHERE r.chat_id = users.id) = 1
                     THEN '9999-12-31' END,          -- i vecchi VIP restano permanenti
    downloads = COALESCE((SELECT SUM(n_download) FROM old.Download d WHERE d.chat_id = users.id), 0);
DETACH old;
```

`old.User.state` è già nel formato giusto: `DbHandler.update_state` scrive
`datetime.now()` senza microsecondi, che sqlite salva come testo
`'YYYY-MM-DD HH:MM:SS'`, lo stesso formato di `datetime('now')`. Unica
differenza: il vecchio valore è in ora locale, il nuovo in UTC (±2 ore,
irrilevante per "attivi 7/30 giorni").

(Il vecchio DB può avere più righe per lo stesso `chat_id` perché non aveva
chiavi primarie: per questo `INSERT OR IGNORE`, `MAX` e `SUM`. Verificare a mano
qualche riga prima di passare in produzione.)

Archivio: **nessuna modifica**. Si copia la cartella attuale in
`data/prod/archive/` (es. `rsync -a archive/ data/prod/archive/`), si avvia il bot e si
controlla il log dello `/reindex`: numero di nodi, file Exclusive senza prezzo,
file oltre i 50 MB. Poi si confronta a campione la navigazione col bot vecchio.

**Passo 5 — Crediti, acquisti, VIP** (`vip_until`, nessun pagamento).

**Passo 6 — Invio materiale con moderazione a bottoni**, salvataggio su disco e
gestione archivio da Telegram (§11).

**Passo 7 — Admin, broadcast in background, stats.**

**Passo 8 — Ricerca inline e deep link.**

**Passo 8b — Preferiti, recenti, novità, Segnala, Scarica tutto.**

**Passo 8c — Gruppi dei corsi (`/materiale` effimero), poi rich messages e topic
dietro opzione, provati sul bot BETA.**

**Passo 9 — Messa in produzione (cutover).**

Prima, sul **bot beta** (token beta, `data/beta/`, canali beta): DB migrato da
una copia del vecchio DB e archivio copiato con `rsync -a`. Si prova tutto lì.
Il beta non condivide nulla con prod, quindi i suoi `file_id` non servono in
produzione.

Poi il passaggio vero, con il **token di produzione** (lo stesso del vecchio bot,
così gli utenti non devono cambiare nulla):

1. **In anticipo** (giorni prima): `data/prod/` pronto, archivio copiato,
   `.env` compilato. Primo `/reindex` impossibile finché il nuovo bot non è
   avviato, quindi si mette in conto ~1,5 ore di caricamento nel canale
   dopo l'avvio (§7.3); nel frattempo i file partono al primo click.
2. Avviso agli utenti con il vecchio bot: "manutenzione di 30 minuti".
3. Fermare il vecchio bot (due processi in polling con lo stesso token vanno in
   conflitto).
4. Copia **finale** del vecchio DB e migrazione (passo 4): così crediti e VIP
   sono quelli dell'ultimo minuto.
5. `logOut` del token dal cloud (§14.2). **Attenzione:** dopo `logOut` Telegram
   non accetta lo stesso token sul server cloud per 10 minuti; tornare indietro
   al vecchio bot richiede quindi almeno 10 minuti.
6. `docker compose up -d`, poi `/reindex` → ✅ Applica.
7. Controllo a campione: navigazione, un download, un acquisto, un invio.

**Rollback:** fermare il nuovo bot, aspettare i 10 minuti dal `logOut`, riavviare
il vecchio con il vecchio DB (non toccato: la migrazione legge da una copia).
Crediti e acquisti fatti nel frattempo sul nuovo bot vanno riportati a mano.

Il vecchio codice resta nel tag `v1` per riferimento.

---

## 18. Checklist finale

- [ ] Repo senza DB, zip, `.idea`, segreti — anche nella storia
- [ ] Versioni dipendenze fissate, una sola dipendenza diretta
- [ ] `.env.example` completo e commentato; il bot fallisce all'avvio con messaggio chiaro se manca una variabile
- [ ] Tutto lo stato in `./data/` del progetto (prod, beta, bot-api), su SSD; nessun volume Docker con nome
- [ ] `.env` unico e commentato: un token per bot, il compose passa a ogni container solo le sue variabili
- [ ] `logOut` dal cloud una volta per bot prima di usare il server Bot API locale
- [ ] Archivio indicizzato una volta; nessun `os.listdir` per click
- [ ] ID nodo stabili su DB; bottoni validi dopo riavvio
- [ ] Canale di archivio: ogni contenuto caricato una sola volta, `file_id` e `storage_message_id` su DB
- [ ] `/reindex` solo manuale, con anteprima e conferma
- [ ] `answer_callback_query` su ogni callback
- [ ] Navigazione con `edit_message_text`, breadcrumb, paginazione, ordinamento naturale
- [ ] Acquisti atomici, tabella `purchases`, `credit_log`
- [ ] Nessun pagamento nel bot; VIP con `vip_until`; correzioni solo manuali
- [ ] Invii utenti: approvazione → cartella → file su disco, tutto da Telegram; nomi sanificati
- [ ] Spostamenti/rinomine riconosciuti via sha256: ID, preferiti e deep link conservati
- [ ] Nessuna traccia del canale storage nei file consegnati (`remove_caption`, mai forward)
- [ ] Ogni callback ricontrolla permessi, saldo e prezzo lato server
- [ ] Utente registrato su ogni update (middleware), non solo su `/start`
- [ ] Invii: download e sha256 alla ricezione, `inbox/`, album come un solo invio
- [ ] Ticket (feedback, segnalazioni, rimozioni) con risposta via reply nel canale staff
- [ ] Gruppi: risposta solo nei gruppi collegati con `/collega`
- [ ] Task notturno: backup DB, pulizia trash/inbox/bot-api, downloads > 12 mesi, rebuild albero
- [ ] `/privacy` e `/rimozione`; privacy policy impostata su @BotFather
- [ ] Cutover con `logOut` e piano di rollback provati sul beta
- [ ] Azioni sui file: Condividi (inline), Copia link (`copy_text`), Preferiti, Segnala
- [ ] "Scarica tutto": solo file diretti, ordine archivio, invio in sequenza in background
- [ ] Bottoni colorati (`style`) e disabilitati (`disabled`) dove servono
- [ ] Rich messages e topic privati solo dietro opzione, provati su Android/iOS/Desktop
- [ ] Comando effimero `/materiale` per i gruppi dei corsi
- [ ] Admin via `ADMIN_IDS`, niente password
- [ ] Broadcast in background con rate limiter; utenti bloccati marcati, non cancellati
- [ ] SQL solo parametrizzato
- [ ] WAL, `synchronous=NORMAL`, scritture minime
- [ ] Log INFO su stdout con rotazione; error handler globale
- [ ] Backup notturno DB
- [ ] Test minimi su scansione archivio, parsing prezzi, acquisto
