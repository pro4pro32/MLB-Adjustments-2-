"""
compute.py – cała logika obliczeniowa

v5: kategorie generyczne po config.ALL_CATEGORIES / CAT_COLS (16 kategorii:
FB%, BB%, OS% + zone1%…zone9%, zone11%…zone14%).

v6 CHANGE — dodane:
  • Rolling baseline (BASELINE_WEEKS) zamiast tylko pojedynczego poprz. tygodnia
    → mniej fałszywych alarmów z małej próby.
  • Flaga `reliable` (sample-size guard, MIN_RELIABLE_PITCHES).
  • Outcome metrics: whiff%, BA (proxy), avg exit velo — batter-centric.
  • Platoon/count context: % rzutów vs LHP, % w 2-strike counts (do wykrywania
    confoundów: czy zmiana pitch-mix to naprawdę adjustment, czy inny matchup).
  • Velocity tracking per pitch-type (ten sam pitch, rzucony mocniej/słabiej).
  • Sustained trend detector — uogólniony na wszystkie 16 kategorii (streak).
  • Team-level rollup.
  • Weekly digest generator (markdown, do wysłania/skopiowania).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import numpy as np
import pandas as pd
import streamlit as st

from config import (
    ALL_CATEGORIES, CAT_COLS, PITCH_TYPES, ZONE_LOW,
    MIN_RELIABLE_PITCHES, BASELINE_WEEKS, TEAM_OF_BATTER,
)
from data_layer import floor_to_monday, make_week_labels


def _cat_key(col: str) -> str:
    """'fb_pct' -> 'fb' ; 'zone11_pct' -> 'zone11' — używane do nazw kolumn delt."""
    return col.replace("_pct", "")


# ─────────────────────────────────────────────────────────────────────────────
#  1.  BATTER-CENTRIC PITCH MIX  (główna perspektywa)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_batter_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Agreguje WSZYSTKICH pitcherów → tygodniowy pitch mix DO danego battera."""
    d = df.copy()
    d["week_start"] = floor_to_monday(d["game_date"])

    base = (
        d.groupby(["batter_name", "week_start", "season"])
         .agg(total=("pitch_type", "count"))
         .reset_index()
    )

    for col, info in ALL_CATEGORIES.items():
        cnt_col = _cat_key(col)
        if info["kind"] == "pitch":
            mask = d["pitch_type"].isin(info["types"])
        else:
            mask = d["zone"] == info["zone"]

        sub = (
            d[mask].groupby(["batter_name", "week_start"]).size()
            .reset_index(name=f"n_{cnt_col}")
        )
        base = base.merge(sub, on=["batter_name", "week_start"], how="left")
        base[f"n_{cnt_col}"] = base[f"n_{cnt_col}"].fillna(0)
        base[col] = (base[f"n_{cnt_col}"] / base["total"] * 100).round(1)

    # v6: carry the real batter_team through (works for both synthetic + real Statcast data —
    # takes the most common team per batter in case of a mid-window trade)
    if "batter_team" in d.columns:
        team_map = (
            d.groupby("batter_name")["batter_team"]
             .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown")
             .reset_index()
        )
        base = base.merge(team_map, on="batter_name", how="left")

    labels = make_week_labels(base["week_start"])
    result = base.merge(labels, on="week_start")
    result["week_date"] = result["week_start"].dt.date
    return result


