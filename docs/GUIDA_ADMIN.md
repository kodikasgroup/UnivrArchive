# Guida per gli admin

Tutto quello che serve allo staff per gestire UniVrArchive **da Telegram**,
senza toccare il server. Per i diagrammi vedi [`FLUSSI.md`](FLUSSI.md), per installazione e backup [`INSTALLAZIONE.md`](INSTALLAZIONE.md).

Sei admin se il tuo ID Telegram è in `ADMIN_IDS` (nel `.env`). Nessuna password:
i comandi admin compaiono nel tuo menu `/` e per gli altri non esistono.

---

## 1. Regola d'oro

> **Il disco decide, `/reindex` pubblica.**
> Qualsiasi modifica all'archivio (file approvati, ⚙️ Gestisci, SFTP) diventa
> visibile agli utenti **solo** dopo `/reindex` → ✅ Applica.

Puoi quindi fare con calma anche molte modifiche, controllare l'anteprima e
pubblicare tutto insieme.

---

## 2. Comandi

| Comando | Cosa fa |
|---|---|
| `/reindex` | confronta il disco con il bot e mostra l'anteprima; ✅ Applica pubblica |
| `/pending` | invii degli utenti ancora da moderare |
| `/stats` | utenti totali, attivi 7/30 giorni, download, file più scaricati |
| `/crediti_add <id o @username> <n> [motivo]` | dà (o toglie, con `n` negativo) crediti. Il motivo resta nel registro |
| `/vip <id o @username> <giorni>` | VIP per N giorni (si somma se è già VIP) |
| `/vip <id o @username> 0` | VIP permanente |
| `/vip <id o @username> off` | toglie il VIP |
| `/broadcast` | **in risposta** a un messaggio: lo manda a tutti gli utenti, dopo anteprima e conferma |
| `/collega` · `/scollega` | (dentro un gruppo) collega il gruppo a una cartella del corso |

Con `@username` il bot può rispondere "ambiguo/non trovato": usa l'ID numerico
(lo vedi nelle schede del gruppo staff).

---

## 3. Moderare il materiale inviato

Nel gruppo staff arriva il file con una scheda:

```
📄 esame_reti_2025.pdf · 2.3 MB
da: @mario (123456789)
suggerita: INFORMATICA › 2° Anno › RETI
[✅ +5] [✅ +10] [✅ +20]
[📂 Cambia cartella] [❌ Rifiuta]
```

1. **Controlla il file** (aprilo dal gruppo).
2. **Cartella sbagliata?** `📂 Cambia cartella` → naviga → `📥 Salva qui`
   (puoi anche creare una cartella nuova da lì).
3. **Approva** con i crediti che merita: `+5` riassunto/esame singolo, `+10`
   raccolta di esami risolti, `+20` progetti/codice (stessa scala dei prezzi).
   - Se scegli una cartella sotto `EXCLUSIVE/`, il bot chiede anche il **prezzo**.
4. **Rifiuta** scegliendo il motivo: l'utente lo riceve.
5. Quando hai approvato quello che volevi: `🔄 Reindex ora` (o `/reindex`).

Note:
- I duplicati non arrivano nemmeno: il bot li scarta da solo.
- I crediti si danno al click, anche se poi il file non viene pubblicato.
- Solo gli admin possono cliccare: gli altri membri del gruppo vedono e basta.
- Doppio click o due admin insieme: i crediti si danno una volta sola.

---

## 4. Aggiungere file tu stesso

Manda il documento al bot in privato: scegli la cartella (anche `EXCLUSIVE/`,
con prezzo) e il file viene salvato. Nessuna moderazione, nessun credito.
Poi `/reindex`.

Per caricare molti file insieme conviene SFTP/Samba/`rsync` direttamente in
`data/prod/archive/` (copia preservando le date, es. `rsync -a`), poi `/reindex`.

---

## 5. ⚙️ Gestisci (riorganizzare l'archivio da Telegram)

Navigando nel bot, in ogni cartella vedi `[⚙️ Gestisci]`:

| Azione | Note |
|---|---|
| ➕ Nuova cartella | nome scritto in chat |
| ✏️ Rinomina | sotto `EXCLUSIVE/` scrivi solo il nome, il prezzo resta |
| 📦 Sposta | scegli la destinazione dall'albero |
| 💰 Prezzo | solo file sotto `EXCLUSIVE/` |
| 🗑 Elimina | va nel **cestino** per 30 giorni, recuperabile dal server |
| 🔄 Reindex | come `/reindex` |

