"""
data_layer.py – ładowanie danych (parquet / pybaseball / syntetyczne)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from datetime import timedelta
from pathlib import Path
from typing import Optional

from config import (
    PITCHER_PROFILES, BATTERS, ZONE_WEIGHTS, ALL_ZONES, ZONE_LOW, INACTIVE_BY_SEASON,
    PITCHER_THROWS, PITCH_VELO_RANGES, TEAM_OF_BATTER,
)

# ── v6: proxy count-state distribution (balls, strikes) — early counts more common ──
_COUNT_STATES = [(0,0),(1,0),(0,1),(2,0),(1,1),(0,2),(3,0),(2,1),(1,2),(3,1),(2,2),(3,2)]
_COUNT_WEIGHTS = np.array([0.22,0.14,0.12,0.08,0.11,0.07,0.03,0.07,0.07,0.03,0.04,0.02])
_COUNT_WEIGHTS = _COUNT_WEIGHTS / _COUNT_WEIGHTS.sum()

_BREAKING = {"SL", "CU", "KC", "ST"}
_OFFSPEED = {"CH", "FS"}


def _simulate_pitch_outcome(rng: np.random.Generator, pt: str, zone: int, strikes: int) -> dict:
    """Proxy swing/contact/exit-velo model — NOT sequenced at-bats, just a per-pitch
    approximation good enough to demo outcome-aware insights on synthetic data."""
    in_zone = zone <= 9
    two_strike = strikes == 2

    base_swing = 0.62 if in_zone else 0.28
    if two_strike:
        base_swing += 0.10
    swing = rng.random() < min(base_swing, 0.92)

    whiff = False
    in_play = False
    exit_velo = np.nan
    hit = False

    if swing:
        whiff_base = 0.30 if pt in _BREAKING else (0.32 if pt in _OFFSPEED else 0.18)
        if not in_zone:
            whiff_base += 0.10
        whiff = rng.random() < whiff_base

        if not whiff:
            foul = rng.random() < 0.55
            in_play = not foul
            if in_play:
                velo_mean = 89.0 if pt in ("FF", "SI") else 85.0
                exit_velo = float(np.clip(rng.normal(velo_mean, 11.0), 40, 118))
                hit_prob = 0.50 if exit_velo >= 95 else (0.32 if exit_velo >= 85 else 0.18)
                hit = rng.random() < hit_prob

    return dict(swing=swing, whiff=whiff, in_play=in_play, exit_velo=exit_velo, hit=hit)


# ── Helpers ───────────────────────────────────────────────────────────────────

def floor_to_monday(dates: pd.Series) -> pd.Series:
    """Wektoryzowany floor do poniedziałku — 8 ms vs 1700 ms dla apply(lambda)."""
    return dates.dt.normalize() - pd.to_timedelta(dates.dt.dayofweek, unit="D")


def make_week_labels(week_starts: pd.Series) -> pd.DataFrame:
    """Buduje tabelę label dla unikalnych week_start."""
    uw = week_starts.drop_duplicates().sort_values()
    return pd.DataFrame({
        "week_start":       uw.values,
        "week_label":       uw.dt.strftime("W%V %Y · %d %b").values,
        "week_label_short": uw.dt.strftime("W%V '%y").values,
    })


# ── Generowanie syntetycznych danych ─────────────────────────────────────────

def _gen_season(year: int) -> pd.DataFrame:
    """Generuje pitch-by-pitch dla jednego sezonu z realistycznymi wzorcami."""
    rng = np.random.default_rng(year * 17 + 3)

    end_mo, end_dy = (7, 15) if year >= 2026 else (10, 1)
    start = pd.Timestamp(f"{year}-04-01")
    end   = pd.Timestamp(f"{year}-{end_mo:02d}-{end_dy:02d}")

    inactive   = INACTIVE_BY_SEASON.get(year, set())
    active_bats = [b for b in BATTERS if b not in inactive]

    rows: list[dict] = []
    pitchers = list(PITCHER_PROFILES.keys())

    pitcher_drift: dict[str, np.ndarray] = {
        p: rng.uniform(-0.08, 0.08, size=4) for p in pitchers
    }
    # v6: slow mph drift per pitcher (simulates "same pitch, thrown harder/softer over time")
    velo_drift: dict[str, np.ndarray] = {
        p: rng.uniform(-1.3, 1.3, size=4) for p in pitchers
    }

    for week_start in pd.date_range(start, end, freq="W-MON"):
        week_num = int((week_start - start).days // 7)
        for pitcher in pitchers:
            prof = PITCHER_PROFILES[pitcher]
            p_throws = PITCHER_THROWS.get(pitcher, "R")
            nb   = rng.integers(5, 12)
            bats = rng.choice(active_bats, size=min(nb, len(active_bats)), replace=False)

            for batter in bats:
                n_p       = int(rng.integers(10, 38))
                game_date = week_start + timedelta(days=int(rng.integers(0, 6)))
                if game_date > end:
                    continue

                all_types    = [prof["primary"]] + prof["secondary"]
                base_w       = np.array([0.42] + [0.58 / len(prof["secondary"])] * len(prof["secondary"]))
                drift_factor = np.ones(len(all_types))
                drift_factor[0] += pitcher_drift[pitcher][week_num % 4] * 0.5
                drift_factor   = np.abs(drift_factor)
                noise          = rng.dirichlet(base_w * 12)
                weights        = 0.68 * base_w * drift_factor + 0.32 * noise
                weights       /= weights.sum()

                count_idx = rng.choice(len(_COUNT_STATES), size=n_p, p=_COUNT_WEIGHTS)

                for pi, pt in enumerate(rng.choice(all_types, size=n_p, p=weights)):
                    zw_raw = ZONE_WEIGHTS.get(pt, [0.25, 0.25, 0.25, 0.25])
                    zone_prob = (
                        [zw_raw[0] / 3] * 3 +
                        [zw_raw[1] / 3] * 3 +
                        [zw_raw[2] / 3] * 3 +
                        [zw_raw[3] / 4] * 4
                    )
                    zone = int(rng.choice(ALL_ZONES, p=zone_prob))

                    balls, strikes = _COUNT_STATES[count_idx[pi]]

                    velo_mean, velo_std = PITCH_VELO_RANGES.get(pt, (88.0, 2.0))
                    velo_mean_wk = velo_mean + velo_drift[pitcher][week_num % 4]
                    release_speed = float(np.clip(rng.normal(velo_mean_wk, velo_std), 60, 105))

                    outcome = _simulate_pitch_outcome(rng, pt, zone, strikes)

                    rows.append({
                        "game_date":    game_date,
                        "pitcher_name": pitcher,
                        "batter_name":  batter,
                        "batter_team":  TEAM_OF_BATTER.get(batter, "Unknown"),
                        "pitch_type":   pt,
                        "zone":         zone,
                        "season":       year,
                        "p_throws":     p_throws,
                        "balls":        balls,
                        "strikes":      strikes,
                        "two_strike":   strikes == 2,
                        "release_speed": round(release_speed, 1),
                        "swing":        outcome["swing"],
                        "whiff":        outcome["whiff"],
                        "in_play":      outcome["in_play"],
                        "exit_velo":    outcome["exit_velo"],
                        "hit":          outcome["hit"],
                    })

    df = pd.DataFrame(rows)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


# ── Ładowanie danych ──────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=3600)
def load_data(seasons: tuple[int, ...], use_live: bool = False,
              live_days_back: int = 14) -> tuple[pd.DataFrame, str]:
    """
    Wczytuje dane dla wybranych sezonów.
    Priorytety:
      1. data/pitch_mix_RRRR.parquet  (z data_pipeline.ipynb)  — zawsze próbowane, szybkie
      2. pybaseball Statcast — TYLKO jeśli use_live=True (opt-in), i TYLKO ostatnie
         `live_days_back` dni sezonu (nie cały sezon!)
      3. Dane syntetyczne (zawsze dostępne, domyślny bezpieczny fallback)

    v6.1 FIX: pociąganie CAŁEGO sezonu (~180 dni) na żywo z Statcast na hostingu
    z ograniczoną pamięcią (np. darmowy Streamlit Community Cloud, ~1GB RAM) potrafiło
    zabić proces (OOM kill = brak tracebacku, po prostu "oh no, error running app").
    Dlatego live-fetch jest teraz: (a) opt-in, (b) ograniczony do krótkiego okna,
    (c) dtype-downcasted żeby zmniejszyć zużycie pamięci.
    """
    frames: list[pd.DataFrame] = []
    source = "syntetyczne"

    for year in sorted(seasons):
        p = Path(f"data/pitch_mix_{year}.parquet")
        if p.exists():
            try:
                df_p = pd.read_parquet(p)
                df_p["game_date"] = pd.to_datetime(df_p["game_date"])
                if "season" not in df_p.columns:
                    df_p["season"] = year
                if "zone" not in df_p.columns:
                    df_p["zone"] = 5
                frames.append(df_p)
                source = "parquet"
            except Exception as e:
                st.warning(f"Nie można wczytać {p}: {e}")

    if frames and len(frames) == len(seasons):
        return pd.concat(frames, ignore_index=True), source

    missing = [y for y in seasons if not Path(f"data/pitch_mix_{y}.parquet").exists()]
    if missing and use_live:
        try:
            from pybaseball import statcast, playerid_reverse_lookup  # type: ignore
            pb_frames: list[pd.DataFrame] = []
            raw_cols = ["game_date", "player_name", "batter", "pitch_type", "zone",
                        "p_throws", "balls", "strikes", "release_speed",
                        "description", "events", "launch_speed",
                        "home_team", "away_team", "inning_topbot"]

            for year in missing:
                # v6.1: BOUNDED window instead of the full ~180-day season — this is
                # the actual fix for the OOM crash, not just a try/except.
                season_start = pd.Timestamp(f"{year}-04-01")
                season_end   = pd.Timestamp(f"{year}-07-15" if year >= 2026 else f"{year}-10-01")
                today        = pd.Timestamp.today().normalize()
                fetch_end    = min(season_end, today)
                fetch_start  = max(season_start, fetch_end - pd.Timedelta(days=live_days_back))
                if fetch_start >= fetch_end:
                    continue

                try:
                    df_pb = statcast(start_dt=fetch_start.strftime("%Y-%m-%d"),
                                      end_dt=fetch_end.strftime("%Y-%m-%d"))
                except Exception as e:
                    st.warning(f"Statcast fetch failed for {year} ({fetch_start.date()}–{fetch_end.date()}): {e}")
                    continue

                if df_pb is None or df_pb.empty:
                    continue

                df_pb = df_pb[[c for c in raw_cols if c in df_pb.columns]].dropna(subset=["pitch_type"])
                df_pb["game_date"] = pd.to_datetime(df_pb["game_date"])
                df_pb["pitcher_name"] = df_pb["player_name"].apply(
                    lambda n: f"{n.split(',')[1].strip()} {n.split(',')[0].strip()}"
                    if isinstance(n, str) and "," in n else str(n)
                )
                df_pb["season"] = year
                if "zone" not in df_pb.columns:
                    df_pb["zone"] = 5

                # ── Real batter names (raw Statcast only gives batter MLBAM id) ──
                fallback_names = "Batter #" + df_pb["batter"].astype("Int64").astype(str)
                try:
                    ids = df_pb["batter"].dropna().astype(int).unique().tolist()
                    lkp = playerid_reverse_lookup(ids, key_type="mlbam")
                    lkp["batter_name"] = (
                        lkp["name_first"].str.title() + " " + lkp["name_last"].str.title()
                    )
                    lkp = lkp[["key_mlbam", "batter_name"]].rename(columns={"key_mlbam": "batter"})
                    df_pb = df_pb.merge(lkp, on="batter", how="left")
                    df_pb["batter_name"] = df_pb["batter_name"].fillna(fallback_names)
                except Exception:
                    df_pb["batter_name"] = fallback_names

                # ── Real batter team (derived from home/away + which half-inning) ──
                if {"home_team", "away_team", "inning_topbot"}.issubset(df_pb.columns):
                    is_away_batting = df_pb["inning_topbot"].astype(str).str.lower().str.startswith("top")
                    df_pb["batter_team"] = np.where(is_away_batting, df_pb["away_team"], df_pb["home_team"])
                else:
                    df_pb["batter_team"] = "Unknown"

                desc = df_pb.get("description", pd.Series("", index=df_pb.index)).fillna("")
                df_pb["swing"]     = desc.str.contains("swing|hit_into_play|foul", case=False, regex=True)
                df_pb["whiff"]     = desc.str.contains("swinging_strike", case=False, regex=True)
                df_pb["in_play"]   = desc.str.contains("hit_into_play", case=False, regex=True)
                df_pb["exit_velo"] = pd.to_numeric(df_pb.get("launch_speed"), errors="coerce")
                events = df_pb.get("events", pd.Series("", index=df_pb.index)).fillna("")
                df_pb["hit"] = events.isin(["single", "double", "triple", "home_run"])
                if "strikes" in df_pb.columns:
                    df_pb["two_strike"] = pd.to_numeric(df_pb["strikes"], errors="coerce") == 2
                else:
                    df_pb["strikes"] = np.nan
                    df_pb["two_strike"] = False
                if "balls" not in df_pb.columns:
                    df_pb["balls"] = np.nan
                if "p_throws" not in df_pb.columns:
                    df_pb["p_throws"] = "R"
                if "release_speed" not in df_pb.columns:
                    df_pb["release_speed"] = np.nan

                keep = ["game_date", "pitcher_name", "batter_name", "batter_team", "pitch_type", "zone",
                        "season", "p_throws", "balls", "strikes", "two_strike", "release_speed",
                        "swing", "whiff", "in_play", "exit_velo", "hit"]
                pb_frames.append(_optimize_dtypes(df_pb[keep]))

            if pb_frames:
                frames.extend(pb_frames)
                source = "Statcast (live, ostatnie dni)"
        except ImportError:
            st.warning("pybaseball nie jest zainstalowany — pomijam live-fetch, używam danych syntetycznych.")
        except Exception as e:
            st.warning(f"Live Statcast fetch nie powiódł się ({e}) — używam danych syntetycznych.")

    have_seasons = {int(f["season"].iloc[0]) for f in frames} if frames else set()
    for year in sorted(seasons):
        if year not in have_seasons:
            frames.append(_gen_season(year))

    df_out = pd.concat(frames, ignore_index=True)

    required = {"game_date", "pitcher_name", "batter_name", "pitch_type", "zone", "season"}
    for col in required:
        if col not in df_out.columns:
            df_out[col] = 5 if col == "zone" else None

    v6_defaults = {
        "batter_team": "Unknown", "p_throws": "R", "balls": np.nan, "strikes": np.nan,
        "two_strike": False, "release_speed": np.nan, "swing": False, "whiff": False,
        "in_play": False, "exit_velo": np.nan, "hit": False,
    }
    for col, default in v6_defaults.items():
        if col not in df_out.columns:
            df_out[col] = default
        else:
            df_out[col] = df_out[col].fillna(default) if df_out[col].dtype != bool else df_out[col].fillna(False)

    df_out["zone"] = pd.to_numeric(df_out["zone"], errors="coerce").fillna(5).astype(int)
    df_out = df_out.dropna(subset=["pitcher_name", "batter_name", "pitch_type"])

    return _optimize_dtypes(df_out), source


def _optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """v6.1: downcast NUMERIC dtypes to reduce memory footprint on constrained hosting.
    NOTE: deliberately does NOT convert name/team/pitch_type columns to 'category' —
    those get string-concatenated (e.g. batter_name + ' · ' + week_label) all over
    compute.py/ui_components.py, and pandas Categorical doesn't support + with str."""
    df = df.copy()
    float_cols = ["release_speed", "exit_velo"]
    for c in float_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    if "zone" in df.columns:
        df["zone"] = pd.to_numeric(df["zone"], errors="coerce").fillna(5).astype("int16")
    if "season" in df.columns:
        df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("int16")
    for c in ("balls", "strikes"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    bool_cols = ["two_strike", "swing", "whiff", "in_play", "hit"]
    for c in bool_cols:
        if c in df.columns:
            df[c] = df[c].fillna(False).astype(bool)
    return df