def _compute_batter_deltas(bw: pd.DataFrame, min_pitches: int = 1) -> pd.DataFrame:
    """
    Week-to-week delta per batter per kategoria + v6 rolling-baseline delta.

    Dla każdej z 16 kategorii tworzy:
      d_<key>       – zmiana vs POPRZEDNI tydzień (jak w v5)
      d_<key>_base  – zmiana vs ROLLING BASELINE (średnia z ostatnich
                      BASELINE_WEEKS tygodni PRZED bieżącym) — bardziej
                      odporne na szum małej próby niż pojedynczy tydzień
      abs_ warianty obu powyższych

    `reliable`      – bool: total i total_prev >= MIN_RELIABLE_PITCHES (dla d_<key>)
    `reliable_base` – bool: total i suma pitchy w oknie baseline >= MIN_RELIABLE_PITCHES
    """
    w = (
        bw[bw["total"] >= min_pitches]
        .sort_values(["batter_name", "week_start"])
        .copy()
    )

    grp = "batter_name"
    abs_d_cols: list[str] = []
    abs_d_base_cols: list[str] = []

    for col in CAT_COLS:
        key     = _cat_key(col)
        d_col   = f"d_{key}"
        abs_col = f"abs_{d_col}"

        # vs poprzedni tydzień
        w[col + "_prev"] = w.groupby(grp)[col].shift(1)
        w[d_col]         = (w[col] - w[col + "_prev"]).round(1)
        w[abs_col]       = w[d_col].abs()
        abs_d_cols.append(abs_col)

        # vs rolling baseline (średnia z BASELINE_WEEKS tygodni przed bieżącym)
        base_col     = f"{col}_baseline"
        d_base_col   = f"d_{key}_base"
        abs_base_col = f"abs_{d_base_col}"
        w[base_col] = (
            w.groupby(grp)[col]
             .transform(lambda s: s.shift(1).rolling(BASELINE_WEEKS, min_periods=1).mean())
        )
        w[d_base_col]   = (w[col] - w[base_col]).round(1)
        w[abs_base_col] = w[d_base_col].abs()
        abs_d_base_cols.append(abs_base_col)

    w = w.copy()  # defragment after the wide per-category loop above
    w["total_prev"] = w.groupby(grp)["total"].shift(1)
    w["week_prev"]  = w.groupby(grp)["week_label"].shift(1)
    w["total_baseline_sum"] = (
        w.groupby(grp)["total"].transform(lambda s: s.shift(1).rolling(BASELINE_WEEKS, min_periods=1).sum())
    )
    w = w.dropna(subset=["total_prev"]).copy()

    min_total = w[["total", "total_prev"]].min(axis=1)
    w["adj_score"] = (w[abs_d_cols].mean(axis=1) * np.sqrt(min_total / 10)).round(2)
    w["adj_score_base"] = (
        w[abs_d_base_cols].mean(axis=1) * np.sqrt(w[["total", "total_baseline_sum"]].min(axis=1) / 10)
    ).round(2)

    # ── sample-size guard (v6) ──
    w["reliable"]      = (w["total"] >= MIN_RELIABLE_PITCHES) & (w["total_prev"] >= MIN_RELIABLE_PITCHES)
    w["reliable_base"] = (w["total"] >= MIN_RELIABLE_PITCHES) & (w["total_baseline_sum"] >= MIN_RELIABLE_PITCHES)

    # ── Biggest single mover: vs poprzedni tydzień ──
    abs_vals = w[abs_d_cols].to_numpy()
    best_idx = np.nanargmax(abs_vals, axis=1)
    w["top_mover_cat"]   = [CAT_COLS[i] for i in best_idx]
    w["top_mover_label"] = w["top_mover_cat"].map(lambda c: ALL_CATEGORIES[c]["short"])
    w["top_mover_abs"]   = abs_vals[np.arange(len(w)), best_idx]
    d_cols_arr = w[[f"d_{_cat_key(c)}" for c in CAT_COLS]].to_numpy()
    w["top_mover_delta"] = d_cols_arr[np.arange(len(w)), best_idx]

    # ── Biggest single mover: vs rolling baseline (v6 — bardziej wiarygodny) ──
    abs_base_vals = w[abs_d_base_cols].to_numpy()
    best_base_idx = np.nanargmax(abs_base_vals, axis=1)
    w["top_mover_base_cat"]   = [CAT_COLS[i] for i in best_base_idx]
    w["top_mover_base_label"] = w["top_mover_base_cat"].map(lambda c: ALL_CATEGORIES[c]["short"])
    w["top_mover_base_abs"]   = abs_base_vals[np.arange(len(w)), best_base_idx]
    d_base_cols_arr = w[[f"d_{_cat_key(c)}_base" for c in CAT_COLS]].to_numpy()
    w["top_mover_base_delta"] = d_base_cols_arr[np.arange(len(w)), best_base_idx]

    w["week_date"] = w["week_start"].dt.date
    return w.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  2.  OUTCOME METRICS  (v6 — did the change actually work?)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_batter_outcomes_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Batter-centric outcome metrics per tydzień: whiff%, BA (proxy z in-play
    outcomes), średnia exit velo. Łączone z pitch-mix żeby zobaczyć czy zmiana
    podejścia pitcherów faktycznie coś dała.
    """
    d = df.copy()
    d["week_start"] = floor_to_monday(d["game_date"])

    swings = d[d["swing"]]
    whiff_agg = (
        swings.groupby(["batter_name", "week_start"])
        .agg(n_swing=("swing", "size"), n_whiff=("whiff", "sum"))
        .reset_index()
    )
    whiff_agg["whiff_pct"] = (whiff_agg["n_whiff"] / whiff_agg["n_swing"] * 100).round(1)

    inplay = d[d["in_play"]]
    ba_agg = (
        inplay.groupby(["batter_name", "week_start"])
        .agg(n_bip=("in_play", "size"), n_hits=("hit", "sum"), avg_exit_velo=("exit_velo", "mean"))
        .reset_index()
    )
    ba_agg["ba_proxy"] = (ba_agg["n_hits"] / ba_agg["n_bip"]).round(3)
    ba_agg["avg_exit_velo"] = ba_agg["avg_exit_velo"].round(1)

    out = whiff_agg.merge(ba_agg, on=["batter_name", "week_start"], how="outer")
    return out


def _compute_batter_context_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    v6 — platoon/count context per tydzień: % rzutów vs LHP i % w 2-strike
    counts. Używane żeby oflagować możliwe confoundy (zmiana pitch-mix mogła
    wynikać z tego że batter zobaczył innych pitcherów / inne sytuacje, a nie
    z faktycznego 'adjustmentu').
    """
    d = df.copy()
    d["week_start"] = floor_to_monday(d["game_date"])

    tot = d.groupby(["batter_name", "week_start"]).size().reset_index(name="n_total_ctx")
    lhp = d[d["p_throws"] == "L"].groupby(["batter_name", "week_start"]).size().reset_index(name="n_lhp")
    ts  = d[d["two_strike"]].groupby(["batter_name", "week_start"]).size().reset_index(name="n_two_strike")

    out = tot.merge(lhp, on=["batter_name", "week_start"], how="left") \
             .merge(ts, on=["batter_name", "week_start"], how="left")
    out[["n_lhp", "n_two_strike"]] = out[["n_lhp", "n_two_strike"]].fillna(0)
    out["pct_vs_lhp"]      = (out["n_lhp"] / out["n_total_ctx"] * 100).round(1)
    out["pct_two_strike"]  = (out["n_two_strike"] / out["n_total_ctx"] * 100).round(1)

    out = out.sort_values(["batter_name", "week_start"])
    out["pct_vs_lhp_prev"] = out.groupby("batter_name")["pct_vs_lhp"].shift(1)
    out["d_pct_vs_lhp"]    = (out["pct_vs_lhp"] - out["pct_vs_lhp_prev"]).round(1)
    # Confound flag: handedness mix shifted by >20pp week over week
    out["platoon_confound_flag"] = out["d_pct_vs_lhp"].abs() >= 20
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  3.  VELOCITY TRACKING  (v6 — same pitch, thrown harder/softer)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_velo_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Średnia release_speed per batter × tydzień × pitch_type + delta."""
    d = df.copy()
    d["week_start"] = floor_to_monday(d["game_date"])
    d = d.dropna(subset=["release_speed"])

    velo = (
        d.groupby(["batter_name", "week_start", "pitch_type"])
        .agg(avg_velo=("release_speed", "mean"), n=("release_speed", "size"))
        .reset_index()
    )
    velo["avg_velo"] = velo["avg_velo"].round(1)
    velo = velo.sort_values(["batter_name", "pitch_type", "week_start"])
    velo["avg_velo_prev"] = velo.groupby(["batter_name", "pitch_type"])["avg_velo"].shift(1)
    velo["d_velo"] = (velo["avg_velo"] - velo["avg_velo_prev"]).round(1)

    labels = make_week_labels(velo["week_start"])
    velo = velo.merge(labels, on="week_start")
    return velo


# ─────────────────────────────────────────────────────────────────────────────
#  4.  MATCHUP-LEVEL  (pitcher × batter) — bez zmian, nadal per pitch_type
# ─────────────────────────────────────────────────────────────────────────────

def _compute_matchup_weekly(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["week_start"] = floor_to_monday(d["game_date"])

    grp = (
        d.groupby(["pitcher_name", "batter_name", "week_start", "pitch_type", "season"])
         .size().reset_index(name="n")
    )
    grp["total"] = grp.groupby(["pitcher_name", "batter_name", "week_start"])["n"].transform("sum")
    grp["pitch_pct"] = (grp["n"] / grp["total"] * 100).round(1)

    labels = make_week_labels(grp["week_start"])
    result = grp.merge(labels, on="week_start")
    result["week_date"] = result["week_start"].dt.date
    return result


def _compute_matchup_deltas(mw: pd.DataFrame) -> pd.DataFrame:
    GRP = ["pitcher_name", "batter_name", "pitch_type"]
    w   = mw.sort_values(GRP + ["week_start"]).copy()

    w["pct_prev"]   = w.groupby(GRP)["pitch_pct"].shift(1)
    w["total_prev"] = w.groupby(GRP)["total"].shift(1)
    w["week_prev"]  = w.groupby(GRP)["week_label"].shift(1)

    w = w.dropna(subset=["pct_prev"]).copy()
    w["delta"]     = (w["pitch_pct"] - w["pct_prev"]).round(1)
    w["abs_delta"] = w["delta"].abs()
    w["pitch_name"] = w["pitch_type"].map(PITCH_TYPES).fillna(w["pitch_type"])

    result = w.rename(columns={
        "pitcher_name": "Pitcher", "batter_name": "Batter", "week_label": "Week",
        "week_prev": "Prev Week", "pitch_type": "PT", "pitch_name": "Pitch Name",
        "pitch_pct": "Now %", "pct_prev": "Prev %", "delta": "Δ pp", "abs_delta": "Abs Δ",
        "total": "Pitches", "total_prev": "Prev Pitches",
    }).reset_index(drop=True)
    result["week_date"] = result["week_start"].dt.date
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  5.  GŁÓWNA FUNKCJA CACHE
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, max_entries=8)
def precompute_all(df: pd.DataFrame) -> dict[str, Any]:
    t0 = time.perf_counter()

    bw = _compute_batter_weekly(df)
    bd = _compute_batter_deltas(bw, min_pitches=1)
    mw = _compute_matchup_weekly(df)
    md = _compute_matchup_deltas(mw)

    outcomes = _compute_batter_outcomes_weekly(df)
    context  = _compute_batter_context_weekly(df)
    velo     = _compute_velo_weekly(df)

    # scal outcomes + context do bd (batter_name + week_start) — jedno miejsce prawdy
    bd = bd.merge(outcomes, on=["batter_name", "week_start"], how="left")
    bd = bd.merge(
        context[["batter_name", "week_start", "pct_vs_lhp", "pct_two_strike",
                 "d_pct_vs_lhp", "platoon_confound_flag"]],
        on=["batter_name", "week_start"], how="left",
    )

    perf_ms = round((time.perf_counter() - t0) * 1000)
    return {
        "batter_weekly":  bw,
        "batter_delta":   bd,
        "matchup_weekly": mw,
        "matchup_delta":  md,
        "velo_weekly":    velo,
        "perf_ms":        perf_ms,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  6.  FILTROWANIE  (inline, bez cache)
# ─────────────────────────────────────────────────────────────────────────────

def filter_batter_weekly(bw, d_start, d_end, sel_batters, sel_seasons):
    col = "week_date" if "week_date" in bw.columns else None
    if col:
        m = (bw[col] >= d_start) & (bw[col] <= d_end)
    else:
        m = (bw["week_start"].dt.date >= d_start) & (bw["week_start"].dt.date <= d_end)
    if sel_batters:  m &= bw["batter_name"].isin(sel_batters)
    if sel_seasons:  m &= bw["season"].isin(sel_seasons)
    return bw[m].copy()


def filter_batter_delta(bd, d_start, d_end, sel_batters, sel_seasons, min_pitches, min_prev):
    col = "week_date" if "week_date" in bd.columns else None
    if col:
        m = (bd[col] >= d_start) & (bd[col] <= d_end)
    else:
        m = (bd["week_start"].dt.date >= d_start) & (bd["week_start"].dt.date <= d_end)
    m &= (bd["total"] >= min_pitches) & (bd["total_prev"] >= min_prev)
    if sel_batters: m &= bd["batter_name"].isin(sel_batters)
    if sel_seasons: m &= bd["season"].isin(sel_seasons)
    return bd[m].sort_values("adj_score", ascending=False).reset_index(drop=True)


def filter_matchup_weekly(mw, d_start, d_end, sel_pitchers, sel_batters, sel_pt, sel_seasons):
    col = "week_date" if "week_date" in mw.columns else None
    if col:
        m = (mw[col] >= d_start) & (mw[col] <= d_end)
    else:
        m = (mw["week_start"].dt.date >= d_start) & (mw["week_start"].dt.date <= d_end)
    if sel_pitchers: m &= mw["pitcher_name"].isin(sel_pitchers)
    if sel_batters:  m &= mw["batter_name"].isin(sel_batters)
    if sel_pt:       m &= mw["pitch_type"].isin(sel_pt)
    if sel_seasons:  m &= mw["season"].isin(sel_seasons)
    return mw[m].copy()


def filter_matchup_delta(md, d_start, d_end, sel_pitchers, sel_batters, sel_pt, sel_seasons, min_pitches, min_prev):
    col = "week_date" if "week_date" in md.columns else None
    if col:
        m = (md[col] >= d_start) & (md[col] <= d_end)
    else:
        m = (md["week_start"].dt.date >= d_start) & (md["week_start"].dt.date <= d_end)
    m &= (md["Pitches"] >= min_pitches) & (md["Prev Pitches"] >= min_prev)
    if sel_pitchers: m &= md["Pitcher"].isin(sel_pitchers)
    if sel_batters:  m &= md["Batter"].isin(sel_batters)
    if sel_pt:       m &= md["PT"].isin(sel_pt)
    if sel_seasons:  m &= md["season"].isin(sel_seasons)
    return md[m].sort_values("Abs Δ", ascending=False).reset_index(drop=True)


def filter_velo_weekly(velo, d_start, d_end, sel_batters, sel_seasons=None):
    col = "week_date" if "week_date" in velo.columns else None
    if col:
        m = (velo[col] >= d_start) & (velo[col] <= d_end)
    else:
        m = (velo["week_start"].dt.date >= d_start) & (velo["week_start"].dt.date <= d_end)
    if sel_batters: m &= velo["batter_name"].isin(sel_batters)
    return velo[m].copy()


# ─────────────────────────────────────────────────────────────────────────────
#  7.  BIGGEST MOVERS  (across all 16 categories — "did you know" leaderboard)
# ─────────────────────────────────────────────────────────────────────────────

def biggest_movers_leaderboard(bd: pd.DataFrame, top_n: int = 15,
                                reliable_only: bool = True,
                                use_baseline: bool = False) -> pd.DataFrame:
    """
    v6: domyślnie filtruje do `reliable` wierszy (sample-size guard) i pozwala
    przełączyć się na baseline-adjusted mover (bardziej odporny na szum niż
    pojedynczy tydzień).
    """
    if bd.empty:
        return bd

    d = bd.copy()
    rel_col = "reliable_base" if use_baseline else "reliable"
    if reliable_only and rel_col in d.columns:
        d = d[d[rel_col]]

    abs_col   = "top_mover_base_abs"   if use_baseline else "top_mover_abs"
    cat_col   = "top_mover_base_cat"   if use_baseline else "top_mover_cat"
    label_col = "top_mover_base_label" if use_baseline else "top_mover_label"
    delta_col = "top_mover_base_delta" if use_baseline else "top_mover_delta"

    cols = ["batter_name", "week_label", "week_label_short", "week_start",
            cat_col, label_col, abs_col, delta_col,
            "total", "total_prev", "adj_score", "whiff_pct", "ba_proxy",
            "avg_exit_velo", "pct_vs_lhp", "platoon_confound_flag"]
    cols = [c for c in cols if c in d.columns]
    out = d[cols].sort_values(abs_col, ascending=False).head(top_n).reset_index(drop=True)
    out = out.rename(columns={cat_col: "top_mover_cat", label_col: "top_mover_label",
                               abs_col: "top_mover_abs", delta_col: "top_mover_delta"})
    return out


def batter_week_matchup_table(mw: pd.DataFrame, batter: str, week_start) -> pd.DataFrame:
    """
    v6.3: 'Batter ranking, not matchup ranking' — for ONE batter in ONE week, returns
    one row per PITCHER FACED that week (not one row per pitch type like matchup_weekly),
    with a pitch-mix breakdown (FB%/BB%/OS%) and pitch count. This answers "what were
    Adley Rutschman's stats against every pitcher he faced in week 1" directly, instead
    of forcing a pitcher-first drilldown.
    """
    from config import PITCH_CATEGORIES
    sub = mw[(mw["batter_name"] == batter) & (mw["week_start"] == week_start)]
    if sub.empty:
        return pd.DataFrame()

    rows = []
    for pitcher, g in sub.groupby("pitcher_name"):
        total = int(g["n"].sum())
        if total == 0:
            continue
        row = {"pitcher_name": pitcher, "total": total}
        for cat_col, info in PITCH_CATEGORIES.items():
            cnt = g[g["pitch_type"].isin(info["types"])]["n"].sum()
            row[cat_col] = round(cnt / total * 100, 1)
        row["top_pitch_type"] = g.groupby("pitch_type")["n"].sum().idxmax()
        rows.append(row)

    out = pd.DataFrame(rows).sort_values("total", ascending=False).reset_index(drop=True)
    return out


def batter_week_rank(bd: pd.DataFrame, batter: str, week_start, use_baseline: bool = False,
                      reliable_only: bool = True) -> dict | None:
    """
    v6.3: Ranks `batter`'s single biggest mover for `week_start` against EVERY OTHER
    batter's biggest mover for that SAME week (league-wide, not just the batters
    currently in a sidebar filter). Used to make the Player Report headline honest:
    only claim 'you had THE biggest change' when that's actually true this week.
    """
    week_df = bd[bd["week_start"] == week_start].copy()
    if reliable_only:
        rel_col = "reliable_base" if use_baseline else "reliable"
        if rel_col in week_df.columns:
            week_df = week_df[week_df[rel_col]]
    if week_df.empty:
        return None
    abs_col = "top_mover_base_abs" if use_baseline else "top_mover_abs"
    week_df = week_df.sort_values(abs_col, ascending=False).reset_index(drop=True)
    week_df["rank"] = week_df.index + 1
    row = week_df[week_df["batter_name"] == batter]
    if row.empty:
        return None
    r = int(row.iloc[0]["rank"])
    return {"rank": r, "total": len(week_df), "is_top": r == 1}


def latest_week_headline(bd_batter: pd.DataFrame, use_baseline: bool = False) -> dict | None:
    if bd_batter.empty:
        return None
    row = bd_batter.sort_values("week_start").iloc[-1]

    if use_baseline:
        cat_label = row["top_mover_base_label"]
        delta     = float(row["top_mover_base_delta"])
        abs_delta = float(row["top_mover_base_abs"])
        reliable  = bool(row.get("reliable_base", True))
        adj       = float(row["adj_score_base"])
    else:
        cat_label = row["top_mover_label"]
        delta     = float(row["top_mover_delta"])
        abs_delta = float(row["top_mover_abs"])
        reliable  = bool(row.get("reliable", True))
        adj       = float(row["adj_score"])

    direction = "wzrost" if delta > 0 else "spadek"
    out = {
        "week_label":     str(row["week_label"]).replace("\n", " ").replace("·", "").strip(),
        "category_label": cat_label,
        "delta":          delta,
        "abs_delta":      abs_delta,
        "direction":      direction,
        "adj_score":      adj,
        "total":          int(row["total"]),
        "reliable":       reliable,
    }
    if "whiff_pct" in row and pd.notna(row["whiff_pct"]):
        out["whiff_pct"] = float(row["whiff_pct"])
    if "ba_proxy" in row and pd.notna(row["ba_proxy"]):
        out["ba_proxy"] = float(row["ba_proxy"])
    if "platoon_confound_flag" in row:
        out["platoon_confound_flag"] = bool(row["platoon_confound_flag"])
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  8.  SUSTAINED TREND DETECTOR  (v6 — uogólniony na wszystkie 16 kategorii)
# ─────────────────────────────────────────────────────────────────────────────

def compute_sustained_trends(bd: pd.DataFrame, cat_cols: Optional[list[str]] = None,
                              min_streak: int = 3) -> pd.DataFrame:
    """
    Dla każdego battera i każdej z 16 kategorii, znajduje aktualny 'streak'
    (kolejne tygodnie zmiany w tym samym kierunku, licząc od najnowszego) i
    sumaryczną zmianę w tym okresie. To jest generalizacja starego
    'FB% rośnie N tygodni z rzędu' insightu na wszystkie kategorie.
    """
    cat_cols = cat_cols or CAT_COLS
    records = []

    for batter, g in bd.sort_values("week_start").groupby("batter_name"):
        for col in cat_cols:
            d_col = f"d_{_cat_key(col)}"
            if d_col not in g.columns:
                continue
            vals  = g[d_col].to_numpy()
            weeks = g["week_label_short"].to_numpy()
            n = len(vals)
            i = n - 1
            while i >= 0 and pd.isna(vals[i]):
                i -= 1
            if i < 0:
                continue
            sign = np.sign(vals[i])
            if sign == 0:
                continue
            streak, cum = 1, float(vals[i])
            j = i - 1
            while j >= 0 and not pd.isna(vals[j]) and np.sign(vals[j]) == sign:
                streak += 1
                cum += float(vals[j])
                j -= 1
            if streak >= min_streak:
                records.append({
                    "batter_name": batter, "category": ALL_CATEGORIES[col]["short"],
                    "cat_col": col, "streak_weeks": streak,
                    "cumulative_delta": round(cum, 1), "last_week": weeks[i],
                })

    return pd.DataFrame(records)


def sustained_movers_leaderboard(bd: pd.DataFrame, top_n: int = 15, min_streak: int = 3) -> pd.DataFrame:
    df = compute_sustained_trends(bd, min_streak=min_streak)
    if df.empty:
        return df
    df["score"] = df["streak_weeks"] * df["cumulative_delta"].abs()
    return df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  9.  TEAM-LEVEL ROLLUP  (v6)
# ─────────────────────────────────────────────────────────────────────────────

def team_rollup_table(bd: pd.DataFrame) -> pd.DataFrame:
    """Agreguje Adjustment Score na poziom drużyny + wskazuje top-mover battera per drużyna.
    v6: używa REALNEGO batter_team z danych jeśli dostępny (real Statcast), w przeciwnym
    razie fallback na syntetyczny config.TEAM_OF_BATTER (demo mode)."""
    if bd.empty:
        return bd
    d = bd.copy()
    if "batter_team" in d.columns and d["batter_team"].notna().any():
        d["team"] = d["batter_team"].fillna("Unknown")
    else:
        d["team"] = d["batter_name"].map(TEAM_OF_BATTER).fillna("Unknown")

    grp = (
        d.groupby("team")
         .agg(avg_adj=("adj_score", "mean"), max_adj=("adj_score", "max"),
              n_batter_weeks=("adj_score", "size"))
         .round(2).reset_index()
    )

    idx = d.groupby("team")["adj_score"].idxmax()
    top = d.loc[idx, ["team", "batter_name", "adj_score", "top_mover_label",
                       "top_mover_delta", "week_label_short"]].rename(
        columns={"batter_name": "top_batter", "week_label_short": "top_week"}
    )
    out = grp.merge(top.drop(columns=["adj_score"]), on="team", how="left")
    return out.sort_values("avg_adj", ascending=False).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  10.  WEEKLY DIGEST  (v6 — auto-generated, downloadable/copyable text)
# ─────────────────────────────────────────────────────────────────────────────

def generate_weekly_digest(bd: pd.DataFrame, top_n: int = 5,
                            title: Optional[str] = None, lang: str = "en") -> str:
    """
    Generuje gotowy do wysłania markdown digest dla NAJNOWSZEGO tygodnia w
    przefiltrowanych danych. Rzeczywista dystrybucja (email/Slack) wymaga
    osobnej integracji — to jest generator treści. v6.2: language-aware.
    """
    from i18n import T
    title = title or T("digest_title_default", lang=lang)

    if bd.empty:
        return f"# {title}\n\n{T('digest_no_data_range', lang=lang)}"

    latest_week = bd["week_start"].max()
    wk = bd[bd["week_start"] == latest_week].sort_values("top_mover_abs", ascending=False).head(top_n)
    if wk.empty:
        return f"# {title}\n\n{T('digest_no_data_latest', lang=lang)}"

    wl = str(wk.iloc[0]["week_label"]).replace("\n", " ").replace("·", "").strip()
    lines = [f"# ⚾ {title} — {wl}", ""]

    for i, row in enumerate(wk.itertuples(), 1):
        sign = "+" if row.top_mover_delta > 0 else ""
        rel  = T("digest_reliable", lang=lang) if getattr(row, "reliable", True) else T("digest_low_sample", lang=lang)
        line = T("digest_line", lang=lang, i=i, batter=row.batter_name, label=row.top_mover_label,
                  sign=sign, delta=row.top_mover_delta, adj=row.adj_score, total=row.total, rel=rel)
        whiff = getattr(row, "whiff_pct", None)
        ba    = getattr(row, "ba_proxy", None)
        extra = []
        if whiff is not None and pd.notna(whiff):
            extra.append(T("digest_whiff_extra", lang=lang, whiff=whiff))
        if ba is not None and pd.notna(ba):
            extra.append(T("digest_ba_extra", lang=lang, ba=ba))
        if extra:
            line += f"\n   ↳ {' · '.join(extra)}"
        confound = getattr(row, "platoon_confound_flag", False)
        if confound:
            line += f"\n   {T('digest_confound_note', lang=lang)}"
        lines.append(line)

    lines += ["", T("digest_footer", lang=lang)]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  11.  INSIGHTS  (auto-generated text)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  12.  PERIOD COMPARISON  (v6.5 — custom week-range A vs week-range B, all league)
# ─────────────────────────────────────────────────────────────────────────────

def compute_period_comparison(raw_df: pd.DataFrame, bw: pd.DataFrame,
                               weeks_p1: list, weeks_p2: list,
                               min_pitches: int = 1) -> pd.DataFrame:
    """
    'Period 1 (weeks X-Y) vs Period 2 (weeks A-B), all MLB batters, all 16
    categories + average velocity.' Sums the underlying pitch counts across
    each period's weeks (not a naive average-of-weekly-percentages, which
    would be biased by uneven weekly volume) and returns one wide row per
    batter with p1/p2/delta for every category, ready to sort by any column.
    """
    n_cols = [f"n_{_cat_key(c)}" for c in CAT_COLS]

    def agg_period(weeks):
        sub = bw[bw["week_start"].isin(weeks)]
        if sub.empty:
            return pd.DataFrame(columns=["batter_name", "total"] + CAT_COLS)
        g = sub.groupby("batter_name").agg(
            total=("total", "sum"),
            **{nc: (nc, "sum") for nc in n_cols},
        ).reset_index()
        for c in CAT_COLS:
            key = _cat_key(c)
            g[c] = (g[f"n_{key}"] / g["total"].replace(0, np.nan) * 100).round(1)
        return g[["batter_name", "total"] + CAT_COLS]

    p1 = agg_period(weeks_p1).add_suffix("_p1").rename(columns={"batter_name_p1": "batter_name"})
    p2 = agg_period(weeks_p2).add_suffix("_p2").rename(columns={"batter_name_p2": "batter_name"})
    if p1.empty or p2.empty:
        return pd.DataFrame()

    merged = p1.merge(p2, on="batter_name", how="inner")
    if merged.empty:
        return merged

    # overall average velocity (all pitch types combined) per period — from raw pitches,
    # since bw/batter_weekly doesn't carry velocity (that's tracked per pitch-type elsewhere)
    d = raw_df.copy()
    d["week_start"] = floor_to_monday(d["game_date"])

    # v6.9: resolve each batter's team SEPARATELY per period, from the actual pitch-level
    # data — not a single static lookup. A player traded between the two periods (or even
    # mid-period) will show a different team_p1 vs team_p2 instead of one (possibly wrong,
    # possibly just outdated) team for the whole comparison. Only really varies with real/
    # live data — synthetic data assigns one fixed team for the whole season, since it
    # doesn't simulate in-season trades.
    def _team_for_period(weeks) -> pd.Series:
        sub = d[d["week_start"].isin(weeks)]
        if sub.empty or "batter_team" not in sub.columns:
            return pd.Series(dtype=object)
        return sub.groupby("batter_name")["batter_team"].agg(
            lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"
        )

    team_p1 = _team_for_period(weeks_p1).rename("team_p1")
    team_p2 = _team_for_period(weeks_p2).rename("team_p2")
    merged = merged.merge(team_p1, on="batter_name", how="left").merge(team_p2, on="batter_name", how="left")
    merged["team_p1"] = merged["team_p1"].fillna(merged["batter_name"].map(TEAM_OF_BATTER)).fillna("Unknown")
    merged["team_p2"] = merged["team_p2"].fillna(merged["batter_name"].map(TEAM_OF_BATTER)).fillna("Unknown")
    merged["team"] = np.where(
        merged["team_p1"] == merged["team_p2"], merged["team_p1"],
        merged["team_p1"] + " / " + merged["team_p2"],
    )

    velo1 = d[d["week_start"].isin(weeks_p1)].groupby("batter_name")["release_speed"].mean().rename("avg_velo_p1")
    velo2 = d[d["week_start"].isin(weeks_p2)].groupby("batter_name")["release_speed"].mean().rename("avg_velo_p2")
    merged = merged.merge(velo1, on="batter_name", how="left").merge(velo2, on="batter_name", how="left")
    merged["avg_velo_p1"] = merged["avg_velo_p1"].round(1)
    merged["avg_velo_p2"] = merged["avg_velo_p2"].round(1)
    merged["d_velo"] = (merged["avg_velo_p2"] - merged["avg_velo_p1"]).round(1)

    for c in CAT_COLS:
        key = _cat_key(c)
        merged[f"d_{key}"] = (merged[f"{c}_p2"] - merged[f"{c}_p1"]).round(1)

    # v6.7: OPS (OBP + SLG) per period, from real plate-appearance-ending events
    # (is_pa_end / pa_event) — walks, HBP, sac flies, and hit type all counted properly,
    # not just a crude hits/pitches ratio. Real Statcast data uses actual game events;
    # synthetic data uses a calibrated per-pitch approximation (see data_layer.py).
    ops1 = _compute_ops_for_period(d, weeks_p1).add_suffix("_p1").rename(columns={"batter_name_p1": "batter_name"})
    ops2 = _compute_ops_for_period(d, weeks_p2).add_suffix("_p2").rename(columns={"batter_name_p2": "batter_name"})
    merged = merged.merge(ops1, on="batter_name", how="left").merge(ops2, on="batter_name", how="left")
    merged["d_ops"] = (merged["ops_p2"] - merged["ops_p1"]).round(3)
    merged["d_obp"] = (merged["obp_p2"] - merged["obp_p1"]).round(3)
    merged["d_slg"] = (merged["slg_p2"] - merged["slg_p1"]).round(3)

    merged = merged[(merged["total_p1"] >= min_pitches) & (merged["total_p2"] >= min_pitches)]
    return merged.reset_index(drop=True)


def compute_period_correlations(comp: pd.DataFrame, delta_cols: list[str]) -> pd.DataFrame:
    """
    v6.9: correlation matrix among ALL the delta columns in a period-comparison table
    (Δ OPS, Δ OBP, Δ SLG, Δ Velo, Δ FB/BB/OS%, Δ zone1..14%) across every batter that
    passed the reliability filter — surfaces patterns like "does more Zone 9% coincide
    with lower OPS" across the league, not just for one player.
    """
    cols = [c for c in delta_cols if c in comp.columns]
    if comp.empty or len(cols) < 2:
        return pd.DataFrame()
    sub = comp[cols].apply(pd.to_numeric, errors="coerce")
    sub = sub.loc[:, sub.notna().sum() >= 3]  # need at least a few real values to correlate
    if sub.shape[1] < 2:
        return pd.DataFrame()
    return sub.corr(method="pearson").round(2)


def _compute_ops_for_period(d: pd.DataFrame, weeks: list) -> pd.DataFrame:
    """Aggregates OBP/SLG/OPS per batter for one period from real PA-ending events.
    `d` must already have a `week_start` column (see compute_period_comparison)."""
    if "is_pa_end" not in d.columns:
        return pd.DataFrame(columns=["batter_name", "pa", "obp", "slg", "ops"])
    sub = d[d["week_start"].isin(weeks) & d["is_pa_end"] & d["pa_event"].notna()]
    if sub.empty:
        return pd.DataFrame(columns=["batter_name", "pa", "obp", "slg", "ops"])

    def _agg(g: pd.DataFrame) -> pd.Series:
        ev = g["pa_event"]
        pa = len(g)
        bb  = (ev == "walk").sum()
        hbp = (ev == "hit_by_pitch").sum()
        sf  = (ev == "sac_fly").sum()
        s1  = (ev == "single").sum()
        s2  = (ev == "double").sum()
        s3  = (ev == "triple").sum()
        hr  = (ev == "home_run").sum()
        h   = s1 + s2 + s3 + hr
        ab  = pa - bb - hbp - sf
        tb  = s1 + 2 * s2 + 3 * s3 + 4 * hr
        obp = (h + bb + hbp) / (ab + bb + hbp + sf) if (ab + bb + hbp + sf) > 0 else np.nan
        slg = tb / ab if ab > 0 else np.nan
        return pd.Series({"pa": pa, "obp": round(obp, 3) if pd.notna(obp) else np.nan,
                           "slg": round(slg, 3) if pd.notna(slg) else np.nan})

    out = sub.groupby("batter_name").apply(_agg, include_groups=False).reset_index()
    out["ops"] = (out["obp"] + out["slg"]).round(3)
    return out


def generate_batter_insights(bd_batter: pd.DataFrame, batter: str, lang: str = "en") -> list[str]:
    from i18n import T
    if bd_batter.empty:
        return []

    insights: list[str] = []

    top = bd_batter.loc[bd_batter["adj_score"].idxmax()]
    if top["adj_score"] > 0:
        wl = str(top["week_label"]).replace("\n", " ").replace("·", "").strip()
        rel_note = "" if top.get("reliable", True) else T("insight_low_sample_suffix", lang=lang)
        insights.append(T("insight_top_adjustment", lang=lang, week=wl, score=top["adj_score"], rel_note=rel_note))

    bd_s = bd_batter.sort_values("week_start")
    if "d_fb" in bd_s.columns:
        fb_d = bd_s["d_fb"].dropna().values
        if len(fb_d) >= 3:
            streak = 0
            for v in reversed(fb_d):
                if v > 0: streak += 1
                else: break
            if streak >= 3:
                total_rise = round(bd_s["d_fb"].tail(streak).sum(), 1)
                insights.append(T("insight_fb_streak", lang=lang, streak=streak, total=total_rise))

    max_idx = bd_batter["top_mover_abs"].idxmax()
    val   = bd_batter.loc[max_idx, "top_mover_delta"]
    label = bd_batter.loc[max_idx, "top_mover_label"]
    wk    = str(bd_batter.loc[max_idx, "week_label"]).replace("\n", " ").replace("·", "").strip()
    if abs(val) >= 10:
        sign = "+" if val > 0 else ""
        insights.append(T("insight_record_change", lang=lang, label=label, sign=sign, val=val, week=wk))

    if "platoon_confound_flag" in bd_batter.columns:
        flagged = bd_batter[bd_batter["platoon_confound_flag"] == True]
        if not flagged.empty:
            frow = flagged.iloc[-1]
            wl2 = str(frow["week_label"]).replace("\n", " ").replace("·", "").strip()
            insights.append(T("insight_platoon_confound", lang=lang, week=wl2, delta=frow["d_pct_vs_lhp"]))

    if "whiff_pct" in bd_batter.columns:
        wpct = bd_batter.dropna(subset=["whiff_pct"]).sort_values("week_start")
        if len(wpct) >= 2:
            d_whiff = round(wpct["whiff_pct"].iloc[-1] - wpct["whiff_pct"].iloc[-2], 1)
            if abs(d_whiff) >= 8:
                verb = T("insight_whiff_verb_up", lang=lang) if d_whiff > 0 else T("insight_whiff_verb_down", lang=lang)
                insights.append(T("insight_whiff_change", lang=lang, verb=verb, delta=d_whiff))

    return insights[:5]
