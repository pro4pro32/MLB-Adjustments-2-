"""
config.py – stałe, kolory, profile, CSS, motyw Plotly

v5 CHANGE: kategorie są teraz zunifikowane w jeden rejestr ALL_CATEGORIES:
  • 3 kategorie pitch-type:  fb_pct, bb_pct, os_pct
  • 13 kategorii per-zone:   zone1_pct … zone9_pct, zone11_pct … zone14_pct
    (zone 10 nie istnieje w Statcast attack-zone numbering)
  = 16 kategorii śledzonych tydzień-do-tygodnia per batter.

Layout stref (standardowy Statcast "attack zone" grid):

        11        12
        1    2    3
        4    5    6
        7    8    9
        13        14

1-9 = wewnątrz strefy (3x3), 11/12/13/14 = rogi na zewnątrz strefy.
"""
from __future__ import annotations

# ── Pitch types ──────────────────────────────────────────────────────────────
PITCH_TYPES: dict[str, str] = {
    "FF": "Four-Seam Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "CU": "Curveball",
    "KC": "Knuckle-Curve",
    "ST": "Sweeper",
    "CH": "Changeup",
    "FS": "Splitter",
}

PITCH_COLORS: dict[str, str] = {
    "FF": "#ff6b35",
    "SI": "#ff9a3c",
    "FC": "#ffd166",
    "SL": "#06d6a0",
    "CU": "#118ab2",
    "KC": "#4cc9f0",
    "ST": "#38b000",
    "CH": "#bc8cff",
    "FS": "#f72585",
}

# ── Strefy Statcast ──────────────────────────────────────────────────────────
ALL_ZONES: list[int] = list(range(1, 10)) + list(range(11, 15))  # 1-9, 11-14 (brak 10)
ZONE_LOW: list[int]  = [7, 8, 9]   # dolny rząd — zachowane dla wstecznej zgodności

# Wizualny layout "diamentu" stref: 5 wierszy x 3 kolumny, None = puste pole
ZONE_GRID_LAYOUT: list[list[int | None]] = [
    [11,   None, 12],
    [1,    2,    3],
    [4,    5,    6],
    [7,    8,    9],
    [13,   None, 14],
]

ZONE_DESCRIPTIONS: dict[int, str] = {
    1: "Top-left (in zone)", 2: "Top-middle (in zone)", 3: "Top-right (in zone)",
    4: "Middle-left (in zone)", 5: "Dead center (in zone)", 6: "Middle-right (in zone)",
    7: "Bottom-left (in zone)", 8: "Bottom-middle (in zone)", 9: "Bottom-right (in zone)",
    11: "Top-left (out of zone)", 12: "Top-right (out of zone)",
    13: "Bottom-left (out of zone)", 14: "Bottom-right (out of zone)",
}

# Wagi stref per pitch type [top, middle, low, outside] — używane do generowania danych syntetycznych
ZONE_WEIGHTS: dict[str, list[float]] = {
    "FF": [0.20, 0.35, 0.25, 0.20],
    "SI": [0.08, 0.22, 0.45, 0.25],
    "FC": [0.15, 0.35, 0.25, 0.25],
    "SL": [0.12, 0.25, 0.33, 0.30],
    "CU": [0.08, 0.15, 0.42, 0.35],
    "KC": [0.08, 0.15, 0.42, 0.35],
    "ST": [0.08, 0.18, 0.38, 0.36],
    "CH": [0.08, 0.22, 0.38, 0.32],
    "FS": [0.08, 0.18, 0.42, 0.32],
}

# ── Kategorie pitch-type agregowane ──────────────────────────────────────────
PITCH_CATEGORIES: dict[str, dict] = {
    "fb_pct":  {"label": "Fastball %",      "short": "FB%",  "kind": "pitch", "types": ["FF", "SI", "FC"],       "color": "#ff6b35"},
    "bb_pct":  {"label": "Breaking Ball %", "short": "BB%",  "kind": "pitch", "types": ["SL", "CU", "KC", "ST"], "color": "#58a6ff"},
    "os_pct":  {"label": "Offspeed %",      "short": "OS%",  "kind": "pitch", "types": ["CH", "FS"],             "color": "#bc8cff"},
}

