# Asset del progetto

File grafici che fanno parte del progetto. **Il bot non legge mai da qui**: quello
che gli serve si copia in `data/<bot>/media/` (vedi
[`docs/INSTALLAZIONE.md`](../docs/INSTALLAZIONE.md#2-prima-installazione)).

```
assets/
├── welcome.mp4             animazione di /start (default, da copiare in data/prod/media/)
└── brand/
    ├── avatar.svg          foto profilo del bot (sorgente)
    ├── avatar-640.jpg      → da caricare in @BotFather (/setuserpic)
    ├── avatar-640.png
    ├── mark.svg            marchio: riquadro arrotondato (README, social, favicon)
    ├── mark-512.png  mark-180.png  mark-64.png  mark-32.png
    ├── logo.svg            marchio + scritta, per sfondi chiari
    ├── logo@2x.png
    ├── logo-dark.svg       marchio + scritta, per sfondi scuri (trasparente)
    ├── logo-dark@2x.png
    └── make_logos.py       genera gli SVG (forme e colori in un solo posto)
```

## Palette

| Colore | Hex | Uso |
|---|---|---|
| Navy | `#26415F` | sfondo, "UniVr" su chiaro |
| Ghiaccio | `#EAF4FE` | forma chiara dietro il lettore |
| Blu | `#0080CB` | maglia, segnalibro, "Archive" su chiaro, linea d'accento |
| Indaco | `#222957` | capelli |
| Libro | `#2E3258` / `#242F4D` | copertina |
| Pelle | `#F3BF9A` / `#EBA685` | viso, mani / collo |
| Nebbia | `#C3CDD9` | "Archive" su scuro |

Colori presi dall'avatar originale: il restyling cambia le forme (più pulite e
geometriche), non i colori.

## Regole

- **Avatar Telegram:** solo il personaggio, niente scritte. Telegram ritaglia
  l'avatar in un cerchio e lo mostra anche a 48 px: una scritta verrebbe tagliata
  e non si leggerebbe.
- **Scritta:** "UniVr" in grassetto, "Archive" regolare, una linea blu corta
  sotto. Negli SVG il font dipende dal sistema (Inter, SF Pro, Helvetica):
  dove serve una resa identica ovunque (README, social) usare i **PNG**.
- **File piccoli:** immagini ottimizzate, video brevi (< 1 MB). Git conserva per
  sempre ogni versione di un file.
- **Mai** materiale dell'archivio o screenshot con nomi/ID di utenti reali.

## Rigenerare

```bash
python assets/brand/make_logos.py           # riscrive gli SVG
# PNG (esempio con Chrome headless, da macOS):
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --hide-scrollbars --default-background-color=00000000 \
  --force-device-scale-factor=2 --window-size=960,240 \
  --screenshot=assets/brand/logo@2x.png "file://$PWD/assets/brand/logo.svg"
```