Spostare o rinominare **non rompe nulla**: link, preferiti e acquisti seguono il
file. **Unica eccezione:** non modificare il contenuto **e** spostare lo stesso
file nello stesso `/reindex` (prima correggi → `/reindex`, poi sposta →
`/reindex`), altrimenti chi l'aveva comprato perde l'accesso.

---

## 6. Leggere l'anteprima di `/reindex`

```
🗂 Anteprima reindex
+12 file  (INFORMATICA/2° Anno/RETI: 9, TOLC: 3)
~1 modificato
↪ 5 spostati/rinominati (ID conservati)
−3 rimossi
⚠ 1 file Exclusive senza prezzo (nascosto): EXCLUSIVE/.../EsameNuovo.pdf
⚠ 1 prezzo oltre 50 (nascosto): EXCLUSIVE/.../2021_esame.pdf → 2021
⏳ 2 file ancora in copia, rilancia /reindex tra poco
[✅ Applica]  [❌ Annulla]
```

- **Numeri strani** (es. "−300 rimossi")? **Annulla** e controlla le cartelle.
- **⚠ nascosto:** il file non sarà visibile finché non correggi il nome
  (`5.nome.pdf`, `10.nome.pdf`; massimo 50).
- **⏳ in copia:** file modificati negli ultimi 30 secondi, aspetta e rilancia.
- L'anteprima scade dopo **10 minuti**.
- Dopo Applica i file nuovi vengono caricati nel canale storage in background
  (`⬆️ Caricati 120/340`): il bot funziona normalmente nel frattempo.

---

## 7. Prezzi Exclusive

Il prezzo è il **numero all'inizio del nome** del file, solo sotto `EXCLUSIVE/`:
`5.Riassunto.pdf` = 5 crediti, `10TemaEsame.pdf` = 10 crediti.

| Prezzo | Per cosa |
|---|---|
| 5 | riassunto o esame singolo |
| 10 | raccolta di esami risolti |
| 20 | progetti e codice |

- Senza numero o sopra 50 → il file resta **nascosto** (meglio che venderlo o
  regalarlo per errore).
- Cambiare prezzo: 💰 Prezzo (o rinomina) → `/reindex`. Chi l'ha già comprato
  lo tiene; nessun rimborso automatico se il prezzo scende (puoi usare
  `/crediti_add`).
- Rendere gratis: togli il numero o spostalo fuori da `EXCLUSIVE/`.
- Lo stesso file dentro e fuori da `EXCLUSIVE/` → l'anteprima ti avvisa: così
  sarebbe gratis dall'altra cartella.

---

## 8. Ticket: feedback, segnalazioni, rimozioni

Nel gruppo staff arrivano schede `🗨 Feedback`, `⚠️ Segnalazione`,
`🚫 Richiesta rimozione`.

- **Rispondi con una reply** alla scheda: il bot la manda all'utente.
- `✅ Chiudi` quando hai finito.
- **Rimozione per diritti d'autore:** verifica, poi ⚙️ Gestisci → 🗑 Elimina →
  `/reindex`, rispondi all'utente e chiudi.

---

## 9. Gruppi dei corsi

1. Aggiungi il bot al gruppo.
2. Scrivi `/collega` nel gruppo e scegli la cartella del corso.
3. Gli studenti usano `/materiale`: il menu lo vede solo chi lo chiede, i file
   arrivano in privato.

Un gruppo non collegato viene ignorato. `/scollega` per togliere.

---

## 10. Crediti, VIP, correzioni

- Non esistono pagamenti né rimborsi automatici: ogni correzione è
  `/crediti_add` con un motivo (resta nel registro).
- Il saldo non va mai sotto zero: un `/crediti_add` negativo troppo grande viene
  rifiutato.
- Il VIP scarica tutti i file Exclusive gratis finché è valido.

---

## 11. Cose da non fare

- ❌ Scrivere o cancellare messaggi nel **canale storage**.
- ❌ Cancellare file direttamente dal server se puoi usare 🗑 Elimina (cestino).
- ❌ Modificare **e** spostare lo stesso file Exclusive nello stesso `/reindex`.
- ❌ Condividere il `.env` o i token.

---

## 12. Se qualcosa non va

| Problema | Cosa fare |
|---|---|
| Il bot non risponde | `docker compose ps`, `docker compose logs -f bot` sul Pi |
| Un file non si scarica | ⚠️ Segnala da utente arriva in staff; prova `/reindex` |
| Errori ripetuti | arrivano in `LOG_CHAT_ID` con il dettaglio |
| DB rovinato | ripristino dal backup notturno: procedura in [`INSTALLAZIONE.md` §6](INSTALLAZIONE.md#6-ripristinare-il-database) |
