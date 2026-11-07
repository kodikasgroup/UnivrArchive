"""Genera i loghi UniVr Archive (SVG) con forme e colori condivisi.

    python assets/brand/make_logos.py        # riscrive gli SVG in assets/brand/

I PNG si esportano dagli SVG (es. Chrome headless, vedi assets/README.md)."""
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)

# Palette originale (estratta dall'avatar)
NAVY = "#26415F"
BLOB = "#EAF4FE"
HAIR = "#222957"
BLUE = "#0080CB"
BOOK_L = "#2E3258"
BOOK_R = "#242F4D"
SKIN = "#F3BF9A"
SKIN_SH = "#EBA685"
MIST = "#C3CDD9"
WHITE = "#FFFFFF"

FONT = "Inter, 'SF Pro Display', 'Helvetica Neue', 'Segoe UI', Arial, sans-serif"


def reader() -> str:
    """Il lettore, in un riquadro 640x640, centrato e dentro il cerchio di ritaglio."""
    return f"""
  <!-- forma chiara (branding dell'originale), più morbida -->
  <path fill="{BLOB}" d="M430 104c66 44 98 140 76 232-22 94-104 156-198 152-92-4-170-70-184-160-14-88 46-170 128-204 60-24 128-48 178-20z"/>
  <!-- busto -->
  <path fill="{BLUE}" d="M206 470v-96c0-52 42-94 94-94h40c52 0 94 42 94 94v96z"/>
  <path fill="{WHITE}" d="M234 318c10-14 24-26 40-32l46 34 46-34c16 6 30 18 40 32l-86 40z"/>
  <!-- collo -->
  <rect x="298" y="228" width="44" height="54" rx="10" fill="{SKIN_SH}"/>
  <!-- testa -->
  <rect x="262" y="132" width="116" height="126" rx="56" fill="{SKIN}"/>
  <!-- capelli: calotta + ciuffo geometrico verso destra, come l'originale -->
  <path fill="{HAIR}" d="M262 196c-6-56 28-88 72-88 22 0 38 6 50 16l20-28-2 26 26-12-18 30c4 10 4 20 0 30l-28-10c-18-8-42-8-64-2-18 5-36 6-48 2-4 12-6 24-6 36z"/>
  <!-- libro aperto: pagine bianche in alto (come l'originale) e copertina -->
  <path fill="{WHITE}" d="M186 322l134 10 134-10v18l-134 12-134-12z"/>
  <path fill="{BOOK_L}" d="M180 334l140 14v146l-140-12z"/>
  <path fill="{BOOK_R}" d="M460 334l-140 14v146l140-12z"/>
  <path fill="none" stroke="{BLOB}" stroke-opacity=".18" stroke-width="3" d="M320 350v142"/>
  <!-- segnalibro: tocco d'accento -->
  <path fill="{BLUE}" d="M392 341l22-2v58l-11-9-11 9z"/>
  <!-- mani -->
  <rect x="160" y="378" width="40" height="36" rx="18" fill="{SKIN}"/>
  <rect x="440" y="378" width="40" height="36" rx="18" fill="{SKIN}"/>
"""


def svg(w: int, h: int, body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n')


# 1. Avatar Telegram: quadrato pieno, il cerchio di ritaglio contiene tutto
avatar = f'<rect width="640" height="640" fill="{NAVY}"/><g transform="translate(320 342) scale(1.08) translate(-320 -320)">{reader()}</g>'
(OUT / "avatar.svg").write_text(svg(640, 640, avatar, "UniVr Archive"))

# 2. Marchio: riquadro arrotondato (README, favicon, social)
mark = (f'<rect width="640" height="640" rx="144" fill="{NAVY}"/>'
        f'<g transform="translate(32 40) scale(.9)">{reader()}</g>')
(OUT / "mark.svg").write_text(svg(640, 640, mark, "UniVr Archive"))


def wordmark(x: int, y: int, size: int, strong: str, light: str, rule: str) -> str:
    return f"""
  <text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" letter-spacing="-1"
        fill="{strong}"><tspan font-weight="700">UniVr</tspan><tspan font-weight="400" fill="{light}"> Archive</tspan></text>
  <rect x="{x + 2}" y="{y + 26}" width="56" height="6" rx="3" fill="{rule}"/>"""


# 3. Logo orizzontale per sfondi chiari
logo = (f'<g transform="scale(.375)">{mark}</g>'
        + wordmark(276, 150, 92, NAVY, BLUE, BLUE))
(OUT / "logo.svg").write_text(svg(960, 240, logo, "UniVr Archive"))

# 4. Logo orizzontale per sfondi scuri
logo_dark = (f'<g transform="scale(.375)"><rect width="640" height="640" rx="144" fill="{NAVY}"/>'
             f'<g transform="translate(32 40) scale(.9)">{reader()}</g></g>'
             + wordmark(276, 150, 92, WHITE, MIST, BLUE))
(OUT / "logo-dark.svg").write_text(svg(960, 240, logo_dark, "UniVr Archive"))

print("ok:", sorted(p.name for p in OUT.glob("*.svg")))