# Kolory per-zone (gradient: wewnątrz strefy = zielono-żółty, poza = fioletowo-niebieski)
_ZONE_COLOR_IN  = ["#39d353", "#7ee787", "#a5d6ff", "#e3b341", "#ffd166", "#ff9a3c", "#ff6b35", "#f85149", "#f72585"]
_ZONE_COLOR_OUT = ["#4cc9f0", "#58a6ff", "#bc8cff", "#7c3aed"]

ZONE_CATEGORIES: dict[str, dict] = {}
for _i, _z in enumerate(ALL_ZONES):
    _in_zone = _z <= 9
    ZONE_CATEGORIES[f"zone{_z}_pct"] = {
        "label": f"Zone {_z} % ({ZONE_DESCRIPTIONS[_z]})",
        "short": f"Z{_z}%",
        "kind":  "zone",
        "zone":  _z,
        "color": _ZONE_COLOR_IN[_i] if _in_zone else _ZONE_COLOR_OUT[_z - 11],
    }

# ── Rejestr zunifikowany — TO jest teraz źródło prawdy dla wszystkich obliczeń ──
ALL_CATEGORIES: dict[str, dict] = {**PITCH_CATEGORIES, **ZONE_CATEGORIES}

CAT_COLS        = list(ALL_CATEGORIES.keys())                                    # 16 kolumn
PITCH_CAT_COLS  = list(PITCH_CATEGORIES.keys())                                  # 3 kolumny (dla starszych wykresów)
ZONE_CAT_COLS   = list(ZONE_CATEGORIES.keys())                                   # 13 kolumn
CAT_LABELS      = {k: v["short"] for k, v in ALL_CATEGORIES.items()}
CAT_COLORS      = {k: v["color"] for k, v in ALL_CATEGORIES.items()}

# Zachowane dla wstecznej zgodności z istniejącym kodem (Tab Rankingi per-kategoria itp.)
PITCH_CATEGORIES_LEGACY = PITCH_CATEGORIES

