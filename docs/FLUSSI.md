# Come funziona — flussi e diagrammi

Spiegazione del funzionamento del bot, flusso per flusso. I diagrammi sono in
Mermaid (GitHub li mostra come grafici). Qui solo il "cosa succede": per i
comandi dello staff vedi [`GUIDA_ADMIN.md`](GUIDA_ADMIN.md), per il codice
[`SVILUPPO.md`](SVILUPPO.md).

---

## 1. Visione d'insieme

```mermaid
flowchart LR
    U["👤 Utenti<br/>chat privata, inline, gruppi"]
    S["👥 Gruppo staff<br/>moderazione, ticket"]
    subgraph PI["Raspberry Pi (docker compose)"]
        B["🤖 Bot<br/>aiogram"]
        API["Server Bot API locale (opzionale)<br/>file fino a 2 GB"]
        subgraph DATA["./data/prod"]
            AR[("archive/<br/>i file")]
            IN[("inbox/<br/>invii in attesa")]
            DB[("bot.db<br/>SQLite")]
        end
    end
    T["☁️ Telegram"]
    ST["🔒 Canale storage<br/>privato"]

    U <--> T
    S <--> T
    T <--> API
    API <--> B
    B --> DB
    B -- "/reindex legge" --> AR
    B -- "invii" --> IN
    IN -- "approvato" --> AR
    B -- "carica 1 volta" --> ST
    ST -. "file_id" .-> B
```

Tre idee alla base:

1. **Il disco decide cosa si vede.** Lo staff gestisce le cartelle in
   `data/prod/archive/`; il bot le pubblica solo con `/reindex`.
2. **Telegram consegna i file.** Ogni file viene caricato una volta nel canale
   storage; agli utenti si invia il suo `file_id`, istantaneo.
3. **Il DB ricorda le persone.** Crediti, acquisti, preferiti, invii, ticket.

---

## 2. Navigare e scaricare

```mermaid
sequenceDiagram
    actor U as Utente
    participant B as Bot
    participant R as Albero in RAM
    participant DB as DB
    participant T as Telegram

    U->>B: /start
    B->>T: animazione + menu corsi (1 messaggio)
    U->>B: click cartella (n:142)
    B->>R: figli di 142 (già pronti)
    B->>T: answerCallbackQuery + editMessageText
    Note over B,T: un solo messaggio che cambia,<br/>il disco non viene mai letto
    U->>B: click file gratuito (n:571)
    B->>DB: file_id per sha256
    alt file_id presente
        B->>T: sendDocument(file_id)
        B->>DB: download registrato
    else non ancora nel canale storage
        B->>U: "⏳ lo sto preparando, te lo mando appena pronto"
        Note over B: il file passa in testa al caricamento<br/>in background (l'unico che legge il disco)
        B->>T: carica nel canale storage (una volta)
        B->>T: sendDocument(file_id) all'utente
        B->>DB: download registrato
    end
```

**Il percorso utente non legge mai il disco:** navigazione, ricerca e invii
usano solo l'indice (database, caricato in memoria) e i `file_id` di Telegram.
Il disco lo leggono solo `/reindex` e il caricamento in background nel canale
storage. Un file appena pubblicato e non ancora caricato passa in testa alla
coda e arriva da solo appena pronto (succede soprattutto nelle ore dopo il
primo `/reindex`).

Sotto ogni file: **📤 Condividi** (via inline), **🔗 Copia link**,
**⭐ Salva** nei preferiti, **⚠️ Segnala**.

**📥 Scarica tutto:** manda tutti i file gratuiti della cartella (non delle
sottocartelle), nell'ordine dei bottoni, circa uno al secondo. Sopra i 20 file
chiede conferma.

**Altri modi di arrivare a un file:** ricerca inline `@bot analisi` in qualsiasi
chat, `/cerca analisi`, link `t.me/<bot>?start=f_571`, `/preferiti`,
`/recenti`, `/novita`.

---

## 3. Comprare un file Exclusive

```mermaid
flowchart TD
    A["Click su file Exclusive"] --> B{"VIP o già<br/>comprato?"}
    B -- sì --> OK["Invio protetto<br/>(non inoltrabile)"]
    B -- no --> C["Scheda: costo, saldo<br/>[Acquista] [Annulla]"]
    C --> D{"Saldo<br/>sufficiente?"}
    D -- no --> E["Acquista disabilitato<br/>+ 'Come ottenere crediti'"]
    D -- sì --> F["Click Acquista"]
    F --> G["Transazione:<br/>−crediti, acquisto, log"]
    G --> OK2["Invio protetto + 🎉"]
```

