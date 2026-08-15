# MLB Pitch Mix Dashboard (v6.7)

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

## v6.7 — 11 more roster corrections + OPS in Period Comparison
- **Roster audit continued**, verified via web search (not guessed): Paul Goldschmidt
  (Cardinals → Yankees), Kyle Tucker (Astros → Dodgers, via the Dec-2024 trade that sent
  Isaac Paredes the other way to Houston), Alex Bregman (Astros → Cubs), Cody Bellinger
  (→ re-signed Yankees), Pete Alonso (Mets → Orioles), Andrew McCutchen (Pirates → non-roster
  minor-league invite elsewhere, removed), and the Cardinals' extensive rebuild — Nolan Arenado
  (→ Diamondbacks), Willson Contreras (→ Red Sox), Brendan Donovan (→ Mariners). Note: this
  covers every trade/signing surfaced by a 2026-offseason transactions sweep, which catches
  the highest-impact moves, but — as before — is not a guarantee every one of the ~200 remaining
  names is currently exactly correct. Live data mode remains the only fully-guaranteed-current
  source, since it reads real names/teams directly from Statcast rather than any hardcoded list.
- **New: OPS in Period Comparison.** Added real plate-appearance-outcome tracking (`is_pa_end`,
  `pa_event`) alongside the existing pitch-level data — walks, HBP, sac flies, and hit type
  (1B/2B/3B/HR), not just a crude "was it a hit" flag. For **real/live data**, this comes directly
  from Statcast's own `events` column (exact, no approximation). For **synthetic data**, it's a
  calibrated per-pitch approximation tuned to land around realistic MLB-average rates (~.700–.750
  league OPS) — flagged in the code as an approximation since pitches aren't grouped into true
  sequential at-bats in the generator.
- Period Comparison now shows **OPS P1 / OPS P2 / Δ OPS** (plus Δ OBP, Δ SLG) as columns, and
  **defaults the sort to Δ OPS** — directly answering "did this hitter's actual production get
  better or worse over that stretch," not just whether pitchers changed their approach.
- The existing "min. pitches per period" reliability filter (already in the tab) now also gates
  the OPS columns, so a low-sample OPS swing can't misleadingly dominate the sort — same
  guardrail requested for this feature, reusing the existing threshold rather than adding a
  second one.