# ── Profile pitcherów (v6.3: pełna liga, ~55 starterów) ──────────────────────
PITCHER_PROFILES: dict[str, dict] = {
    "Gerrit Cole":      {"primary": "FF", "secondary": ["SL", "CH", "KC"]},
    "Sandy Alcantara":  {"primary": "SI", "secondary": ["SL", "CH", "FF"]},
    "Spencer Strider":  {"primary": "FF", "secondary": ["SL"]},
    "Zack Wheeler":     {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Kevin Gausman":    {"primary": "FC", "secondary": ["FS", "FF", "SL"]},
    "Pablo Lopez":      {"primary": "CH", "secondary": ["FF", "SI", "SL"]},
    "Corbin Burnes":    {"primary": "FC", "secondary": ["SL", "CU", "SI"]},
    "Framber Valdez":   {"primary": "SI", "secondary": ["CU", "CH", "FF"]},
    "Logan Gilbert":    {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Luis Castillo":    {"primary": "FF", "secondary": ["SL", "CH", "SI"]},
    "Yu Darvish":       {"primary": "SL", "secondary": ["FF", "CU", "CH", "FC"]},
    "Max Fried":        {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Dylan Cease":      {"primary": "SL", "secondary": ["FF", "CU", "CH"]},
    "Shane Bieber":     {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Shohei Ohtani":    {"primary": "FF", "secondary": ["SL", "CU", "FS"]},
    "Kodai Senga":      {"primary": "FS", "secondary": ["FF", "CU", "ST"]},
    "Tarik Skubal":     {"primary": "FF", "secondary": ["CH", "SL", "CU"]},
    "Chris Sale":       {"primary": "FF", "secondary": ["SL", "CH", "CU"]},
    "Grayson Rodriguez":{"primary": "FF", "secondary": ["SL", "CH", "CU"]},
    "Zach Eflin":       {"primary": "FF", "secondary": ["FC", "CU", "CH"]},
    "Tanner Houck":     {"primary": "SI", "secondary": ["SL", "ST", "CU"]},
    "Brayan Bello":     {"primary": "SI", "secondary": ["CH", "CU", "SL"]},
    "Carlos Rodon":     {"primary": "FF", "secondary": ["SL", "CH"]},
    "Marcus Stroman":   {"primary": "SI", "secondary": ["SL", "CH", "CU"]},
    "Shane McClanahan": {"primary": "FF", "secondary": ["CU", "CH", "SL"]},
    "Jose Berrios":     {"primary": "FF", "secondary": ["CU", "SI", "CH"]},
    "Aaron Nola":       {"primary": "FF", "secondary": ["CU", "CH", "SI"]},
    "Garrett Crochet":  {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Michael Kopech":   {"primary": "FF", "secondary": ["SL", "CH"]},
    "Nick Lodolo":      {"primary": "FF", "secondary": ["CU", "CH", "SL"]},
    "Hunter Greene":    {"primary": "FF", "secondary": ["SL", "CH"]},
    "Freddy Peralta":   {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Ranger Suarez":    {"primary": "SI", "secondary": ["CH", "CU", "SL"]},
    "Mitch Keller":     {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Sonny Gray":       {"primary": "FF", "secondary": ["SL", "CU", "SI"]},
    "Bailey Ober":      {"primary": "FF", "secondary": ["SL", "CH", "CU"]},
    "Jesus Luzardo":    {"primary": "FF", "secondary": ["SL", "CH"]},
    "Justin Verlander": {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Cristopher Sanchez":{"primary": "SI", "secondary": ["CH", "SL"]},
    "Tyler Glasnow":    {"primary": "FF", "secondary": ["CU", "SL", "CH"]},
    "Yusei Kikuchi":    {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "George Kirby":     {"primary": "FF", "secondary": ["SL", "CH", "CU"]},
    "Bryce Miller":     {"primary": "FF", "secondary": ["SL", "SI", "CH"]},
    "Nathan Eovaldi":   {"primary": "FF", "secondary": ["SL", "CU", "SI"]},
    "Jack Flaherty":    {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Zac Gallen":       {"primary": "FF", "secondary": ["CU", "CH", "SL"]},
    "Merrill Kelly":    {"primary": "SL", "secondary": ["FF", "CU", "CH"]},
    "Kyle Freeland":    {"primary": "SI", "secondary": ["SL", "CH", "CU"]},
    "German Marquez":   {"primary": "FF", "secondary": ["SL", "CU", "CH"]},
    "Yoshinobu Yamamoto":{"primary": "FF", "secondary": ["SL", "CU", "FS"]},
    "Tony Gonsolin":    {"primary": "FF", "secondary": ["SL", "SI", "CH"]},
    "Joe Musgrove":     {"primary": "FF", "secondary": ["SL", "CH", "CU"]},
    "Jared Jones":      {"primary": "FF", "secondary": ["SL", "CH"]},
    "Logan Webb":       {"primary": "SI", "secondary": ["CH", "SL", "FC"]},
    "Robbie Ray":       {"primary": "FF", "secondary": ["SL", "CH"]},
}

# ── v6.3: Pełna liga — 30 drużyn MLB, ~7 batterów per drużyna (~210 łącznie) ─
TEAM_ROSTERS: dict[str, list[str]] = {
    "Baltimore Orioles":     ["Gunnar Henderson", "Anthony Santander", "Cedric Mullins", "Pete Alonso"],
    "Boston Red Sox":        ["Rafael Devers", "Trevor Story", "Jarren Duran", "Wilyer Abreu",
                                "Triston Casas", "Masataka Yoshida", "Ceddanne Rafaela", "Willson Contreras", "Adley Rutschman"],
    "New York Yankees":      ["Aaron Judge", "Giancarlo Stanton", "Anthony Volpe", "Austin Wells",
                                "Jazz Chisholm Jr.", "Cody Bellinger", "Paul Goldschmidt", "Heliot Ramos", "Luis Garcia Jr."],
    "Tampa Bay Rays":        ["Yandy Diaz", "Jose Siri", "Brandon Lowe",
                                "Josh Lowe", "Junior Caminero", "Richie Palacios", "Jack Suwinski"],
    "Toronto Blue Jays":     ["Vladimir Guerrero Jr.", "George Springer", "Daulton Varsho",
                                "Alejandro Kirk", "Ernie Clement", "Addison Barger"],
    "Chicago White Sox":     ["Luis Robert Jr.", "Andrew Vaughn", "Gavin Sheets", "Zach Remillard",
                                "Nicky Lopez", "Braden Shewmake", "Lenyn Sosa"],
    "Cleveland Guardians":   ["Jose Ramirez", "Steven Kwan", "Josh Naylor", "Andres Gimenez",
                                "Bo Naylor", "Kyle Manzardo", "Tyler Freeman"],
    "Detroit Tigers":        ["Riley Greene", "Spencer Torkelson", "Kerry Carpenter", "Colt Keith",
                                "Javier Baez", "Matt Vierling", "Parker Meadows"],
    "Kansas City Royals":    ["Bobby Witt Jr.", "Salvador Perez", "Vinnie Pasquantino", "MJ Melendez",
                                "Maikel Garcia", "Michael Massey", "Hunter Renfroe"],
    "Minnesota Twins":       ["Byron Buxton", "Carlos Correa", "Royce Lewis", "Ryan Jeffers",
                                "Matt Wallner", "Willi Castro", "Trevor Larnach"],
    "Houston Astros":        ["Jose Altuve", "Yordan Alvarez", "Isaac Paredes",
                                "Yainer Diaz", "Jeremy Pena", "Chas McCormick", "Christian Walker"],
    "Los Angeles Angels":    ["Mike Trout", "Logan O'Hoppe",
                                "Zach Neto", "Jo Adell", "Nolan Schanuel"],
    "Athletics":             ["Brent Rooker", "Zack Gelof", "JJ Bleday", "Shea Langeliers",
                                "Lawrence Butler", "Tyler Soderstrom", "Seth Brown"],
    "Seattle Mariners":      ["Julio Rodriguez", "Cal Raleigh", "J.P. Crawford", "Josh Rojas",
                                "Mitch Garver", "Brendan Donovan", "Victor Robles", "Taylor Ward"],
    "Texas Rangers":         ["Corey Seager", "Marcus Semien", "Adolis Garcia", "Josh Jung",
                                "Wyatt Langford", "Jonah Heim", "Ezequiel Duran"],
    "Atlanta Braves":        ["Ronald Acuna Jr.", "Austin Riley", "Matt Olson", "Ozzie Albies",
                                "Sean Murphy", "Michael Harris II", "Orlando Arcia"],
    "Miami Marlins":         ["Jesus Sanchez", "Jake Burger", "Xavier Edwards",
                                "Griffin Conine", "Nick Fortes", "Kyle Stowers"],
    "New York Mets":         ["Juan Soto", "Francisco Lindor", "Brandon Nimmo",
                                "Mark Vientos", "Francisco Alvarez", "Starling Marte", "Bo Bichette"],
    "Philadelphia Phillies": ["Bryce Harper", "Trea Turner", "Kyle Schwarber", "Alec Bohm",
                                "J.T. Realmuto", "Nick Castellanos", "Bryson Stott", "Luis Arraez"],
    "Washington Nationals":  ["CJ Abrams", "James Wood", "Keibert Ruiz",
                                "Jacob Young", "Joey Meneses", "Alex Call"],
    "Chicago Cubs":          ["Seiya Suzuki", "Dansby Swanson", "Ian Happ", "Nico Hoerner",
                                "Michael Busch", "Christopher Morel", "Alex Bregman"],
    "Cincinnati Reds":       ["Elly De La Cruz", "Spencer Steer", "Matt McLain", "TJ Friedl",
                                "Christian Encarnacion-Strand", "Jonathan India"],
    "Milwaukee Brewers":     ["William Contreras", "Christian Yelich", "Willy Adames", "Jackson Chourio",
                                "Brice Turang", "Sal Frelick", "Rhys Hoskins"],
    "Pittsburgh Pirates":    ["Oneil Cruz", "Bryan Reynolds", "Ke'Bryan Hayes", "Joey Bart", "Nick Gonzales"],
    "St. Louis Cardinals":   ["Masyn Winn", "Alec Burleson"],
    "Arizona Diamondbacks":  ["Corbin Carroll", "Ketel Marte", "Gabriel Moreno",
                                "Eugenio Suarez", "Lourdes Gurriel Jr.", "Jake McCarthy", "Nolan Arenado", "Lars Nootbaar"],
    "Colorado Rockies":      ["Ryan McMahon", "Ezequiel Tovar", "Brenton Doyle", "Elias Diaz",
                                "Nolan Jones", "Michael Toglia", "Connor Norby"],
    "Los Angeles Dodgers":   ["Shohei Ohtani", "Mookie Betts", "Freddie Freeman", "Will Smith",
                                "Teoscar Hernandez", "Max Muncy", "Kyle Tucker"],
    "San Diego Padres":      ["Fernando Tatis Jr.", "Manny Machado", "Xander Bogaerts", "Jackson Merrill",
                                "Jake Cronenworth", "Jurickson Profar"],
    "San Francisco Giants":  ["Matt Chapman", "Jung Hoo Lee", "Patrick Bailey",
                                "Wilmer Flores", "Tyler Fitzgerald", "LaMonte Wade Jr."],
}

TEAMS: list[str] = list(TEAM_ROSTERS.keys())
BATTERS: list[str] = [b for roster in TEAM_ROSTERS.values() for b in roster]
TEAM_OF_BATTER: dict[str, str] = {b: team for team, roster in TEAM_ROSTERS.items() for b in roster}

INACTIVE_BY_SEASON: dict[int, set[str]] = {
    2024: {"Wander Franco"},
    2025: {"Wander Franco"},
    2026: {"Wander Franco"},
}

AVAILABLE_SEASONS: list[int] = [2022, 2023, 2024, 2025, 2026]

# ── v6: Pitcher handedness (dla platoon splits: vs LHP / vs RHP) ─────────────
_LEFTIES = {
    "Framber Valdez", "Max Fried", "Tarik Skubal", "Chris Sale", "Yusei Kikuchi",
    "Kyle Freeland", "Robbie Ray", "Garrett Crochet", "Nick Lodolo",
    "Ranger Suarez", "Jesus Luzardo", "Cristopher Sanchez",
}
PITCHER_THROWS: dict[str, str] = {name: ("L" if name in _LEFTIES else "R") for name in PITCHER_PROFILES}

# ── v6: Typowe prędkości (mph) per pitch type — do trackingu velo drift ──────
PITCH_VELO_RANGES: dict[str, tuple[float, float]] = {
    # (średnia mph, odchylenie std)
    "FF": (95.0, 1.6), "SI": (94.5, 1.6), "FC": (89.5, 1.5),
    "SL": (85.5, 1.8), "CU": (79.0, 2.0), "KC": (81.0, 1.8),
    "ST": (82.5, 1.8), "CH": (86.0, 1.7), "FS": (85.5, 1.7),
}

# ── v6: Progi wiarygodności (sample-size guard) ──────────────────────────────
MIN_RELIABLE_PITCHES: int = 20   # both current AND baseline week need >= this
BASELINE_WEEKS: int = 3          # rolling window dla "vs baseline" (zamiast pojedynczego poprz. tygodnia)

# ── Plotly – motyw bazowy (v6.4: mocniejszy kontrast tekstu + większe marginesy) ──
CHART_TEXT_COLOR = "#f0f6fc"    # niemal biały — dobry kontrast na ciemnym tle
CHART_MUTED_COLOR = "#c9d1d9"   # dla drugorzędnych elementów (siatka, obramowania)

PLOTLY_BASE: dict = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color=CHART_TEXT_COLOR, size=13),
    margin=dict(l=40, r=40, t=56, b=40),
    hoverlabel=dict(
        bgcolor="#161b22",
        bordercolor="#30363d",
        font=dict(color=CHART_TEXT_COLOR, size=12),
    ),
)

LEGEND_DEFAULT: dict = dict(
    bgcolor="rgba(22,27,34,0.92)",
    bordercolor="#30363d",
    borderwidth=1,
    font=dict(size=11, color=CHART_TEXT_COLOR),
)

AXIS_STYLE: dict = dict(
    gridcolor="#21262d",
    linecolor="#30363d",
    tickfont=dict(size=11, color=CHART_TEXT_COLOR),
    title_font=dict(size=12, color=CHART_TEXT_COLOR),
    zeroline=False,
    automargin=True,
    ticklabelstandoff=6,   # v6.4: breathing room between tick labels and axis line
)

# ── CSS ───────────────────────────────────────────────────────────────────────
APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --bg:      #0d1117;  --bg2:    #161b22;  --bg3:    #21262d;
    --border:  #30363d;  --green:  #39d353;  --red:    #f85149;
    --yellow:  #e3b341;  --blue:   #58a6ff;  --purple: #bc8cff;
    --text:    #f0f6fc;  --muted:  #8b949e;  --accent: #ff6b35;
    --accent2: #ffd166;
}
html, body, [class*="css"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', sans-serif;
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1117 0%, #111820 100%) !important;
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] * { color: var(--text) !important; }
section[data-testid="stSidebar"] .stMarkdown h3 {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1rem;
    letter-spacing: 2px;
    color: var(--accent) !important;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
    margin: 16px 0 8px 0;
}
div[data-testid="stSelectbox"] > div,
div[data-testid="stMultiSelect"] > div,
div[data-testid="stTextInput"] > div > div {
    background-color: var(--bg3) !important;
    border-color: var(--border) !important;
    border-radius: 8px !important;
}
div[data-testid="stSlider"] > div { color: var(--text) !important; }
div[data-testid="stTabs"] > div > div > button {
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    font-size: 0.82rem;
    color: var(--muted) !important;
    border-radius: 6px 6px 0 0;
    padding: 8px 16px;
}
div[data-testid="stTabs"] > div > div > button[aria-selected="true"] {
    color: var(--accent) !important;
    border-bottom: 2px solid var(--accent) !important;
    background: var(--bg2) !important;
}
div[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}
/* v6.4: force readable white text inside dataframes/tables regardless of pandas Styler output */
/* v6.6 FIX: previously forced white text everywhere in dataframes with !important —
   this broke pandas' own contrast-aware text color from .background_gradient(), which
   picks dark text for light/pale cells (e.g. pale yellow/green) and light text for dark
   cells. Inline styles from pandas' Styler beat a plain (non-!important) rule, so this
   now only sets a sensible DEFAULT for cells that have no Styler color of their own. */
div[data-testid="stDataFrame"] { color: var(--text); }
div[data-testid="stDataFrame"] table { font-variant-numeric: tabular-nums; }
div[data-testid="stInfo"]    { background: #0d2137 !important; border-color: var(--blue) !important; color: var(--text) !important; }
div[data-testid="stWarning"] { background: #2d1f00 !important; border-color: var(--yellow) !important; color: var(--text) !important; }
div[data-testid="stError"]   { background: #2d0f0f !important; border-color: var(--red) !important; color: var(--text) !important; }
div[data-testid="stInfo"] *, div[data-testid="stWarning"] *, div[data-testid="stError"] * { color: var(--text) !important; }
/* v6.4: ensure every native widget label/value stays readable on the dark background */
label, .stSelectbox, .stMultiSelect, .stSlider, .stRadio, .stCheckbox, .stTextInput,
div[data-testid="stMarkdownContainer"] p, div[data-testid="stMetricValue"],
div[data-testid="stMetricLabel"] {
    color: var(--text) !important;
}
.dash-header {
    background: linear-gradient(135deg, #1a0800 0%, #0d1117 40%, #001510 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 28px 36px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}
.dash-header::after {
    content: '⚾';
    position: absolute;
    right: 28px; top: 50%;
    transform: translateY(-50%);
    font-size: 96px;
    opacity: 0.06;
    pointer-events: none;
}
.dash-header h1 {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 2.6rem;
    letter-spacing: 4px;
    color: var(--accent) !important;
    margin: 0 0 6px 0;
    line-height: 1;
}
.dash-header .subtitle { color: var(--muted) !important; font-size: 0.88rem; margin: 0; }
.dash-header .badge {
    display: inline-block;
    background: rgba(255,107,53,0.15);
    border: 1px solid rgba(255,107,53,0.4);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.72rem;
    color: var(--accent) !important;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 10px;
}
.kpi-row { display: flex; gap: 14px; margin: 0 0 24px 0; flex-wrap: wrap; }
.kpi-card {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    flex: 1; min-width: 138px; box-sizing: border-box;
    transition: border-color 0.2s;
    overflow: hidden;
    container-type: inline-size;
}
.kpi-card:hover { border-color: #444d56; }
.kpi-card .kpi-label {
    font-size: 0.68rem; color: var(--muted);
    text-transform: uppercase; letter-spacing: 1.2px;
    margin-bottom: 4px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kpi-card .kpi-value {
    font-family: 'Bebas Neue', sans-serif;
    font-size: clamp(1rem, 15cqi, 2rem);
    color: var(--accent); line-height: 1.15;
    font-variant-numeric: tabular-nums;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kpi-card .kpi-sub {
    font-size: 0.7rem; color: var(--muted); margin-top: 3px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kpi-card.highlight { border-color: rgba(255,107,53,0.5); background: rgba(255,107,53,0.06); }
.section-hdr {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.2rem; letter-spacing: 2px;
    color: var(--yellow);
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
    margin: 24px 0 14px 0;
}
.insight-box {
    background: linear-gradient(135deg, #0d2137, #111820);
    border: 1px solid #1a3a5c;
    border-left: 3px solid var(--blue);
    border-radius: 8px;
    padding: 12px 16px;
    margin: 12px 0;
    font-size: 0.84rem;
    color: var(--text) !important;
}
.insight-box .icon { font-size: 1.1rem; margin-right: 6px; }
.trend-up   { color: var(--green) !important; font-family: 'JetBrains Mono', monospace; font-weight: 600; }
.trend-down { color: var(--red)   !important; font-family: 'JetBrains Mono', monospace; font-weight: 600; }
.trend-neu  { color: var(--muted) !important; font-family: 'JetBrains Mono', monospace; }
.perf-pill {
    display: inline-block;
    background: #0d2137; border: 1px solid #1a3a5c;
    border-radius: 20px; padding: 4px 14px;
    font-size: 0.72rem; color: var(--blue);
    font-family: 'JetBrains Mono', monospace;
}
.cat-chip {
    display: inline-block; padding: 3px 10px;
    border-radius: 12px; font-size: 0.72rem;
    font-weight: 600; margin: 2px;
    font-family: 'JetBrains Mono', monospace;
}
.empty-state {
    text-align: center; padding: 48px 24px;
    color: var(--muted); font-size: 0.9rem;
}
.empty-state .icon { font-size: 2.5rem; display: block; margin-bottom: 12px; }

/* ── Player Report / shareable card ─────────────────────────────────────── */
.share-card {
    background: radial-gradient(circle at top right, #1a0800 0%, #0d1117 55%, #001510 100%);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 36px 40px;
    margin-bottom: 20px;
    position: relative;
    overflow: hidden;
}
.share-card::after {
    content: '⚾';
    position: absolute; right: 12px; bottom: -20px;
    font-size: 160px; opacity: 0.05; pointer-events: none;
}
.share-card .sc-eyebrow {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem; letter-spacing: 2px; text-transform: uppercase;
    color: var(--accent2);
}
.share-card .sc-name {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 2.4rem; letter-spacing: 2px; color: var(--text);
    margin: 4px 0 10px 0;
}
.share-card .sc-headline {
    font-size: 1.15rem; color: var(--text); line-height: 1.5;
    max-width: 640px;
}
.share-card .sc-headline b { color: var(--accent); }
.share-card .sc-meta {
    margin-top: 16px; font-size: 0.78rem; color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
}
</style>
"""
