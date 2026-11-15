# data/ — put your files here (commit them to the repo)

The app scans this folder (and the repo root) at start-up and tells you in the sidebar panel
**"📁 Data files detected"** what it found. Recognized by their columns, not their names:

| File | Used for |
|---|---|
| pitch-by-pitch with dates — output of `export_statcast_data.py` (`statcast_export_<year>.parquet/.csv`) or a raw *Statcast Search* CSV from Baseball Savant | **all weekly analysis** (pitch-mix changes, OPS, Period Comparison, Week by Week, AI) |
| `players_summary_<year>.csv` (bat tracking, one row per player) | 🦇 Bat tracking view |
| `detail_zone_pitchgroup_<year>.csv` (bat tracking by zone × pitch group) | 🦇 Bat tracking view |
| `swings_by_player_and_pitchgroup_<year>.csv` (pitcher × hitter swings) | recognized, not used yet |

* Put the **year in the file name** (e.g. `statcast_export_2026.parquet`): the app loads **one season at a time**
  (the sidebar "Seasons" picker, default = latest) to keep memory low — about 0.6 GB per full season.
* Prefer **Parquet** (about 5 MB per season instead of ~100 MB CSV).
* Season totals (bat tracking) have no dates, so they cannot show week-to-week changes — only pitch-by-pitch files can.