## v6.6 — roster accuracy fixes + dataframe contrast bug
- **Confirmed and fixed 3 roster errors** in the synthetic data (verified via web search, not
  guessed): Bo Bichette moved from Toronto to the New York Mets (signed Jan 2026 — the synthetic
  roster had his pre-free-agency team); Charlie Blackmon removed entirely (retired in **2024**,
  this was a plain mistake on the model's part, not just staleness); Jeimer Candelario removed
  from the Reds (DFA'd, currently outrighted to Triple-A, not an active MLB player).
- **Standing caveat, not fully resolved**: the synthetic roster is a hardcoded ~208-name snapshot
  built from training knowledge. Only the 3 specifically reported errors were verified and fixed —
  the other ~205 names have **not** been individually re-verified against current rosters, and
  more may be stale (trades, retirements, injuries happen constantly). The only way to get
  guaranteed-current rosters is live data mode (the sidebar checkbox), which pulls real names and
  real teams directly from Statcast rather than any hardcoded list.
- **Real bug, not cosmetic**: dataframe cells using `.background_gradient()` (Period Comparison,
  Rankings, Team Rollup, etc.) could render **invisible white-on-white text** on pale gradient
  cells (e.g. light yellow near the middle of a color scale). Root cause: a `!important` CSS rule
  added in v6.4 to force white text everywhere was overriding pandas' own contrast-aware text
  color (which correctly picks dark text for light cells) with a blanket white — the opposite of
  what that rule was supposed to protect against. Fixed by removing the `!important` override so
  pandas' inline per-cell color can take effect; verified visually that pale cells now show dark
  text and dark cells still show light text, across the full gradient range.

## v6.5.1 — full re-test pass (visual, all 9 tabs, all languages)
Did a complete re-verification after v6.5: real-browser screenshots of every tab (not just
the ones that had bugs before), plus the full headless regression suite. Found and fixed one
more real bug in the process:
- **Digest download button was hardcoded in Polish** (`"⬇ Pobierz digest (.md)"`) regardless
  of the selected UI language — a leftover from before i18n was wired through that specific
  function. Fixed and swept the rest of the codebase for similar leftovers (none found).
- Extended the "thin ticks above ~15 labels" fix (previously only on heatmaps) to every
  week-axis line/bar chart (trend, delta bars, outcome overlay, platoon context, velocity,
  comparison, matchup line) for consistency — dense-but-technically-not-overlapping tick
  labels are now readable everywhere, not just where the collision was most visible.
- All 9 tabs visually confirmed clean: no duplicate widgets, no overlapping text, correct
  dark theme/contrast, Period Comparison table showing all 210 batters with real team names
  and working sort in both directions.

## v6.5 — visually verified fixes + Period Comparison tab
This round was verified with an actual headless browser (Playwright) against the real
running app, not just code review — screenshots below are what caught these:
- **Duplicate sidebar (real bug)**: the app rendered "Pitch Mix Analyzer" and a "Seasons"
  picker *twice* — once before data load (needed to know which seasons to fetch) and again
  inside `SidebarFilters`, which unconditionally re-rendered its own copy whose value was then
  silently overwritten. Fixed: `SidebarFilters` now accepts the already-chosen seasons and skips
  re-rendering that widget entirely.
- **Bar-chart text collisions (real bug, not just cosmetic)**: on Biggest Movers, Sustained
  Movers, and Matchup Changes, a bar whose magnitude approached the axis extreme had its
  "outside" text label collide directly with the row's own y-axis category label (visually
  confirmed via screenshot — e.g. "Julio Rodriguez · BB%" overlapping "-88.8pp" into an
  unreadable smear). Fixed by padding every such chart's axis range beyond the data's min/max
  so outside labels always have room.
- **Heatmap text cramming with wide date ranges**: with many weeks selected, per-cell "%"
  text and x-axis week labels smeared into each other. Fixed: per-cell text now suppresses
  above ~20 weeks (color + hover tooltip still convey the value), and x-axis ticks thin out
  to ~15 evenly-spaced labels instead of cramming every week in.
- **KPI number truncation**: fixed the v6.4 overlap fix's side effect where long numbers
  (e.g. "411,362") got ellipsis-truncated at narrow card widths. Now uses CSS container
  queries (`cqi` units) so font size responds to each card's *actual* rendered width instead
  of just overall viewport width — correctly handles any number of cards sharing a row.
- Re dark theme/white-on-white reports: the `.streamlit/config.toml` dark theme and CSS from
  v6.4 were verified correct in a real browser — actual root cause of contrast complaints
  traced to the duplicate-sidebar and chart-collision bugs above, now fixed.
- **New: Period Comparison tab** — pick two independent custom week ranges (e.g. weeks 1-10 vs
  11-20) and get one wide table covering **every MLB batter** (whole league, independent of any
  sidebar name filter) with the change in FB%/BB%/OS%, average velocity, and all 13 zones between
  the two periods. Sort by any single column, either direction (e.g. "biggest Zone 9% decrease
  first") — exactly the "biggest change to zone 9, positive or negative" workflow requested.
  Full-width CSV export included.

## v6.4 — dark-theme contrast, chart visibility, spacing
- **`.streamlit/config.toml` added** — sets an explicit dark theme (`textColor = "#f0f6fc"`) so
  every *native* Streamlit widget (labels, dataframes, sliders, checkboxes) gets white text on
  the dark background by default, instead of relying only on CSS overrides guessing at Streamlit's
  internal (and frequently-changing) class names.
- **Real bug fix, not just cosmetic**: several heatmaps (weekly pitch-mix heatmap, matchup
  heatmap) had colorscales that ended at pure white (`#ffffff`) while using white/unset text —
  meaning the value label became **literally invisible** on the highest-value cells. Colorscales
  now stay bounded between a dark slate and a warm amber, with explicit dark text on top, so labels
  stay readable across the whole range. Same fix applied to the zone diamond.
- **Chart margins widened** across every horizontal bar chart (Biggest Movers, Sustained Movers,
  Team Rollup, Adjustment Score ranking, Matchup Changes) so outside-positioned value labels never
  clip or crowd the edge.
- **Week-axis charts now rotate tick labels** (trend, delta bars, outcome overlay, platoon context,
  velocity, comparison, matchup line) so week labels don't overlap when many weeks are in view.
- **KPI cards**: numbers now use `tabular-nums` and a fluid `clamp()` font size instead of a fixed
  2rem, so a long number (e.g. "148,919") shrinks to fit its card instead of overlapping the
  neighboring card; labels/values get `text-overflow: ellipsis` as a safety net.
- All hardcoded dim/muted chart text colors (`#7d8590`, `#c9d1d9` in text roles) bumped to a
  brighter `#f0f6fc` for stronger contrast against the dark background.

## v6.3 — full league, batter-first matchups, honest share card
- **Whole league**: synthetic data now covers all 30 MLB teams, ~210 batters (7/team) and 55
  pitchers, up from 6 teams / 30 batters / 18 pitchers. Team names/rosters are representative
  real players for demo flavor, not a live roster feed — swap in real data (parquet or live) for
  an always-current roster.
- **Batter × Week tab (was "Matchup Detail")**: this used to force picking a pitcher first, then a
  batter. It's now batter-first: pick a batter and a week, and see a table of **every pitcher
  they faced that week** with each one's pitch mix — e.g. "what were Adley Rutschman's stats
  across all matchups in week 1." The old single-pitcher trend-across-weeks view still exists,
  now inside an optional "drill into one pitcher" expander.
- **Honest Player Report headline**: the "did you know you had the biggest change in the league"
  card previously showed that framing for *every* selected player regardless of whether it was
  true — it only ever reflected that player's own biggest category change, never actually checked
  against the rest of the league. It now computes the player's real league-wide rank for that week
  (`compute.batter_week_rank`, scored against every batter league-wide, ignoring any sidebar name
  filter) and only uses the superlative phrasing when they're genuinely #1 — otherwise it states
  their honest rank (e.g. "#5 of 142 qualifying hitters") or a neutral framing if not enough data
  exists to rank them confidently.

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
