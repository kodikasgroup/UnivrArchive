# Mini App — rimandata (dopo la v1)

> Stato: **non in sviluppo**. Questo documento serve solo a non perdere
> l'analisi. Nessun task della v1 la prepara.

## Cos'è

Una **Mini App** è una pagina web che si apre dentro Telegram (dalla Bot API
8.0 anche a schermo intero), lanciata da un bottone del bot. Per UniVrArchive
sarebbe un esploratore dell'archivio:

- albero delle cartelle espandibile, senza un messaggio per ogni livello;
- ricerca che filtra mentre si scrive;
- filtri per corso, anno, materia, "solo novità";
- tocco su un file → il bot lo manda in chat (stesso `file_id` della v1).

## Perché è rimandata

| Costo | Dettaglio |
|---|---|
| Frontend web | HTML/JS da scrivere e mantenere, oltre al bot Python |
| HTTPS pubblico | Telegram apre solo URL `https://` raggiungibili da internet |
| Rete | il Raspberry è dietro NAT → serve un tunnel (es. Cloudflare Tunnel): un servizio in più nel compose, un account esterno, un dominio |
| Sicurezza | va verificato `initData` (firma HMAC col token) su ogni richiesta, altrimenti chiunque può fingersi un utente |
| Superficie d'attacco | un server web esposto, contro zero porte aperte della v1 (long polling) |

La v1 copre già la navigazione (bottoni + paginazione + breadcrumb) e la ricerca
(inline e `/cerca`).

## Quando riprenderla

Solo se, dopo il lancio, i dati dicono che la navigazione a bottoni è scomoda:

- molti utenti usano `/cerca` più volte di fila per lo stesso file;
- cartelle con più di 5 pagine diventano comuni;
- feedback degli utenti in quella direzione.

## Come andrebbe fatta (bozza)

- Pagina statica (HTML + JS, nessun framework pesante) servita dal bot stesso
  con `aiohttp` (già dipendenza di aiogram), dietro Cloudflare Tunnel.
- API minime in sola lettura: `GET /api/tree` (albero senza percorsi su disco),
  `POST /api/send` (`node_id`) → il bot invia il file in chat.
- Ogni richiesta verifica `initData`; i file Exclusive seguono le stesse regole
  di acquisto della v1 (la Mini App non vende niente da sola).
- Nessun dato nuovo nel DB: usa `nodes`, `purchases`, `favorites` esistenti.
