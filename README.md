# MLB Pitch Mix Dashboard (v6.2)

Batter-centric pitch-mix analyzer: shows how the *league's* approach to a hitter
changes week over week, across **16 tracked categories**:

- Fastball % / Breaking Ball % / Offspeed %
- 13 individual Statcast zones (zone1–zone9, zone11–zone14 — zone 10 doesn't exist)

## What's new in v5
- Categories are now a single generalized registry (`config.ALL_CATEGORIES`) instead
  of 4 hardcoded columns — compute logic loops over all 16 automatically.
- **Zone diamond** chart: strike-zone-shaped heatmap showing which zone changed most.
- **Biggest Movers leaderboard**: ranks every batter-week by its single largest
  change across *any* of the 16 categories — the "did you know..." stat.
- **Player Report tab**: a clean, shareable card designed to send to a team or
  player ("You had the biggest change in FB% this week — here's the full picture").

## What's new in v6
- **Sample-size guard**: every delta now carries a `reliable` flag (needs ≥20 pitches in both
  weeks being compared, configurable via `config.MIN_RELIABLE_PITCHES`). Leaderboards filter to
  reliable rows by default.
- **Rolling baseline**: alongside "vs last week," every category also has a "vs rolling 3-week
  baseline" delta (`config.BASELINE_WEEKS`) — toggleable in Player Report / Rankings — which is
  far less noisy than a single-week comparison.
- **Outcome-aware**: whiff%, BA (proxy), and avg exit velocity are tracked per batter per week and
  overlaid against Adjustment Score, so you can see whether a pitch-mix change actually worked.
- **Platoon/count context**: % of pitches seen vs LHP and % in 2-strike counts, with an automatic
  "confound flag" when handedness mix swings ≥20pp week-over-week (a likely false-positive driver).
  Note: count-state on synthetic data is a per-pitch proxy, not sequenced at-bats — this becomes
  exact once real Statcast data (which has real `balls`/`strikes`) is used via the pybaseball path.
- **Velocity tracking**: avg release speed per pitch type per batter per week — catches "same
  pitch, thrown harder" adjustments that usage/location miss entirely.
- **Sustained trend detector**: generalized the old FB%-only streak insight to all 16 categories —
  surfaces ≥3-week trends, which are a more credible signal than a single big week.
- **Team rollup**: Adjustment Score aggregated to team level (synthetic team assignment in this
  demo — swap in real rosters via `config.TEAM_OF_BATTER`).
- **Weekly digest generator**: auto-written markdown summary of the week's biggest movers,
  downloadable/copyable. Actually *sending* it (email/Slack) needs a separate scheduled job that
  calls `compute.generate_weekly_digest()` — not built into the Streamlit app itself.

## v6.1 — crash fix for hosted deployments
- **Root cause of the "oh no, error running app" crash:** live Statcast fetching used to run
  automatically on every cold start for whichever seasons were selected (default: two seasons,
  ~180 days each). On memory-constrained hosting (e.g. free Streamlit Community Cloud, ~1GB RAM),
  pulling that much raw Statcast data (90+ columns before trimming) gets the process OOM-killed —
  which produces no Python traceback, just a dead process and Streamlit's generic error page.
- **Fix:** live data fetching is now **opt-in** (checkbox, off by default) and **bounded** to a
  short recent window (3–30 days, configurable in the sidebar) instead of the full season. Numeric
  columns are also downcast (float32/int16) to reduce memory further. Default behavior (checkbox
  off) never touches pybaseball at all — it's exactly as safe/fast as before.
- If you want a full real season loaded fast with no live-fetch risk at all, still use `data_pipeline.ipynb`
  to bake a `data/pitch_mix_<year>.parquet` file — that path was never affected by this issue.

## v6.2 — language switcher
- New sidebar language selector: **English (default), Polski, Français, Español, 日本語**.
- Every static UI string (headers, tabs, captions, buttons, table columns) and every
  dynamically-generated text (insights, weekly digest, shareable Player Report card) is now
  routed through `i18n.py` and switches live with the selector — no page reload needed.
- Scope note: category *abbreviations* (FB%, Z7%, etc.) and the longer zone descriptions baked
  into `config.py` at import time are English-only regardless of the UI language — translating
  those fully would require restructuring how categories are built (currently a static dict built
  once at module load). Everything else in the app is fully translated.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data
Looks for `data/pitch_mix_<year>.parquet` first (see `data_pipeline.ipynb` to build
one from real Statcast data via `pybaseball`), falls back to `pybaseball.statcast()`
live, falls back to realistic synthetic data if neither is available — so it always runs.
