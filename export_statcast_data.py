"""
export_statcast_data.py — run LOCALLY (not in the Streamlit app) to pull real Statcast data with
pybaseball and save it in exactly the format the dashboard's sidebar uploader expects.

    pip install pybaseball pandas numpy pyarrow
    python export_statcast_data.py --seasons 2025 2026
    python export_statcast_data.py --seasons 2026 --start 2026-04-01 --end 2026-10-01

Writes statcast_export_<year>.parquet (small — upload this one) and .csv (same data).
A full season is ~700k pitches; the first run can take 15-30+ minutes (pybaseball caches it).
"""
from __future__ import annotations
import argparse, sys
from datetime import date
import numpy as np
import pandas as pd

try:
    from pybaseball import statcast, playerid_reverse_lookup, cache
    cache.enable()
except ImportError:
    print("ERROR: pip install pybaseball"); sys.exit(1)

RAW = ["game_date", "player_name", "batter", "pitch_type", "zone", "p_throws", "balls", "strikes",
       "release_speed", "description", "events", "launch_speed", "home_team", "away_team", "inning_topbot"]
PA_MAP = {"single": "single", "double": "double", "triple": "triple", "home_run": "home_run", "walk": "walk",
          "hit_by_pitch": "hit_by_pitch", "sac_fly": "sac_fly", "sac_fly_double_play": "sac_fly",
          "strikeout": "strikeout", "strikeout_double_play": "strikeout"}


def export_season(year, start, end):
    today = date.today()
    start = start or f"{year}-03-15"
    end = end or (min(date(year, 10, 15), today) if year == today.year else date(year, 10, 15)).strftime("%Y-%m-%d")
    print(f"\n=== {year}: Statcast {start} -> {end} ===")
    df = statcast(start_dt=start, end_dt=end)
    if df is None or df.empty:
        print("  no data"); return
    df = df[[c for c in RAW if c in df.columns]].dropna(subset=["pitch_type"]).copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    df["pitcher_name"] = df["player_name"].apply(
        lambda n: f"{n.split(',')[1].strip()} {n.split(',')[0].strip()}" if isinstance(n, str) and "," in n else str(n))
    df["season"] = year
    fallback = "Batter #" + df["batter"].astype("Int64").astype(str)
    try:
        ids = df["batter"].dropna().astype(int).unique().tolist()
        lkp = playerid_reverse_lookup(ids, key_type="mlbam")
        lkp["batter_name"] = lkp["name_first"].str.title() + " " + lkp["name_last"].str.title()
        df = df.merge(lkp[["key_mlbam", "batter_name"]].rename(columns={"key_mlbam": "batter"}), on="batter", how="left")
        df["batter_name"] = df["batter_name"].fillna(fallback)
    except Exception as e:
        print("  name lookup failed, using ids:", e); df["batter_name"] = fallback
    top = df["inning_topbot"].astype(str).str.lower().str.startswith("top")
    df["batter_team"] = np.where(top, df["away_team"], df["home_team"])
    desc, ev = df["description"].fillna(""), df["events"].fillna("")
    df["swing"] = desc.str.contains("swing|hit_into_play|foul", case=False, regex=True)
    df["whiff"] = desc.str.contains("swinging_strike", case=False, regex=True)
    df["in_play"] = desc.str.contains("hit_into_play", case=False, regex=True)
    df["exit_velo"] = pd.to_numeric(df["launch_speed"], errors="coerce")
    df["hit"] = ev.isin(["single", "double", "triple", "home_run"])
    df["is_pa_end"] = ev != ""
    df["pa_event"] = ev.map(PA_MAP)
    df.loc[df["is_pa_end"] & df["pa_event"].isna(), "pa_event"] = "field_out"
    df["two_strike"] = pd.to_numeric(df["strikes"], errors="coerce") == 2
    keep = ["game_date", "pitcher_name", "batter_name", "batter_team", "pitch_type", "zone", "season", "p_throws",
            "balls", "strikes", "two_strike", "release_speed", "swing", "whiff", "in_play", "exit_velo", "hit",
            "is_pa_end", "pa_event"]
    out = df[keep].dropna(subset=["pitcher_name", "batter_name", "pitch_type"])
    out.to_csv(f"statcast_export_{year}.csv", index=False)
    try:
        out.to_parquet(f"statcast_export_{year}.parquet", index=False)
    except Exception as e:
        print("  (parquet skipped:", e, ")")
    print(f"  saved {len(out):,} pitches · {out['batter_name'].nunique()} batters · "
          f"{out['game_date'].min().date()} -> {out['game_date'].max().date()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", required=True)
    ap.add_argument("--start"); ap.add_argument("--end")
    a = ap.parse_args()
    if (a.start or a.end) and len(a.seasons) > 1:
        print("--start/--end need a single season"); sys.exit(1)
    for y in a.seasons:
        export_season(y, a.start, a.end)
    print("\nDone. Upload the .parquet (or .csv) in the dashboard sidebar: 'Upload your own data'.")
