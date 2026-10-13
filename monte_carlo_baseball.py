"""
Monte Carlo Baseball 2025 / 2026
================================
Obsługa plików:
  Batters_2025_splits.csv
  Batters_2026_splits.csv

Kolumny splitów (opcjonalne):
  pa_lhp, k_percent_lhp, bb_percent_lhp, babip_lhp, hr_pct_lhp,
  hbp_pct_lhp, 1b_rate_lhp, 2b_rate_lhp, 3b_rate_lhp
  (+ analogiczne *_rhp)

Gdy split ma za mało PA → fallback do overall, a przy LHP
dodatkowo lekka korekta generyczna.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ═══════════════════════════════════════════════════════════════════════════════
# 1. CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

APP_TITLE   = "Monte Carlo Baseball"
APP_VERSION = "3.2.0"
DATA_SOURCE = "MLB Stats API · overall + vs LHP/RHP splits"

CSV_BY_SEASON = {
    2025: "Batters_2025_splits.csv",
    2026: "Batters_2026_splits.csv",
}
# fallbacki, gdy nie ma pliku *_splits
CSV_FALLBACK = {
    2025: "Batters_2025.csv",
    2026: "Batters_2026.csv",
}

PROJECTION_PA_THRESHOLD = 100
MIN_SPLIT_PA            = 15   # poniżej → nie ufamy splitowi
_N_GAMES_DEFAULT_MIXED  = 300
_N_GAMES_DEFAULT_SAME   = 200
_N_GAMES_DEFAULT_FULL   = 1000
_N_SENS_POINTS          = 14
_N_GAMES_SENS           = 150

_PALETTE = ["#4C8AC6", "#E07B54", "#5DBB8A", "#C67BB5", "#E0C454", "#7BC6C6"]

_SAVANT_ALIASES = {
    "b_pa": "pa", "b_ab": "ab", "b_hit": "hit",
    "b_single": "single", "b_double": "double", "b_triple": "triple",
    "b_home_run": "home_run", "b_strikeout": "strikeout", "b_walk": "walk",
    "b_k_percent": "k_percent", "b_bb_percent": "bb_percent",
}

TEAMS: dict[str, str] = {
    "New York Yankees": "NYY", "New York Mets": "NYM",
    "Los Angeles Dodgers": "LAD", "Philadelphia Phillies": "PHI",
    "Atlanta Braves": "ATL", "Houston Astros": "HOU",
    "Texas Rangers": "TEX", "Cleveland Guardians": "CLE",
    "St. Louis Cardinals": "STL", "Chicago Cubs": "CHC",
    "Baltimore Orioles": "BAL", "Toronto Blue Jays": "TOR",
    "Boston Red Sox": "BOS", "San Diego Padres": "SD",
    "Seattle Mariners": "SEA", "Minnesota Twins": "MIN",
    "Detroit Tigers": "DET", "Kansas City Royals": "KC",
    "Tampa Bay Rays": "TB", "Athletics": "OAK",
    "Miami Marlins": "MIA", "Colorado Rockies": "COL",
    "Arizona Diamondbacks": "ARI", "Cincinnati Reds": "CIN",
    "Pittsburgh Pirates": "PIT", "Milwaukee Brewers": "MIL",
    "Washington Nationals": "WSH", "San Francisco Giants": "SF",
    "Los Angeles Angels": "LAA", "Chicago White Sox": "CWS",
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. i18n (skrócone — te same klucze co wcześniej)
# ═══════════════════════════════════════════════════════════════════════════════

LANGUAGES = {
    "English": "en", "Polski": "pl", "Español": "es",
    "Français": "fr", "日本語": "ja",
}

_TR: dict[str, dict[str, str]] = {
    "app_subtitle": {
        "en": "Overall + vs LHP/RHP splits · Monte Carlo",
        "pl": "Overall + splity vs LHP/RHP · Monte Carlo",
        "es": "Overall + splits LHP/RHP · Monte Carlo",
        "fr": "Overall + splits LHP/RHP · Monte Carlo",
        "ja": "総合+対LHP/RHP・モンテカルロ",
    },
    "lang_label": {"en": "Language", "pl": "Język", "es": "Idioma", "fr": "Langue", "ja": "言語"},
    "season": {"en": "Season", "pl": "Sezon", "es": "Temporada", "fr": "Saison", "ja": "シーズン"},
    "sec_sim": {"en": "⚙ Simulation", "pl": "⚙ Symulacja", "es": "⚙ Simulación",
                "fr": "⚙ Simulation", "ja": "⚙ シミュレーション"},
    "sec_team": {"en": "🏟 Team Mode", "pl": "🏟 Tryb drużynowy", "es": "🏟 Modo equipo",
                 "fr": "🏟 Mode équipe", "ja": "🏟 チームモード"},
    "sec_player": {"en": "➕ Custom Player", "pl": "➕ Własny gracz", "es": "➕ Jugador",
                   "fr": "➕ Joueur", "ja": "➕ カスタム選手"},
    "sec_lineup_io": {"en": "💾 Save / Load Lineup", "pl": "💾 Zapisz / Wczytaj lineup",
                      "es": "💾 Guardar / Cargar", "fr": "💾 Sauver / Charger", "ja": "💾 保存 / 読込"},
    "era_plus": {"en": "Opposing ERA+", "pl": "ERA+ przeciwnika", "es": "ERA+ rival",
                 "fr": "ERA+ adverse", "ja": "相手ERA+"},
    "era_plus_help": {
        "en": "100 = average. 150 = ace. 70 = replacement.",
        "pl": "100 = przeciętny. 150 = as. 70 = zastępczy.",
        "es": "100 = promedio. 150 = as. 70 = reemplazo.",
        "fr": "100 = moyen. 150 = as. 70 = remplaçant.",
        "ja": "100=平均、150=エース、70=控え",
    },
    "min_pa": {"en": "Minimum PA", "pl": "Min. PA", "es": "PA mínimo", "fr": "PA minimum", "ja": "最低PA"},
    "ultra_fast": {"en": "Ultra-fast mode", "pl": "Tryb szybki", "es": "Modo rápido",
                   "fr": "Mode rapide", "ja": "高速モード"},
    "allow_dup": {
        "en": "Allow duplicate players in lineup",
        "pl": "Pozwól na powtórzenia graczy w lineupie",
        "es": "Permitir jugadores repetidos",
        "fr": "Autoriser les doublons",
        "ja": "打順で選手の重複を許可",
    },
    "allow_dup_help": {
        "en": "Off = unique 1–9. On = same batter in multiple slots.",
        "pl": "Wyłączone = unikalni 1–9. Włączone = ten sam gracz w wielu slotach.",
        "es": "Off = únicos. On = se puede repetir.",
        "fr": "Off = uniques. On = doublons autorisés.",
        "ja": "OFF=重複なし / ON=重複可",
    },
    "lhp_pct": {
        "en": "% of PAs vs LHP (left-handed pitchers)",
        "pl": "% pojedynków vs LHP (leworęczni miotacze)",
        "es": "% de PAs vs LHP",
        "fr": "% des PAs vs LHP",
        "ja": "対LHPのPA割合",
    },
    "lhp_help": {
        "en": "Uses real splits when available. Remainder = vs RHP.",
        "pl": "Używa prawdziwych splitów, gdy są w CSV. Reszta = vs RHP.",
        "es": "Usa splits reales si existen. Resto = vs RHP.",
        "fr": "Utilise les vrais splits si dispo. Reste = vs RHP.",
        "ja": "CSVに実スプリットがあれば使用。残りは対RHP",
    },
    "team_mode": {"en": "Restrict to one team", "pl": "Tylko jedna drużyna",
                  "es": "Un solo equipo", "fr": "Une seule équipe", "ja": "1チームに限定"},
    "select_team": {"en": "Select team", "pl": "Wybierz drużynę", "es": "Equipo",
                    "fr": "Équipe", "ja": "チーム"},
    "load_lineup": {"en": "Load top-9 lineup by PA", "pl": "Wczytaj top-9 po PA",
                    "es": "Cargar top-9 por PA", "fr": "Charger top-9 PA", "ja": "PA上位9人を読込"},
    "btn_load": {"en": "Load", "pl": "Wczytaj", "es": "Cargar", "fr": "Charger", "ja": "読込"},
    "btn_reset": {"en": "Reset lineup", "pl": "Reset lineup", "es": "Reiniciar",
                  "fr": "Réinitialiser", "ja": "リセット"},
    "player_name": {"en": "Name", "pl": "Imię i nazwisko", "es": "Nombre", "fr": "Nom", "ja": "名前"},
    "stat_level": {"en": "Stat level", "pl": "Poziom statystyk", "es": "Nivel", "fr": "Niveau", "ja": "統計レベル"},
    "level_basic": {"en": "Basic — BA / OBP / SLG", "pl": "Podstawowy — BA / OBP / SLG",
                    "es": "Básico", "fr": "Basique", "ja": "基本"},
    "level_mid": {"en": "Intermediate — + K% / HR%", "pl": "Średni — + K% / HR%",
                  "es": "Intermedio", "fr": "Intermédiaire", "ja": "中級"},
    "level_adv": {"en": "Advanced — full set", "pl": "Zaawansowany — pełny zestaw",
                  "es": "Avanzado", "fr": "Avancé", "ja": "上級"},
    "btn_add": {"en": "Add player", "pl": "Dodaj gracza", "es": "Añadir", "fr": "Ajouter", "ja": "追加"},
    "btn_save_json": {"en": "Download lineup (JSON)", "pl": "Pobierz lineup (JSON)",
                      "es": "Descargar JSON", "fr": "Télécharger JSON", "ja": "JSONダウンロード"},
    "upload_json": {"en": "Upload lineup JSON", "pl": "Wgraj lineup JSON",
                    "es": "Subir JSON", "fr": "Importer JSON", "ja": "JSONアップロード"},
    "tab_lineup": {"en": "📋 Mixed Lineup", "pl": "📋 Mieszany lineup",
                   "es": "📋 Alineación", "fr": "📋 Alignement", "ja": "📋 混合打線"},
    "tab_same": {"en": "⚔ 9× Same Batter", "pl": "⚔ 9× Ten sam",
                 "es": "⚔ 9× Mismo", "fr": "⚔ 9× Même", "ja": "⚔ 9×同一"},
    "tab_sensitivity": {"en": "📊 Sensitivity", "pl": "📊 Wrażliwość",
                        "es": "📊 Sensibilidad", "fr": "📊 Sensibilité", "ja": "📊 感度"},
    "btn_simulate": {"en": "▶ Simulate", "pl": "▶ Symuluj", "es": "▶ Simular",
                     "fr": "▶ Simuler", "ja": "▶ 実行"},
    "btn_compare": {"en": "⚔ Compare", "pl": "⚔ Porównaj", "es": "⚔ Comparar",
                    "fr": "⚔ Comparer", "ja": "⚔ 比較"},
    "btn_run_sens": {"en": "▶ Run analysis", "pl": "▶ Uruchom analizę",
                     "es": "▶ Ejecutar", "fr": "▶ Lancer", "ja": "▶ 分析"},
    "slot": {"en": "Slot", "pl": "Slot", "es": "Pos.", "fr": "Pos.", "ja": "打順"},
    "player_a": {"en": "Player A", "pl": "Gracz A", "es": "Jugador A", "fr": "Joueur A", "ja": "選手A"},
    "player_b": {"en": "Player B", "pl": "Gracz B", "es": "Jugador B", "fr": "Joueur B", "ja": "選手B"},
    "sens_player": {"en": "Player for analysis", "pl": "Gracz do analizy",
                    "es": "Jugador", "fr": "Joueur", "ja": "分析選手"},
    "spinner": {"en": "Simulating…", "pl": "Symulacja…", "es": "Simulando…",
                "fr": "Simulation…", "ja": "計算中…"},
    "rpg": {"en": "runs / game", "pl": "runów / mecz", "es": "carreras / juego",
            "fr": "points / match", "ja": "得点 / 試合"},
    "rps": {"en": "projected runs / 162", "pl": "runów / 162 mecze",
            "es": "carreras / 162", "fr": "points / 162", "ja": "162試合投影"},
    "elapsed": {"en": "Elapsed", "pl": "Czas", "es": "Tiempo", "fr": "Durée", "ja": "時間"},
    "prob_header": {"en": "Outcome probabilities", "pl": "Prawdopodobieństwa",
                    "es": "Probabilidades", "fr": "Probabilités", "ja": "確率"},
    "data_badge_act": {"en": "actual", "pl": "aktualne", "es": "real", "fr": "réel", "ja": "実績"},
    "data_badge_proj": {"en": "proj", "pl": "proj", "es": "proy", "fr": "proj", "ja": "予測"},
    "data_badge_split": {"en": "split", "pl": "split", "es": "split", "fr": "split", "ja": "スプリット"},
    "sens_note": {
        "en": "9× same batter; other stats fixed; ERA+ from sidebar.",
        "pl": "9× ten sam pałkarz; reszta stała; ERA+ z sidebara.",
        "es": "9× mismo bateador; resto fijo.",
        "fr": "9× même frappeur; reste fixe.",
        "ja": "9×同一打者、他固定",
    },
    "computing": {"en": "Computing…", "pl": "Obliczanie…", "es": "Calculando…",
                  "fr": "Calcul…", "ja": "計算中…"},
    "tornado_title": {"en": "Sensitivity tornado", "pl": "Tornado wrażliwości",
                      "es": "Tornado", "fr": "Tornade", "ja": "感度トルネード"},
    "obp_slg_title": {"en": "OBP vs SLG (equal Δ)", "pl": "OBP vs SLG (równy Δ)",
                      "es": "OBP vs SLG", "fr": "OBP vs SLG", "ja": "OBP vs SLG"},
    "obp_line": {"en": "OBP (via BB%)", "pl": "OBP (BB%)", "es": "OBP", "fr": "OBP", "ja": "OBP"},
    "slg_line": {"en": "SLG (via HR%)", "pl": "SLG (HR%)", "es": "SLG", "fr": "SLG", "ja": "SLG"},
    "delta_label": {"en": "+Δ", "pl": "+Δ", "es": "+Δ", "fr": "+Δ", "ja": "+Δ"},
    "detail_curves": {"en": "Per-stat curves", "pl": "Krzywe per stat", "es": "Curvas",
                      "fr": "Courbes", "ja": "統計別曲線"},
    "base_rpg": {"en": "Base RPG", "pl": "Bazowe RPG", "es": "RPG base", "fr": "RPG base", "ja": "ベースRPG"},
    "no_csv": {"en": "CSV not found — sample data.", "pl": "Brak CSV — dane przykładowe.",
               "es": "CSV no encontrado.", "fr": "CSV introuvable.", "ja": "CSVなし — サンプル"},
    "added": {"en": "Added", "pl": "Dodano", "es": "Añadido", "fr": "Ajouté", "ja": "追加"},
    "lineup_loaded": {"en": "Lineup loaded", "pl": "Lineup wczytany", "es": "Cargada",
                      "fr": "Chargé", "ja": "読込完了"},
    "lineup_reset": {"en": "Lineup reset", "pl": "Lineup zresetowany", "es": "Reiniciada",
                     "fr": "Réinitialisé", "ja": "リセット"},
    "team_not_found": {
        "en": "Not enough players for this team (try lower min PA).",
        "pl": "Za mało graczy w drużynie (obniż min PA).",
        "es": "Pocos jugadores.", "fr": "Pas assez de joueurs.", "ja": "選手不足",
    },
    "proj_note": {
        "en": "Using xStats / small-sample projection (PA < 100)",
        "pl": "Projekcja / mała próbka (PA < 100)",
        "es": "Proyección (PA < 100)", "fr": "Projection (PA < 100)", "ja": "予測 (PA < 100)",
    },
    "upload_ok": {"en": "Lineup imported.", "pl": "Lineup zaimportowany.",
                  "es": "Importado.", "fr": "Importé.", "ja": "インポート完了"},
    "upload_err": {"en": "Could not parse file.", "pl": "Błąd pliku.",
                   "es": "Error de archivo.", "fr": "Erreur fichier.", "ja": "解析エラー"},
}


def t(key: str) -> str:
    lang = st.session_state.get("lang", "en")
    return _TR.get(key, {}).get(lang) or _TR.get(key, {}).get("en", key)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def _to_frac(series: pd.Series, default: float = 0.0) -> pd.Series:
    """k_percent bywa 22.5 albo 0.225 → zawsze ułamek 0–1."""
    s = pd.to_numeric(series, errors="coerce")
    med = s.median(skipna=True)
    if pd.notna(med) and med > 1.0:
        s = s / 100.0
    return s.fillna(default)


@st.cache_data(show_spinner=False)
def load_batters_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.str.strip().str.lower()

    for old, new in _SAVANT_ALIASES.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    # Name
    if "last_name, first_name" in df.columns:
        df["Name"] = df["last_name, first_name"].astype(str).str.strip()
    elif "name" in df.columns:
        df["Name"] = df["name"].astype(str).str.strip()
    elif "last_name" in df.columns and "first_name" in df.columns:
        df["Name"] = (
            df["last_name"].astype(str).str.strip()
            + ", "
            + df["first_name"].astype(str).str.strip()
        )
    else:
        df["Name"] = df.iloc[:, 0].astype(str).str.strip()

    # numeric overall + split columns
    num_candidates = [
        "pa", "ab", "single", "double", "triple", "home_run",
        "k_percent", "bb_percent", "babip", "b_hit_by_pitch",
        "k_pct", "bb_pct", "hr_pct", "hbp_pct",
        "1b_rate", "2b_rate", "3b_rate",
        "xba", "xslg", "xobp",
        # splits
        "pa_lhp", "ab_lhp", "single_lhp", "double_lhp", "triple_lhp", "home_run_lhp",
        "k_percent_lhp", "bb_percent_lhp", "babip_lhp", "hbp_lhp",
        "hr_pct_lhp", "hbp_pct_lhp", "1b_rate_lhp", "2b_rate_lhp", "3b_rate_lhp",
        "pa_rhp", "ab_rhp", "single_rhp", "double_rhp", "triple_rhp", "home_run_rhp",
        "k_percent_rhp", "bb_percent_rhp", "babip_rhp", "hbp_rhp",
        "hr_pct_rhp", "hbp_pct_rhp", "1b_rate_rhp", "2b_rate_rhp", "3b_rate_rhp",
    ]
    for col in num_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "pa" not in df.columns:
        df["pa"] = 0.0
    df["PA"] = df["pa"].fillna(0).clip(lower=1)

    # overall rates
    if "k_pct" in df.columns and df["k_pct"].notna().any():
        df["K_pct"] = _to_frac(df["k_pct"], 0.22)
    elif "k_percent" in df.columns:
        df["K_pct"] = _to_frac(df["k_percent"], 0.22)
    else:
        df["K_pct"] = 0.22

    if "bb_pct" in df.columns and df["bb_pct"].notna().any():
        df["BB_pct"] = _to_frac(df["bb_pct"], 0.08)
    elif "bb_percent" in df.columns:
        df["BB_pct"] = _to_frac(df["bb_percent"], 0.08)
    else:
        df["BB_pct"] = 0.08

    pa = df["PA"]
    if "hr_pct" in df.columns and df["hr_pct"].notna().any():
        df["HR_pct"] = df["hr_pct"].fillna(0.03).clip(0, 0.2)
    elif "home_run" in df.columns:
        df["HR_pct"] = (df["home_run"].fillna(0) / pa).clip(0, 0.2)
    else:
        df["HR_pct"] = 0.03

    if "hbp_pct" in df.columns and df["hbp_pct"].notna().any():
        df["HBP_pct"] = df["hbp_pct"].fillna(0.01).clip(0, 0.1)
    elif "b_hit_by_pitch" in df.columns:
        df["HBP_pct"] = (df["b_hit_by_pitch"].fillna(0) / pa).clip(0, 0.1)
    else:
        df["HBP_pct"] = 0.01

    df["BABIP"] = df["babip"].fillna(0.290) if "babip" in df.columns else 0.290

    for side, prefix in [("overall", ""), ("lhp", "_lhp"), ("rhp", "_rhp")]:
        if prefix == "":
            s_col, d_col, t_col = "single", "double", "triple"
            r1, r2, r3 = "1B_rate", "2B_rate", "3B_rate"
        else:
            s_col, d_col, t_col = f"single{prefix}", f"double{prefix}", f"triple{prefix}"
            r1, r2, r3 = f"1B_rate{prefix}", f"2B_rate{prefix}", f"3B_rate{prefix}"
            # już mogą być policzone w CSV
            if r1.lower() in df.columns:
                df[r1] = df[r1.lower()]
                df[r2] = df[r2.lower()]
                df[r3] = df[r3.lower()]
                continue
        if s_col in df.columns:
            s = df[s_col].fillna(0).clip(lower=0)
            d = df[d_col].fillna(0).clip(lower=0) if d_col in df.columns else 0
            t3 = df[t_col].fillna(0).clip(lower=0) if t_col in df.columns else 0
            non_hr = (s + d + t3).clip(lower=1)
            df[r1] = s / non_hr
            df[r2] = d / non_hr
            df[r3] = t3 / non_hr
        elif prefix == "":
            df["1B_rate"] = 0.70
            df["2B_rate"] = 0.20
            df["3B_rate"] = 0.05

    # znormalizuj nazwy split rate z CSV (lowercase → canonical)
    rename_split = {}
    for side in ("lhp", "rhp"):
        for src, dst in [
            (f"k_percent_{side}", f"K_pct_{side}"),
            (f"bb_percent_{side}", f"BB_pct_{side}"),
            (f"babip_{side}", f"BABIP_{side}"),
            (f"hr_pct_{side}", f"HR_pct_{side}"),
            (f"hbp_pct_{side}", f"HBP_pct_{side}"),
            (f"1b_rate_{side}", f"1B_rate_{side}"),
            (f"2b_rate_{side}", f"2B_rate_{side}"),
            (f"3b_rate_{side}", f"3B_rate_{side}"),
            (f"pa_{side}", f"PA_{side}"),
        ]:
            if src in df.columns:
                rename_split[src] = dst
    df = df.rename(columns=rename_split)

    # k_percent_lhp jako 0–100 → ułamek
    for side in ("lhp", "rhp"):
        kcol = f"K_pct_{side}"
        bcol = f"BB_pct_{side}"
        if kcol in df.columns:
            df[kcol] = _to_frac(df[kcol], np.nan)
        if bcol in df.columns:
            df[bcol] = _to_frac(df[bcol], np.nan)
        # jeśli w CSV było k_percent_lhp nie przemianowane
        raw_k = f"k_percent_{side}"
        if raw_k in df.columns and kcol not in df.columns:
            df[kcol] = _to_frac(df[raw_k], np.nan)
        raw_b = f"bb_percent_{side}"
        if raw_b in df.columns and bcol not in df.columns:
            df[bcol] = _to_frac(df[raw_b], np.nan)

    # xStats fallback overall
    if all(c in df.columns for c in ("xba", "xobp", "xslg")):
        xba = df["xba"].fillna(0).clip(0.10, 0.40)
        xobp = df["xobp"].fillna(0).clip(0.15, 0.55)
        xslg = df["xslg"].fillna(0).clip(0.20, 0.80)
        xiso = (xslg - xba).clip(lower=0.0)
        df["xK_pct"] = df["K_pct"]
        df["xBB_pct"] = (xobp - xba).clip(0.02, 0.25)
        df["xHR_pct"] = (xiso * 0.35).clip(upper=0.12)
        df["xBABIP"] = (xba / (1.0 - df["K_pct"]).clip(lower=0.40)).clip(0.18, 0.42)
    else:
        df["xK_pct"] = df["K_pct"]
        df["xBB_pct"] = df["BB_pct"]
        df["xHR_pct"] = df["HR_pct"]
        df["xBABIP"] = df["BABIP"]

    # Team
    if "team" in df.columns:
        df["Team"] = (
            df["team"].astype(str).str.strip().str.upper()
            .replace({"NAN": "FA", "NONE": "FA", "": "FA", "2TM": "FA", "3TM": "FA",
                      "ATH": "OAK"})
        )
        df["Team"] = df["Team"].fillna("FA")
    else:
        df["Team"] = "FA"

    return (
        df.sort_values("PA", ascending=False)
          .drop_duplicates("Name")
          .reset_index(drop=True)
    )


def resolve_csv_path(season: int) -> str | None:
    primary = CSV_BY_SEASON.get(season, "")
    if primary and os.path.exists(primary):
        return primary
    fb = CSV_FALLBACK.get(season, "")
    if fb and os.path.exists(fb):
        return fb
    return None


_SAMPLE_DATA = pd.DataFrame({
    "Name": ["Judge, Aaron", "Ohtani, Shohei", "Soto, Juan",
             "Ramírez, José", "Witt Jr., Bobby", "Carroll, Corbin"],
    "PA": [650, 640, 680, 660, 700, 620],
    "K_pct": [0.236, 0.257, 0.160, 0.148, 0.198, 0.220],
    "BB_pct": [0.183, 0.150, 0.200, 0.099, 0.092, 0.100],
    "HR_pct": [0.078, 0.076, 0.055, 0.060, 0.046, 0.040],
    "HBP_pct": [0.012, 0.015, 0.008, 0.012, 0.008, 0.010],
    "BABIP": [0.298, 0.290, 0.300, 0.322, 0.312, 0.310],
    "1B_rate": [0.68, 0.65, 0.70, 0.68, 0.72, 0.70],
    "2B_rate": [0.22, 0.25, 0.20, 0.22, 0.20, 0.22],
    "3B_rate": [0.05, 0.05, 0.04, 0.05, 0.08, 0.08],
    "xK_pct": [0.236, 0.257, 0.160, 0.148, 0.198, 0.220],
    "xBB_pct": [0.183, 0.150, 0.200, 0.099, 0.092, 0.100],
    "xHR_pct": [0.078, 0.076, 0.055, 0.060, 0.046, 0.040],
    "xBABIP": [0.298, 0.290, 0.300, 0.322, 0.312, 0.310],
    "Team": ["NYY", "LAD", "NYM", "CLE", "KC", "ARI"],
})


def default_lineup_for_team(df: pd.DataFrame, team_abbr: str, n: int = 9) -> list[str]:
    sub = df[df["Team"] == team_abbr].sort_values("PA", ascending=False)
    return sub["Name"].head(n).tolist()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STAT DERIVATION (custom)
# ═══════════════════════════════════════════════════════════════════════════════

def _derive_hit_split(iso: float) -> tuple[float, float, float]:
    xbh = min(iso * 2.0, 0.45)
    r1 = max(0.50, 1.0 - xbh)
    r2 = xbh * 0.85
    r3 = xbh * 0.15
    tot = r1 + r2 + r3
    return r1 / tot, r2 / tot, r3 / tot


def derive_from_basic(ba: float, obp: float, slg: float) -> dict[str, Any]:
    bb_pct = max(0.02, min(obp - ba, 0.25))
    iso = max(0.0, slg - ba)
    k_pct, hr_pct = 0.220, max(0.0, min(iso * 0.35, 0.12))
    denom = max(0.01, 1.0 - k_pct - hr_pct)
    babip = float(np.clip((ba - hr_pct) / denom, 0.18, 0.42))
    r1, r2, r3 = _derive_hit_split(iso)
    return dict(K_pct=k_pct, BB_pct=bb_pct, HBP_pct=0.008,
                HR_pct=hr_pct, BABIP=babip, r1=r1, r2=r2, r3=r3)


def derive_from_intermediate(
    ba: float, obp: float, slg: float, k_pct: float, hr_pct: float
) -> dict[str, Any]:
    bb_pct = max(0.02, min(obp - ba, 0.25))
    iso = max(0.0, slg - ba)
    denom = max(0.01, 1.0 - k_pct - hr_pct)
    babip = float(np.clip((ba - hr_pct) / denom, 0.18, 0.42))
    r1, r2, r3 = _derive_hit_split(iso)
    return dict(K_pct=k_pct, BB_pct=bb_pct, HBP_pct=0.008,
                HR_pct=hr_pct, BABIP=babip, r1=r1, r2=r2, r3=r3)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PROBABILITY MODEL
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def get_batter_probs(
    K: float, BB: float, HBP: float, HR: float,
    babip: float, r1: float, r2: float, r3: float,
    era_plus: int,
) -> np.ndarray:
    K = float(np.clip(K, 0.0, 0.60))
    BB = float(np.clip(BB, 0.0, 0.30))
    HBP = float(np.clip(HBP, 0.0, 0.05))
    HR = float(np.clip(HR, 0.0, 0.15))
    babip = float(np.clip(babip, 0.10, 0.45))

    q = era_plus / 100.0
    pK = float(np.clip(K * (1.0 + 0.5 * (q - 1.0)), 0.0, 0.55))
    pBB = max(0.0, BB * (1.0 - 0.4 * (q - 1.0)))
    pHBP = max(0.0, HBP * (1.0 - 0.4 * (q - 1.0)))
    pHR = max(0.0, HR * (1.0 - 0.4 * (q - 1.0)))
    adj_b = float(np.clip(babip * (1.0 - 0.25 * (q - 1.0)), 0.15, 0.40))

    total_non = pK + pBB + pHBP + pHR
    if total_non > 0.65:
        s = 0.65 / total_non
        pK *= s
        pBB *= s
        pHBP *= s
        pHR *= s

    p_c = max(0.0, 1.0 - pK - pBB - pHBP - pHR)
    hits = adj_b * p_c
    probs = np.array(
        [p_c - hits + pK, pBB + pHBP, hits * r1, hits * r2, hits * r3, pHR],
        dtype=np.float64,
    )
    probs = np.clip(probs, 0.0, None)
    s = probs.sum()
    return probs / s if s > 0 else np.array([0.68, 0.09, 0.13, 0.05, 0.01, 0.04])


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

def simulate_games(
    lineup_probs: np.ndarray,
    n_games: int,
    lhp_lineup_probs: np.ndarray | None = None,
    lhp_rate: float = 0.38,
) -> float:
    rng = np.random.default_rng()
    n_batters = lineup_probs.shape[0]
    cumprobs_r = np.cumsum(lineup_probs, axis=1)
    use_split = lhp_lineup_probs is not None and lhp_rate > 0
    if use_split:
        cumprobs_l = np.cumsum(lhp_lineup_probs, axis=1)

    MAX_PA = 270
    total_pa = n_games * MAX_PA
    batter_seq = np.arange(total_pa) % n_batters
    rand_pa = rng.random(total_pa)

    if use_split:
        is_lhp = rng.random(total_pa) < lhp_rate
        cp_all = np.where(
            is_lhp[:, None],
            cumprobs_l[batter_seq],
            cumprobs_r[batter_seq],
        )
    else:
        cp_all = cumprobs_r[batter_seq]

    outcomes = np.clip((cp_all < rand_pa[:, None]).sum(axis=1), 0, 5).astype(np.int32).tolist()
    total_runs = 0

    for g in range(n_games):
        base = g * MAX_PA
        pa_cursor = 0
        game_runs = 0
        for _ in range(9):
            bases = 0
            outs = 0
            while outs < 3 and pa_cursor < MAX_PA:
                res = outcomes[base + pa_cursor]
                pa_cursor += 1
                if res == 0:
                    outs += 1
                    continue
                on1, on2, on3 = bases & 1, (bases >> 1) & 1, (bases >> 2) & 1
                if res == 5:
                    game_runs += on1 + on2 + on3 + 1
                    bases = 0
                elif res == 4:
                    game_runs += on1 + on2 + on3
                    bases = 4
                elif res == 3:
                    game_runs += on2 + on3
                    bases = (on1 << 2) | 2
                elif res == 2:
                    game_runs += on3
                    bases = 1 | (on1 << 1) | (on2 << 2)
                else:
                    if on1 and on2 and on3:
                        game_runs += 1
                    elif on1 and on2:
                        bases = 7
                    elif on1:
                        bases = 3
                    else:
                        bases |= 1
        total_runs += game_runs
    return total_runs / n_games


# ═══════════════════════════════════════════════════════════════════════════════
# 7. HELPERS — overall / LHP / RHP stats z wiersza
# ═══════════════════════════════════════════════════════════════════════════════

def _sg(row: pd.Series, col: str, default: float) -> float:
    val = row.get(col)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _use_projection(row: pd.Series) -> bool:
    return float(_sg(row, "PA", 0)) < PROJECTION_PA_THRESHOLD


def _has_real_split(row: pd.Series, side: str) -> bool:
    """side = 'lhp' | 'rhp'."""
    pa = _sg(row, f"PA_{side}", 0) or _sg(row, f"pa_{side}", 0)
    k = row.get(f"K_pct_{side}")
    if pa < MIN_SPLIT_PA:
        return False
    if k is None or (isinstance(k, float) and np.isnan(k)):
        return False
    return True


def _stat_tuple_overall(row: pd.Series) -> tuple[float, ...]:
    proj = _use_projection(row)
    k = _sg(row, "xK_pct" if proj else "K_pct", 0.22)
    bb = _sg(row, "xBB_pct" if proj else "BB_pct", 0.08)
    hbp = _sg(row, "HBP_pct", 0.01)
    hr = _sg(row, "xHR_pct" if proj else "HR_pct", 0.03)
    bab = _sg(row, "xBABIP" if proj else "BABIP", 0.290)
    r1 = _sg(row, "1B_rate", 0.70)
    r2 = _sg(row, "2B_rate", 0.20)
    r3 = _sg(row, "3B_rate", 0.05)
    return k, bb, hbp, hr, bab, r1, r2, r3


def _stat_tuple_side(row: pd.Series, side: str) -> tuple[float, ...]:
    """
    Prawdziwy split jeśli jest; inaczej overall.
    Dla LHP bez splitu: lekka korekta generyczna na overall.
    """
    if _has_real_split(row, side):
        k = _sg(row, f"K_pct_{side}", 0.22)
        bb = _sg(row, f"BB_pct_{side}", 0.08)
        hbp = _sg(row, f"HBP_pct_{side}", _sg(row, "HBP_pct", 0.01))
        hr = _sg(row, f"HR_pct_{side}", 0.03)
        bab = _sg(row, f"BABIP_{side}", 0.290)
        r1 = _sg(row, f"1B_rate_{side}", _sg(row, "1B_rate", 0.70))
        r2 = _sg(row, f"2B_rate_{side}", _sg(row, "2B_rate", 0.20))
        r3 = _sg(row, f"3B_rate_{side}", _sg(row, "3B_rate", 0.05))
        return k, bb, hbp, hr, bab, r1, r2, r3

    k, bb, hbp, hr, bab, r1, r2, r3 = _stat_tuple_overall(row)
    if side == "lhp":
        # generyczny RHH-vs-LHP, gdy brak prawdziwego splitu
        k *= 1.08
        bb *= 0.95
        hr *= 0.90
        bab *= 0.97
    return k, bb, hbp, hr, bab, r1, r2, r3


def build_probs_rhp(row: pd.Series, era_plus: int) -> np.ndarray:
    k, bb, hbp, hr, bab, r1, r2, r3 = _stat_tuple_side(row, "rhp")
    return get_batter_probs(k, bb, hbp, hr, bab, r1, r2, r3, era_plus)


def build_probs_lhp(row: pd.Series, era_plus: int) -> np.ndarray:
    k, bb, hbp, hr, bab, r1, r2, r3 = _stat_tuple_side(row, "lhp")
    return get_batter_probs(k, bb, hbp, hr, bab, r1, r2, r3, era_plus)


def build_probs(row: pd.Series, era_plus: int) -> np.ndarray:
    """Domyślnie vs RHP (większość PA w lidze)."""
    return build_probs_rhp(row, era_plus)


def prob_label(row: pd.Series, era_plus: int) -> str:
    p = build_probs_rhp(row, era_plus)
    has_l = _has_real_split(row, "lhp")
    has_r = _has_real_split(row, "rhp")
    if has_l or has_r:
        badge = f"📊 {t('data_badge_split')}"
    elif _use_projection(row):
        badge = f"🔮 {t('data_badge_proj')}"
    else:
        badge = f"✅ {t('data_badge_act')}"
    return (
        f"{badge}  ·  out {p[0]*100:.1f}% · walk/HBP {p[1]*100:.1f}% · "
        f"1B {p[2]*100:.1f}% · 2B {p[3]*100:.1f}% · "
        f"3B {p[4]*100:.1f}% · HR {p[5]*100:.1f}%"
    )


def split_source_caption(row: pd.Series) -> str:
    parts = []
    if _has_real_split(row, "lhp"):
        parts.append(f"LHP PA={int(_sg(row, 'PA_lhp', 0) or _sg(row, 'pa_lhp', 0))}")
    else:
        parts.append("LHP: fallback")
    if _has_real_split(row, "rhp"):
        parts.append(f"RHP PA={int(_sg(row, 'PA_rhp', 0) or _sg(row, 'pa_rhp', 0))}")
    else:
        parts.append("RHP: overall")
    return " · ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. SENSITIVITY + CHARTS (bez zmian logiki)
# ═══════════════════════════════════════════════════════════════════════════════

_SENS_RANGES = {
    "K%": ("K_pct", 0.08, 0.38),
    "BB%": ("BB_pct", 0.03, 0.18),
    "HR%": ("HR_pct", 0.005, 0.09),
    "BABIP": ("BABIP", 0.220, 0.370),
    "2B rate": ("2B_rate", 0.08, 0.30),
}


def _base_stats(row: pd.Series) -> dict[str, float]:
    return {
        "K_pct": _sg(row, "K_pct", 0.22),
        "BB_pct": _sg(row, "BB_pct", 0.08),
        "HBP_pct": _sg(row, "HBP_pct", 0.01),
        "HR_pct": _sg(row, "HR_pct", 0.03),
        "BABIP": _sg(row, "BABIP", 0.290),
        "1B_rate": _sg(row, "1B_rate", 0.70),
        "2B_rate": _sg(row, "2B_rate", 0.20),
        "3B_rate": _sg(row, "3B_rate", 0.05),
    }


def _rpg_override(stats: dict, era_plus: int, n_games: int, **kw) -> float:
    s = {**stats, **kw}
    r1, r2, r3 = s["1B_rate"], s["2B_rate"], s["3B_rate"]
    tot = max(r1 + r2 + r3, 1e-9)
    p = get_batter_probs(
        s["K_pct"], s["BB_pct"], s["HBP_pct"], s["HR_pct"],
        s["BABIP"], r1 / tot, r2 / tot, r3 / tot, era_plus,
    )
    return simulate_games(np.array([p] * 9, dtype=np.float64), n_games)


def compute_sensitivity(row: pd.Series, era_plus: int, progress_cb=None):
    base = _base_stats(row)
    total_steps = 1 + 2 * len(_SENS_RANGES) + _N_SENS_POINTS * 2 + _N_SENS_POINTS * len(_SENS_RANGES)
    step = [0]

    def _tick():
        step[0] += 1
        if progress_cb:
            progress_cb(step[0] / total_steps)

    base_rpg = _rpg_override(base, era_plus, _N_GAMES_SENS)
    _tick()
    tornado: dict[str, tuple] = {}
    for label, (col, lo, hi) in _SENS_RANGES.items():
        lo_c, hi_c = min(lo, base[col]), max(hi, base[col])
        rpg_lo = _rpg_override(base, era_plus, _N_GAMES_SENS, **{col: lo_c})
        _tick()
        rpg_hi = _rpg_override(base, era_plus, _N_GAMES_SENS, **{col: hi_c})
        _tick()
        tornado[label] = (rpg_lo, base_rpg, rpg_hi, lo_c, base[col], hi_c)

    deltas = np.linspace(0.0, 0.08, _N_SENS_POINTS)
    obp_curve, slg_curve = [], []
    for d in deltas:
        obp_curve.append(_rpg_override(base, era_plus, _N_GAMES_SENS, BB_pct=min(base["BB_pct"] + d, 0.30)))
        _tick()
    for d in deltas:
        slg_curve.append(_rpg_override(base, era_plus, _N_GAMES_SENS, HR_pct=min(base["HR_pct"] + d / 3.0, 0.15)))
        _tick()

    detail: dict[str, tuple] = {}
    for label, (col, lo, hi) in _SENS_RANGES.items():
        lo_c, hi_c = min(lo, base[col]), max(hi, base[col])
        xs = np.linspace(lo_c, hi_c, _N_SENS_POINTS)
        rpgs = []
        for x in xs:
            rpgs.append(_rpg_override(base, era_plus, _N_GAMES_SENS, **{col: float(x)}))
            _tick()
        detail[label] = (xs.tolist(), rpgs)
    return base_rpg, tornado, deltas.tolist(), obp_curve, slg_curve, detail


_CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="white", family="Inter, Arial, sans-serif"),
    margin=dict(l=80, r=20, t=28, b=44),
)


def _tornado_chart(tornado: dict, base_rpg: float) -> go.Figure:
    items = sorted(tornado.items(), key=lambda kv: abs(kv[1][2] - kv[1][0]))
    labels = [k for k, _ in items]
    lo_rpgs = [v[0] for _, v in items]
    hi_rpgs = [v[2] for _, v in items]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=[r - base_rpg for r in lo_rpgs], base=[base_rpg] * len(labels),
        orientation="h", name="Low", marker_color=_PALETTE[0],
        hovertemplate="%{base:.2f} RPG (low)<extra>%{y}</extra>",
    ))
    fig.add_trace(go.Bar(
        y=labels, x=[r - base_rpg for r in hi_rpgs], base=[base_rpg] * len(labels),
        orientation="h", name="High", marker_color=_PALETTE[1],
        hovertemplate="%{base:.2f} RPG (high)<extra>%{y}</extra>",
    ))
    fig.add_vline(x=base_rpg, line_dash="dot", line_color="rgba(255,255,255,0.6)", line_width=1.5)
    fig.update_layout(**_CHART_LAYOUT, barmode="overlay", xaxis_title=t("rpg"),
                      yaxis_title="", height=340,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
    return fig


def _obp_slg_chart(deltas: list, obp_curve: list, slg_curve: list) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=deltas, y=obp_curve, mode="lines+markers", name=t("obp_line"),
        line=dict(color=_PALETTE[0], width=2),
        hovertemplate="Δ=+%{x:.3f} → %{y:.2f} RPG<extra>OBP</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=deltas, y=slg_curve, mode="lines+markers", name=t("slg_line"),
        line=dict(color=_PALETTE[1], width=2, dash="dash"),
        hovertemplate="Δ=+%{x:.3f} → %{y:.2f} RPG<extra>SLG</extra>",
    ))
    fig.update_layout(**_CHART_LAYOUT, xaxis_title=t("delta_label"), yaxis_title=t("rpg"),
                      height=320, legend=dict(orientation="h", yanchor="bottom", y=1.02))
    return fig


def _detail_chart(detail: dict) -> go.Figure:
    fig = go.Figure()
    for i, (label, (xs, rpgs)) in enumerate(detail.items()):
        fig.add_trace(go.Scatter(
            x=xs, y=rpgs, mode="lines+markers", name=label,
            line=dict(color=_PALETTE[i % len(_PALETTE)], width=2),
            hovertemplate=f"{label}=%{{x:.3f}} → %{{y:.2f}} RPG<extra></extra>",
        ))
    fig.update_layout(**_CHART_LAYOUT, xaxis_title="Stat value", yaxis_title=t("rpg"),
                      height=360, legend=dict(orientation="h", yanchor="bottom", y=1.02))
    return fig


def _lineup_to_json(lineup: list[str]) -> str:
    return json.dumps({"version": "3.2", "lineup": lineup}, ensure_ascii=False, indent=2)


def _json_to_lineup(raw: bytes) -> list[str] | None:
    try:
        data = json.loads(raw.decode("utf-8"))
        lineup = data.get("lineup", [])
        if isinstance(lineup, list) and len(lineup) == 9:
            return lineup
    except Exception:
        pass
    return None


def _apply_lineup(names: list[str], all_players: list[str]) -> None:
    for i, name in enumerate(names):
        if name in all_players:
            st.session_state[f"slot{i}"] = name


# ═══════════════════════════════════════════════════════════════════════════════
# 9. APP LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title=APP_TITLE, page_icon="⚾", layout="wide", initial_sidebar_state="expanded"
)

lang_names = list(LANGUAGES.keys())
lang_idx = lang_names.index(
    next(k for k, v in LANGUAGES.items() if v == st.session_state.get("lang", "en"))
)
chosen_lang = st.sidebar.selectbox(
    t("lang_label"), lang_names, index=lang_idx, key="lang_selector"
)
st.session_state["lang"] = LANGUAGES[chosen_lang]

st.title(f"⚾ {APP_TITLE}")
st.caption(t("app_subtitle"))

# ── Season + data ─────────────────────────────────────────────────────────────
season = st.sidebar.selectbox(t("season"), [2026, 2025], index=0, key="season_sel")
csv_path = resolve_csv_path(season)

if (
    "players_df" not in st.session_state
    or st.session_state.get("loaded_season") != season
    or st.session_state.get("loaded_path") != csv_path
):
    try:
        if csv_path:
            st.session_state.players_df = load_batters_csv(csv_path)
            st.session_state.loaded_season = season
            st.session_state.loaded_path = csv_path
        else:
            raise FileNotFoundError("no csv")
    except FileNotFoundError:
        st.info(t("no_csv") + f" (szukano {CSV_BY_SEASON.get(season)})")
        st.session_state.players_df = _SAMPLE_DATA.copy()
        st.session_state.loaded_season = season
        st.session_state.loaded_path = None
    except Exception as e:
        st.warning(f"⚠️ CSV: {type(e).__name__}: {e}. Sample data.")
        st.session_state.players_df = _SAMPLE_DATA.copy()
        st.session_state.loaded_season = season
        st.session_state.loaded_path = None

_df_all: pd.DataFrame = st.session_state.players_df

# ── Simulation controls ───────────────────────────────────────────────────────
st.sidebar.markdown(f"### {t('sec_sim')}")
era_plus = st.sidebar.slider(t("era_plus"), 70, 150, 100, help=t("era_plus_help"))
min_pa = st.sidebar.slider(t("min_pa"), 0, 700, 0)
ultra_fast = st.sidebar.checkbox(t("ultra_fast"), value=True)
allow_duplicates = st.sidebar.checkbox(
    t("allow_dup"), value=False, help=t("allow_dup_help")
)

st.sidebar.markdown("---")
lhp_pct = st.sidebar.slider(t("lhp_pct"), 0, 100, 38, step=1, help=t("lhp_help"))
rhp_pct = 100 - lhp_pct
st.sidebar.caption(f"**vs LHP: {lhp_pct}%** · **vs RHP: {rhp_pct}%**")
lhp_rate = lhp_pct / 100.0

n_mixed = _N_GAMES_DEFAULT_MIXED if ultra_fast else _N_GAMES_DEFAULT_FULL
n_same = _N_GAMES_DEFAULT_SAME if ultra_fast else _N_GAMES_DEFAULT_FULL // 2

# ile graczy ma prawdziwe splity
n_split_l = int(_df_all.apply(lambda r: _has_real_split(r, "lhp"), axis=1).sum()) if len(_df_all) else 0
n_split_r = int(_df_all.apply(lambda r: _has_real_split(r, "rhp"), axis=1).sum()) if len(_df_all) else 0

# ── Team mode ─────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown(f"### {t('sec_team')}")
team_mode = st.sidebar.checkbox(t("team_mode"), value=False)
selected_team_abbr: str | None = None
if team_mode:
    team_names = ["—"] + list(TEAMS.keys())
    chosen_team = st.sidebar.selectbox(t("select_team"), team_names, key="chosen_team")
    if chosen_team != "—":
        selected_team_abbr = TEAMS[chosen_team]

lineup_options = {"—": None}
for full_name, abbr in TEAMS.items():
    lineup_options[full_name] = abbr

example_choice = st.sidebar.selectbox(
    t("load_lineup"), list(lineup_options.keys()), key="example_lineup_sel"
)
if st.sidebar.button(t("btn_load"), key="btn_load_lineup"):
    abbr = lineup_options.get(example_choice)
    if abbr:
        pool = _df_all[_df_all["PA"] >= min_pa]
        names = default_lineup_for_team(pool, abbr, 9)
        all_names = sorted(pool["Name"].unique().tolist())
        if len(names) < 9:
            st.sidebar.warning(t("team_not_found") + f" ({len(names)}/9)")
        else:
            _apply_lineup(names, all_names)
            st.sidebar.success(t("lineup_loaded") + f" — {abbr}")
        st.rerun()

if st.sidebar.button(t("btn_reset"), key="btn_reset_lineup"):
    for i in range(9):
        st.session_state.pop(f"slot{i}", None)
    st.sidebar.info(t("lineup_reset"))
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(f"📂 {DATA_SOURCE}")
st.sidebar.caption(f"v{APP_VERSION} · sezon {season} · {len(_df_all)} graczy")
st.sidebar.caption(f"Splity LHP: {n_split_l} · RHP: {n_split_r}")
if csv_path:
    st.sidebar.caption(f"📄 {csv_path}")

# ── Custom player ─────────────────────────────────────────────────────────────
with st.sidebar.expander(t("sec_player")):
    new_name = st.text_input(t("player_name"), "Custom Player", key="new_player_name")
    level_map = {
        t("level_basic"): "basic",
        t("level_mid"): "mid",
        t("level_adv"): "adv",
    }
    level_key = st.radio(
        t("stat_level"), list(level_map.keys()), horizontal=False, key="custom_level"
    )
    level = level_map[level_key]

    if level == "basic":
        ba = st.slider("BA", 0.150, 0.400, 0.260, 0.001, key="c_ba")
        obp = st.slider("OBP", 0.200, 0.500, 0.330, 0.001, key="c_obp")
        slg = st.slider("SLG", 0.250, 0.700, 0.420, 0.001, key="c_slg")
        derived = derive_from_basic(ba, obp, slg)
    elif level == "mid":
        ba = st.slider("BA", 0.150, 0.400, 0.260, 0.001, key="c_ba2")
        obp = st.slider("OBP", 0.200, 0.500, 0.330, 0.001, key="c_obp2")
        slg = st.slider("SLG", 0.250, 0.700, 0.420, 0.001, key="c_slg2")
        k_pct = st.slider("K%", 0.05, 0.50, 0.22, 0.001, key="c_k2")
        hr_pct = st.slider("HR%", 0.00, 0.12, 0.03, 0.001, key="c_hr2")
        derived = derive_from_intermediate(ba, obp, slg, k_pct, hr_pct)
    else:
        derived = {
            "K_pct": st.slider("K%", 0.00, 0.50, 0.22, 0.001, key="c_k3"),
            "BB_pct": st.slider("BB%", 0.00, 0.30, 0.08, 0.001, key="c_bb3"),
            "HR_pct": st.slider("HR%", 0.00, 0.15, 0.03, 0.001, key="c_hr3"),
            "BABIP": st.slider("BABIP", 0.200, 0.400, 0.300, 0.001, key="c_bab3"),
            "HBP_pct": st.slider("HBP%", 0.00, 0.05, 0.01, 0.001, key="c_hbp3"),
            "r1": st.slider("1B rate", 0.50, 0.90, 0.70, 0.01, key="c_r1"),
            "r2": st.slider("2B rate", 0.05, 0.35, 0.20, 0.01, key="c_r2"),
            "r3": st.slider("3B rate", 0.00, 0.15, 0.05, 0.01, key="c_r3"),
        }

    if st.button(t("btn_add"), key="btn_add_player"):
        r1 = derived.get("r1", 0.70)
        r2 = derived.get("r2", 0.20)
        r3 = derived.get("r3", 0.05)
        tot = r1 + r2 + r3
        new_row = pd.DataFrame([{
            "Name": new_name, "PA": 600,
            "K_pct": derived["K_pct"], "BB_pct": derived["BB_pct"],
            "HR_pct": derived["HR_pct"], "HBP_pct": derived.get("HBP_pct", 0.008),
            "BABIP": derived["BABIP"], "Team": "FA",
            "1B_rate": r1 / tot, "2B_rate": r2 / tot, "3B_rate": r3 / tot,
            "xK_pct": derived["K_pct"], "xBB_pct": derived["BB_pct"],
            "xHR_pct": derived["HR_pct"], "xBABIP": derived["BABIP"],
        }])
        st.session_state.players_df = pd.concat(
            [st.session_state.players_df, new_row], ignore_index=True
        )
        st.success(f"{t('added')}: {new_name}")
        st.rerun()

# ── Save / load ───────────────────────────────────────────────────────────────
with st.sidebar.expander(t("sec_lineup_io")):
    _all_for_export = sorted(
        _df_all[_df_all["PA"] >= min_pa]["Name"].unique().tolist()
    )
    _current_lineup = [
        st.session_state.get(f"slot{i}", _all_for_export[0] if _all_for_export else "")
        for i in range(9)
    ]
    st.download_button(
        label=t("btn_save_json"),
        data=_lineup_to_json(_current_lineup).encode("utf-8"),
        file_name=f"lineup_{season}.json",
        mime="application/json",
        key="dl_lineup",
    )
    uploaded = st.file_uploader(t("upload_json"), type="json", key="upload_lineup")
    if uploaded is not None:
        parsed = _json_to_lineup(uploaded.read())
        if parsed:
            _apply_lineup(parsed, _all_for_export)
            st.success(t("upload_ok"))
            st.rerun()
        else:
            st.error(t("upload_err"))

# ── Player pool ───────────────────────────────────────────────────────────────
df_pool = _df_all[_df_all["PA"] >= min_pa].copy()
if team_mode and selected_team_abbr:
    df_pool = df_pool[df_pool["Team"] == selected_team_abbr]

all_players = sorted(df_pool["Name"].unique().tolist())
if not all_players:
    st.warning(
        f"Brak graczy: min PA={min_pa}, team={selected_team_abbr or 'all'}. "
        f"W zbiorze: {len(_df_all)}."
    )
    st.stop()

tab1, tab2, tab3 = st.tabs([t("tab_lineup"), t("tab_same"), t("tab_sensitivity")])

# ── TAB 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    st.markdown(f"#### {APP_TITLE} {season} · {t('tab_lineup')}")
    if team_mode and selected_team_abbr:
        full = next(
            (k for k, v in TEAMS.items() if v == selected_team_abbr), selected_team_abbr
        )
        st.info(f"🏟 **{full}** — {len(all_players)} graczy")

    lineup_names: list[str] = []
    cols = st.columns(3)
    for i in range(9):
        if allow_duplicates:
            available = list(all_players)
        else:
            already = set(lineup_names)
            available = [p for p in all_players if p not in already] or list(all_players)

        prev = st.session_state.get(f"slot{i}")
        default_idx = available.index(prev) if prev in available else min(i, len(available) - 1)

        with cols[i % 3]:
            chosen = st.selectbox(
                f"{t('slot')} {i + 1}", available, index=default_idx, key=f"slot{i}"
            )
        lineup_names.append(chosen)

    if st.button(t("btn_simulate"), type="primary", key="btn_sim_lineup"):
        probs_r, probs_l, debug_lines = [], [], []
        for name in lineup_names:
            row = df_pool[df_pool["Name"] == name].iloc[0]
            probs_r.append(build_probs_rhp(row, era_plus))
            probs_l.append(build_probs_lhp(row, era_plus))
            debug_lines.append(
                f"**{name}** ({row.get('Team', '?')}) — {prob_label(row, era_plus)}  \n"
                f"  _{split_source_caption(row)}_"
            )

        arr_r = np.array(probs_r, dtype=np.float64)
        arr_l = np.array(probs_l, dtype=np.float64) if lhp_pct > 0 else None

        with st.spinner(t("spinner")):
            start = time.time()
            rpg = simulate_games(arr_r, n_mixed, arr_l, lhp_rate=lhp_rate)
            elapsed = time.time() - start

        c1, c2, c3 = st.columns(3)
        c1.metric(t("rpg"), f"{rpg:.2f}")
        c2.metric(t("rps"), f"{int(rpg * 162)}")
        c3.metric(t("elapsed"), f"{elapsed:.2f}s")
        st.caption(f"⚔ vs LHP **{lhp_pct}%** · vs RHP **{rhp_pct}%** (prawdziwe splity gdy PA≥{MIN_SPLIT_PA})")
        with st.expander(t("prob_header")):
            for line in debug_lines:
                st.markdown(line)

# ── TAB 2 ─────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown(f"#### {APP_TITLE} {season} · {t('tab_same')}")
    c1, c2 = st.columns(2)
    with c1:
        a = st.selectbox(t("player_a"), all_players, key="player_a")
    with c2:
        b = st.selectbox(t("player_b"), all_players, key="player_b")

    if st.button(t("btn_compare"), type="primary", key="btn_compare"):
        row_a = df_pool[df_pool["Name"] == a].iloc[0]
        row_b = df_pool[df_pool["Name"] == b].iloc[0]
        la_r = np.array([build_probs_rhp(row_a, era_plus)] * 9, dtype=np.float64)
        lb_r = np.array([build_probs_rhp(row_b, era_plus)] * 9, dtype=np.float64)
        la_l = np.array([build_probs_lhp(row_a, era_plus)] * 9, dtype=np.float64) if lhp_pct > 0 else None
        lb_l = np.array([build_probs_lhp(row_b, era_plus)] * 9, dtype=np.float64) if lhp_pct > 0 else None

        with st.spinner(t("spinner")):
            start = time.time()
            r_a = simulate_games(la_r, n_same, la_l, lhp_rate=lhp_rate)
            r_b = simulate_games(lb_r, n_same, lb_l, lhp_rate=lhp_rate)
            elapsed = time.time() - start

        m1, m2, m3 = st.columns(3)
        m1.metric(f"9× {a}", f"{r_a:.2f}", f"{r_a - r_b:+.2f}")
        m2.metric(f"9× {b}", f"{r_b:.2f}")
        m3.metric(t("elapsed"), f"{elapsed:.2f}s")
        st.caption(f"⚔ vs LHP {lhp_pct}% · vs RHP {rhp_pct}%")
        with st.expander(t("prob_header")):
            st.markdown(f"**{a}** — {prob_label(row_a, era_plus)}  \n_{split_source_caption(row_a)}_")
            st.markdown(f"**{b}** — {prob_label(row_b, era_plus)}  \n_{split_source_caption(row_b)}_")

# ── TAB 3 ─────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown(f"#### {APP_TITLE} {season} · {t('tab_sensitivity')}")
    st.caption(t("sens_note"))
    sens_player = st.selectbox(t("sens_player"), all_players, key="sens_player")

    if st.button(t("btn_run_sens"), type="primary", key="btn_sens"):
        sens_row = df_pool[df_pool["Name"] == sens_player].iloc[0]
        prog = st.progress(0.0, text=t("computing"))

        def _progress(frac: float):
            prog.progress(min(frac, 1.0), text=f"{t('computing')} {frac*100:.0f}%")

        start = time.time()
        base_rpg, tornado, deltas, obp_curve, slg_curve, detail = compute_sensitivity(
            sens_row, era_plus, progress_cb=_progress
        )
        elapsed = time.time() - start
        prog.empty()

        c1, c2 = st.columns(2)
        c1.metric(t("base_rpg"), f"{base_rpg:.2f}")
        c2.metric(t("elapsed"), f"{elapsed:.1f}s")
        st.caption(split_source_caption(sens_row))

        st.subheader(t("tornado_title"))
        st.plotly_chart(_tornado_chart(tornado, base_rpg), use_container_width=True, key="tornado")
        st.subheader(t("obp_slg_title"))
        st.plotly_chart(
            _obp_slg_chart(deltas, obp_curve, slg_curve), use_container_width=True, key="obp_slg"
        )
        with st.expander(t("detail_curves")):
            st.plotly_chart(_detail_chart(detail), use_container_width=True, key="detail")