- I crediti **non si comprano**: si guadagnano inviando materiale approvato
  ([§4](#4-inviare-materiale-e-guadagnare-crediti)) o li assegna un admin.
- L'acquisto resta valido se il file viene corretto, rinominato, spostato o
  cambia prezzo.
- Se l'invio fallisce dopo l'acquisto, basta ricliccare: niente doppio addebito.

---

## 4. Inviare materiale (e guadagnare crediti)

```mermaid
sequenceDiagram
    actor U as Utente
    participant B as Bot
    participant I as inbox/
    participant S as Gruppo staff
    actor A as Admin

    U->>B: manda un documento (o un album)
    B->>B: controlli: estensione, dimensione, limite giornaliero
    B->>I: scarica + sha256
    alt già nell'archivio
        B->>U: "Grazie, questo file lo abbiamo già"
    else nuovo
        B->>U: "Per quale materia?" (albero)
        U->>B: sceglie cartella (o "Non so")
        B->>U: reazione 👀
        B->>S: file + scheda [+5][+10][+20][Cambia cartella][Rifiuta]
        alt approvato
            A->>S: ✅ +10 (eventuale Cambia cartella)
            B->>I: sposta inbox → archive/cartella
            B->>B: +10 crediti (log)
            B->>U: reazione 👍 + "🎉 +10 crediti"
            B->>S: "Approvato da @admin · visibile al prossimo /reindex" [🔄 Reindex ora]
        else rifiutato
            A->>S: ❌ Rifiuta + motivo
            B->>U: reazione 👎 + motivo
        end
    end
```

Il file approvato è su disco ma **compare agli utenti solo dopo `/reindex`**.

---

## 5. Aggiornare l'archivio (`/reindex`)

```mermaid
stateDiagram-v2
    [*] --> Scansione: admin /reindex
    Scansione --> Anteprima: differenze calcolate
    Scansione --> Occupato: un altro reindex è in corso
    Occupato --> [*]
    Anteprima --> NessunaModifica: niente da fare
    NessunaModifica --> [*]
    Anteprima --> Applicato: ✅ Applica
    Anteprima --> Annullato: ❌ Annulla
    Anteprima --> Scaduto: 10 minuti senza scelta
    Applicato --> Ricontrollo: il disco è cambiato nel frattempo?
    Ricontrollo --> Anteprima: sì, nuova anteprima
    Ricontrollo --> Pubblicato: no
    Pubblicato --> CaricamentoCanale: in background
    CaricamentoCanale --> [*]
    Annullato --> [*]
    Scaduto --> [*]
```

Cosa mostra l'anteprima: file nuovi, modificati, spostati/rinominati (che
**tengono lo stesso ID**: link, preferiti e acquisti restano validi), rimossi,
prezzi cambiati, file Exclusive nascosti per prezzo mancante o > 50, file in
copia da meno di 30 secondi.

---

## 6. Feedback, segnalazioni, richieste di rimozione

```mermaid
sequenceDiagram
    actor U as Utente
    participant B as Bot
    participant S as Gruppo staff
    actor A as Admin

    U->>B: /feedback testo · ⚠️ Segnala · /rimozione
    B->>S: scheda ticket [✅ Chiudi]
    A->>S: reply alla scheda
    B->>U: "💬 Risposta dello staff: …"
    A->>S: ✅ Chiudi
    B->>S: "Chiuso da @admin"
```

---

## 7. Gruppi dei corsi

```mermaid
flowchart TD
    A["Bot aggiunto al gruppo"] --> B{"Gruppo collegato<br/>con /collega?"}
    B -- no --> X["Il bot ignora tutto"]
    B -- sì --> C["Utente: /materiale<br/>(comando effimero)"]
    C --> D["Menu della cartella del corso<br/>visibile solo a lui"]
    D --> E["Click su un file"]
    E --> F{"L'utente ha mai<br/>avviato il bot?"}
    F -- sì --> G["File inviato in privato"]
    F -- no --> H["'Aprimi in privato' + link"]
```

---

## 8. Task notturno (03:00 UTC)

```mermaid
flowchart LR
    J["03:00 UTC"] --> B1["Backup DB<br/>(tiene 14)"]
    B1 --> B2["Svuota trash/<br/>> 30 giorni"]
    B2 --> B3["inbox/: rifiutati > 30 gg<br/>pending > 30 gg → avviso staff"]
    B3 --> B4["Invii orfani<br/>ripubblicati o chiusi"]
    B4 --> B5["Download > 12 mesi<br/>cancellati"]
    B5 --> B6["Albero ricostruito<br/>(🆕 scaduti)"]
```

Se il bot era spento a quell'ora, il task parte all'avvio.

I file scaricati dal server Bot API li cancella un piccolo container separato
(`bot-api-cleaner`) dopo 24 ore: il bot non ne ha i permessi.
