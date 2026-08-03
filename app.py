"""
app.py – Pitch Mix Dashboard v5
Analiza pitch mix rzucanego DO pałkarzy w ujęciu tygodniowym.
Teraz z 16 śledzonymi kategoriami (FB%/BB%/OS% + 13 stref Statcast)
i shareable "Player Report" do wysłania drużynie / graczowi.

Uruchomienie:
    pip install streamlit pandas numpy plotly
    streamlit run app.py
"""
from __future__ import annotations

import time as _time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    APP_CSS, AVAILABLE_SEASONS, CAT_COLS, PITCH_CAT_COLS, ZONE_CAT_COLS,
    CAT_COLORS, ALL_CATEGORIES, PITCH_TYPES, MIN_RELIABLE_PITCHES, BASELINE_WEEKS,
)
from data_layer import load_data
from compute import (
    precompute_all,
    filter_batter_weekly, filter_batter_delta,
    filter_matchup_weekly, filter_matchup_delta, filter_velo_weekly,
    generate_batter_insights,
    biggest_movers_leaderboard, latest_week_headline,
    sustained_movers_leaderboard, team_rollup_table, generate_weekly_digest,
)
from ui_components import (
    SidebarFilters,
    themed, themed_rot,
    render_kpis, section, empty, insight_box, export_csv,
    chart_batter_trend, chart_batter_delta_bars, chart_batter_heatmap,
    chart_zone_diamond, chart_adj_score_ranking, chart_comparison,
    chart_matchup_line, chart_matchup_heatmap,
    chart_biggest_changes, chart_biggest_movers, render_share_card,
    chart_outcome_trend, chart_platoon_context, chart_velo_trend,
    chart_team_rollup, chart_sustained_movers, render_digest_block,
)

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="⚾ Pitch Mix Dashboard",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(APP_CSS, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="dash-header">
    <h1>⚾ Pitch Mix Dashboard</h1>
    <p class="subtitle">
        Jak zmienia się pitch mix rzucany DO pałkarza tydzień po tygodniu?
        FB% · BB% · OS% · 13 stref Statcast · outcomes · velo · platoon · Adjustment Score
    </p>
    <span class="badge">v6 · 16 kategorii · sample-size guard · outcome-aware · batter-centric</span>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
#  SIDEBAR + LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚾ Pitch Mix Analyzer")
    st.markdown("### 📅 Sezony")
    _seasons_sel = st.multiselect(
        "Sezony", AVAILABLE_SEASONS, default=[2025, 2026],
        label_visibility="collapsed", key="_seasons_pre",
    )
    if not _seasons_sel:
        _seasons_sel = [2026]

with st.spinner("⚾ Ładowanie danych…"):
    raw_df, data_source = load_data(tuple(sorted(_seasons_sel)))

raw_df["game_date"] = pd.to_datetime(raw_df["game_date"])

filters = SidebarFilters(raw_df)
filters.seasons = _seasons_sel

# ─────────────────────────────────────────────────────────────────────────────
#  PRECOMPUTE
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner("📊 Obliczanie statystyk (16 kategorii, cache po pierwszym uruchomieniu)…"):
    pc = precompute_all(raw_df)

bw_all   = pc["batter_weekly"]
bd_all   = pc["batter_delta"]
mw_all   = pc["matchup_weekly"]
md_all   = pc["matchup_delta"]
velo_all = pc["velo_weekly"]
pc_ms    = pc["perf_ms"]

season_str = ", ".join(str(y) for y in sorted(filters.seasons))
src_icon   = "📂" if data_source == "parquet" else ("🌐" if data_source == "Statcast" else "🎲")
st.markdown(
    f'<span class="perf-pill">'
    f'{src_icon} {data_source} · sezony {season_str} · '
    f'precompute {pc_ms} ms · filtr ~5 ms · min. {MIN_RELIABLE_PITCHES} pitchy dla "reliable" · '
    f'baseline {BASELINE_WEEKS} tyg.'
    f'</span>',
    unsafe_allow_html=True,
)
st.markdown("")

# ─────────────────────────────────────────────────────────────────────────────
#  FILTROWANIE
# ─────────────────────────────────────────────────────────────────────────────
_tf = _time.perf_counter()

bw = filter_batter_weekly(bw_all, filters.d_start, filters.d_end, filters.sel_batters, filters.seasons)
bd = filter_batter_delta(bd_all, filters.d_start, filters.d_end, filters.sel_batters, filters.seasons,
                          filters.min_pitches, filters.min_prev)
mw = filter_matchup_weekly(mw_all, filters.d_start, filters.d_end,
                            filters.sel_pitchers, filters.sel_batters, filters.sel_pt, filters.seasons)
md = filter_matchup_delta(md_all, filters.d_start, filters.d_end,
                           filters.sel_pitchers, filters.sel_batters, filters.sel_pt, filters.seasons,
                           filters.min_pitches, filters.min_prev)
velo = filter_velo_weekly(velo_all, filters.d_start, filters.d_end, filters.sel_batters)
_tf_ms = round((_time.perf_counter() - _tf) * 1000, 1)

if bw.empty and mw.empty:
    st.warning("⚠️ Brak danych dla wybranych filtrów — zmień kryteria w sidebarze.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
#  GLOBAL KPIs
# ─────────────────────────────────────────────────────────────────────────────
n_batters_f  = bw["batter_name"].nunique()
n_pitchers_f = mw["pitcher_name"].nunique() if not mw.empty else 0
n_pitches_f  = int(bw["total"].sum()) if not bw.empty else 0
n_matchups_f = mw.groupby(["pitcher_name", "batter_name"]).ngroups if not mw.empty else 0
n_weeks_f    = bw["week_start"].nunique() if not bw.empty else 0
avg_adj      = round(bd["adj_score"].mean(), 1) if not bd.empty else 0

render_kpis([
    {"label": "Pitches do battera", "value": f"{n_pitches_f:,}", "sub": "łącznie w filtrze"},
    {"label": "Tygodnie",           "value": str(n_weeks_f),      "sub": "zakresu analizy"},
    {"label": "Batters",            "value": str(n_batters_f),    "sub": "pałkarzy"},
    {"label": "Pitchers",           "value": str(n_pitchers_f),   "sub": "miotaczy"},
    {"label": "Matchups",           "value": f"{n_matchups_f:,}", "sub": "par pitcher-batter"},
    {"label": "Avg Adj.Score",      "value": str(avg_adj), "sub": "16 kategorii łącznie", "highlight": True},
    {"label": "Filtr",              "value": str(_tf_ms), "sub": "ms per interakcja"},
])

# ─────────────────────────────────────────────────────────────────────────────
#  TABY
# ─────────────────────────────────────────────────────────────────────────────
(tab_profile, tab_report, tab_velo, tab_compare, tab_changes,
 tab_matchup, tab_ranking, tab_team) = st.tabs([
    "🏏 Profil Pałkarza",
    "🎖️ Player Report",
    "🌡️ Velo & Kontekst",
    "🆚 Porównanie",
    "📊 Zmiany Matchup",
    "🔍 Szczegóły Matchupu",
    "📈 Rankingi",
    "🏟️ Team & Digest",
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 – PROFIL PAŁKARZA
# ══════════════════════════════════════════════════════════════════════════════
with tab_profile:
    st.markdown("""
    > **Jak czytać tę zakładkę:** dla każdego tygodnia liczymy WSZYSTKIE pitche
    > rzucone do wybranego battera i pokazujemy jak zmieniał się ich mix
    > FB%/BB%/OS% oraz rozkład per strefa Statcast (13 stref).
    """)

    if bw.empty:
        empty("Brak danych batter-weekly. Zmień filtry.")
        st.stop()

    avail_batters = sorted(bw["batter_name"].unique())
    col_sel, col_info = st.columns([2, 3])
    with col_sel:
        sel_batter = st.selectbox("🏏 Wybierz pałkarza", avail_batters, key="profile_batter")

    bw_b = bw[bw["batter_name"] == sel_batter].sort_values("week_start")
    bd_b = bd[bd["batter_name"] == sel_batter].sort_values("week_start")

    with col_info:
        if not bw_b.empty:
            total_px   = int(bw_b["total"].sum())
            n_wk       = len(bw_b)
            avg_fb     = round(bw_b["fb_pct"].mean(), 1)
            top_adj_wk = (bd_b.loc[bd_b["adj_score"].idxmax(), "week_label"].replace("\n", " ").replace("·", "").strip()
                          if not bd_b.empty else "—")
            render_kpis([
                {"label": "Pitchy do niego", "value": f"{total_px:,}", "sub": "w wybranym okresie"},
                {"label": "Tygodnie",         "value": str(n_wk),      "sub": "obserwacji"},
                {"label": "Śr. FB%",          "value": f"{avg_fb}%",   "sub": "fastballe"},
                {"label": "Max adj. tydzień", "value": top_adj_wk, "sub": "największe dostosowanie", "highlight": True},
            ])

    if not bd_b.empty:
        for ins in generate_batter_insights(bd_b, sel_batter):
            insight_box(ins)

    section("📊 Tygodniowy Mix — Pitch Type (FB%/BB%/OS%)")
    if bw_b.empty:
        empty(f"Brak danych tygodniowych dla {sel_batter}.")
    else:
        st.plotly_chart(chart_batter_trend(bw, sel_batter), use_container_width=True, key="profile_trend")

        section("📉 Zmiany Tydzień do Tygodnia (pitch type)")
        if bd_b.empty:
            st.info("Za mało tygodni / pitchy by policzyć deltę — obniż progi w sidebarze.")
        else:
            st.plotly_chart(chart_batter_delta_bars(bd, sel_batter), use_container_width=True, key="profile_delta_bars")

        col_ht, col_tbl = st.columns([3, 2])
        with col_ht:
            section("🗓️ Heatmapa (tygodnie × FB/BB/OS)")
            st.plotly_chart(chart_batter_heatmap(bw, sel_batter), use_container_width=True, key="profile_heatmap")
        with col_tbl:
            section("📋 Tabela delt (pitch type)")
            if not bd_b.empty:
                disp_cols = {
                    "week_label_short": "Tydzień",
                    "fb_pct": "FB%", "bb_pct": "BB%", "os_pct": "OS%",
                    "d_fb": "ΔFB", "d_bb": "ΔBB", "d_os": "ΔOS",
                    "adj_score": "Adj.Score", "total": "Pitchy",
                }
                cols_avail = [c for c in disp_cols if c in bd_b.columns]
                tbl = bd_b[cols_avail].rename(columns=disp_cols)
                fmt = {}
                for c in tbl.columns:
                    if "%" in c and "Δ" not in c: fmt[c] = "{:.1f}%"
                    elif "Δ" in c: fmt[c] = "{:+.1f}"
                    elif c == "Adj.Score": fmt[c] = "{:.1f}"
                st.dataframe(
                    tbl.style.background_gradient(subset=["Adj.Score"] if "Adj.Score" in tbl.columns else [], cmap="YlOrRd")
                       .format(fmt, na_rep="—"),
                    use_container_width=True, height=320,
                )
                export_csv(bd_b, f"batter_delta_{sel_batter.replace(' ','_')}.csv", "⬇ Pobierz CSV")

        # ── NOWE: Zone diamond ──────────────────────────────────────────────
        section("🎯 Rozkład per strefa (Statcast zone diamond)")
        st.caption(
            "Kolor = zmiana (Δ pp) udziału rzutów w danej strefie względem poprzedniego tygodnia. "
            "Zielony = więcej rzutów w tej strefie, czerwony = mniej."
        )
        zc1, zc2 = st.columns(2)
        with zc1:
            zmode = st.radio("Widok", ["Zmiana (Δ)", "Poziom (%)"], horizontal=True, key="zone_mode")
        mode_key = "delta" if zmode == "Zmiana (Δ)" else "level"
        st.plotly_chart(chart_zone_diamond(bw, sel_batter, bd=bd, mode=mode_key), use_container_width=True, key="profile_zone_diamond")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 – PLAYER REPORT (shareable) — NOWE
# ══════════════════════════════════════════════════════════════════════════════
with tab_report:
    section("🎖️ Player Report — gotowe do wysłania drużynie / graczowi")
    st.caption(
        "Automatycznie wygenerowany, 'shareable' insight: który pałkarz miał największą "
        "pojedynczą zmianę podejścia pitcherów w ostatnim tygodniu, w KTÓREJKOLWIEK z 16 "
        "śledzonych kategorii (FB%/BB%/OS% lub dowolna z 13 stref)."
    )

    if bd.empty:
        empty("Za mało danych by wygenerować report. Obniż progi w sidebarze.")
    else:
        rc0a, rc0b = st.columns([2, 1])
        with rc0a:
            rep_batter = st.selectbox("Wybierz pałkarza do reportu", sorted(bd["batter_name"].unique()),
                                       key="report_batter")
        with rc0b:
            use_base = st.checkbox(
                f"Użyj rolling baseline ({BASELINE_WEEKS} tyg.) zamiast pojedynczego tygodnia",
                value=False, key="report_use_base",
                help="Baseline porównuje bieżący tydzień do średniej z ostatnich "
                     f"{BASELINE_WEEKS} tygodni — mniej wrażliwe na szum małej próby.",
            )
        bd_rep = bd[bd["batter_name"] == rep_batter].sort_values("week_start")
        headline = latest_week_headline(bd_rep, use_baseline=use_base)

        if headline is None:
            empty("Brak wystarczających danych tygodniowych dla tego battera.")
        else:
            render_share_card(rep_batter, headline)
            if not headline.get("reliable", True):
                st.warning(
                    f"⚠️ Ten tydzień ma mniej niż {MIN_RELIABLE_PITCHES} pitchy w bieżącym lub "
                    "poprzednim/baseline oknie — traktuj tę liczbę jako wstępny sygnał, nie pewnik."
                )

            rc1, rc2 = st.columns([1, 1])
            with rc1:
                section("Trend FB%/BB%/OS%")
                st.plotly_chart(chart_batter_trend(bw, rep_batter), use_container_width=True, key="report_trend")
            with rc2:
                section("Zone diamond (Δ ostatni tydzień)")
                st.plotly_chart(chart_zone_diamond(bw, rep_batter, bd=bd, mode="delta"), use_container_width=True, key="report_zone_diamond")

            section("🎯 Czy to zadziałało? Outcome overlay")
            st.caption("Whiff% i BA (proxy) w czasie, na tle Adjustment Score — sprawdź czy tygodnie "
                      "z dużym adjustmentem faktycznie idą w parze ze zmianą wyników battera.")
            st.plotly_chart(chart_outcome_trend(bd, rep_batter), use_container_width=True, key="report_outcome_trend")

            st.divider()
            section("🏆 Top 15 — Kto miał NAJWIĘKSZĄ zmianę w tym okresie (wszystkie 16 kategorii)")
            st.caption(
                "Domyślnie tylko wiarygodne wiersze (≥ "
                f"{MIN_RELIABLE_PITCHES} pitchy w obu tygodniach). Każdy wiersz to batter + tydzień + "
                "jego największa pojedyncza zmiana (FB%, BB%, OS%, lub dowolna strefa)."
            )
            rel_toggle = st.checkbox("Pokaż tylko wiarygodne (reliable) wiersze", value=True, key="report_rel_toggle")
            lb = biggest_movers_leaderboard(bd, top_n=15, reliable_only=rel_toggle, use_baseline=use_base)
            st.plotly_chart(chart_biggest_movers(lb), use_container_width=True, key="report_biggest_movers")
            export_csv(lb, "biggest_movers_leaderboard.csv", "⬇ CSV leaderboardu")

            section("📈 Sustained Movers — trwałe trendy (≥3 tygodnie), nie pojedynczy skok")
            st.caption("Bardziej wiarygodny sygnał niż jeden duży tydzień: kto ma dłuższy trend w tym samym kierunku.")
            sust = sustained_movers_leaderboard(bd, top_n=12, min_streak=3)
            if sust.empty:
                st.info("Brak trendów ≥3 tygodnie w obecnym filtrze — spróbuj rozszerzyć zakres dat.")
            else:
                st.plotly_chart(chart_sustained_movers(sust), use_container_width=True, key="report_sustained_movers")
                export_csv(sust, "sustained_movers.csv", "⬇ CSV sustained movers")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 – VELOCITY & KONTEKST (platoon/count)  — NOWE
# ══════════════════════════════════════════════════════════════════════════════
with tab_velo:
    section("🌡️ Prędkość rzutów i kontekst platoon/count")
    st.caption(
        "Dwa dodatkowe sygnały, których nie widać w samym pitch-mix: (1) czy pitcherzy rzucają "
        "TEN SAM pitch z inną prędkością, i (2) czy zmiana mixu może wynikać z innego kontekstu "
        "(więcej leworęcznych pitcherów / więcej sytuacji 2-strike) zamiast prawdziwego adjustmentu."
    )

    if bd.empty:
        empty("Brak danych. Zmień filtry.")
    else:
        avail_vc = sorted(bd["batter_name"].unique())
        sel_vc = st.selectbox("🏏 Wybierz pałkarza", avail_vc, key="velo_ctx_batter")

        section("Prędkość per pitch type (mph)")
        st.caption("Ten sam pitch rzucony wyraźnie mocniej/słabiej tydzień-do-tygodnia też jest 'adjustmentem' — "
                  "usage% i strefy tego nie łapią.")
        if velo.empty or velo[velo["batter_name"] == sel_vc].empty:
            empty(f"Brak danych o prędkości dla {sel_vc}.")
        else:
            st.plotly_chart(chart_velo_trend(velo, sel_vc), use_container_width=True, key="velo_trend_chart")
            velo_b = velo[velo["batter_name"] == sel_vc].dropna(subset=["d_velo"])
            if not velo_b.empty:
                big_velo = velo_b.loc[velo_b["d_velo"].abs().idxmax()]
                st.info(
                    f"Największa zmiana prędkości: **{big_velo['pitch_type']}** "
                    f"**{big_velo['d_velo']:+.1f} mph** w tygodniu {big_velo['week_label_short']} "
                    f"(N={int(big_velo['n'])})."
                )

        section("Kontekst platoon (% rzutów vs LHP)")
        st.plotly_chart(chart_platoon_context(bd, sel_vc), use_container_width=True, key="platoon_context_chart")
        st.caption(
            "Jeśli słupek jest czerwony, % rzutów vs LHP zmienił się o ≥20pp względem poprzedniego "
            "tygodnia — część zmiany pitch-mix w tym tygodniu może wynikać z tego, a nie z faktycznego "
            "dostosowania podejścia."
        )

        section("% rzutów w sytuacji 2-strike")
        bd_vc = bd[bd["batter_name"] == sel_vc].sort_values("week_start")
        if "pct_two_strike" in bd_vc.columns and not bd_vc.empty:
            st.plotly_chart(
                themed(
                    go.Figure(go.Bar(
                        x=bd_vc["week_label_short"], y=bd_vc["pct_two_strike"],
                        marker_color="#bc8cff",
                        hovertemplate="Tydzień: %{x}<br>%% w 2-strike: %{y:.1f}%%<extra></extra>",
                    )),
                    height=240, title=f"% rzutów w sytuacji 2-strike · {sel_vc}",
                    xaxis_title="Tydzień", yaxis_title="%",
                ),
                use_container_width=True,
                key="two_strike_chart",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 – PORÓWNANIE
# ══════════════════════════════════════════════════════════════════════════════
with tab_compare:
    section("🆚 Porównanie pałkarzy — pitch mix do nich")
    st.caption("Wybierz 2-4 pałkarzy i kategorię (pitch-type LUB strefę) aby porównać.")

    if bw.empty:
        empty()
    else:
        avail_cmp = sorted(bw["batter_name"].unique())
        c1, c2 = st.columns([3, 1])
        with c1:
            cmp_batters = st.multiselect(
                "Wybierz pałkarzy (2-4)", avail_cmp,
                default=avail_cmp[:3] if len(avail_cmp) >= 3 else avail_cmp,
                max_selections=4, key="cmp_batters",
            )
        with c2:
            cmp_mode = st.radio("Tryb", ["Pitch type (FB/BB/OS)", "Jedna kategoria (w tym strefy)"],
                                horizontal=False, key="cmp_mode")

        if not cmp_batters:
            empty("Wybierz co najmniej jednego pałkarza.")
        elif cmp_mode == "Jedna kategoria (w tym strefy)":
            sel_cat_cmp = st.selectbox(
                "Kategoria", CAT_COLS,
                format_func=lambda x: ALL_CATEGORIES[x]["label"],
                key="cmp_cat",
            )
            st.plotly_chart(chart_comparison(bw, cmp_batters, sel_cat_cmp), use_container_width=True, key="compare_single_cat")
        else:
            grid_cols = st.columns(len(PITCH_CAT_COLS))
            for ci, col_cat in enumerate(PITCH_CAT_COLS):
                with grid_cols[ci]:
                    st.plotly_chart(chart_comparison(bw, cmp_batters, col_cat), use_container_width=True, key=f"compare_grid_{col_cat}")

        section("📋 Tabela średnich (pitch type)")
        if cmp_batters and not bw.empty:
            bw_cmp = bw[bw["batter_name"].isin(cmp_batters)]
            avg_tbl = bw_cmp.groupby("batter_name")[PITCH_CAT_COLS].mean().round(1).reset_index()
            avg_tbl.columns = ["Batter"] + [ALL_CATEGORIES[c]["short"] for c in PITCH_CAT_COLS]
            st.dataframe(
                avg_tbl.style.background_gradient(cmap="RdYlGn", subset=avg_tbl.columns[1:].tolist())
                       .format({c: "{:.1f}%" for c in avg_tbl.columns[1:]}),
                use_container_width=True,
            )
            export_csv(avg_tbl, "comparison_avg.csv", "⬇ CSV")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 – ZMIANY MATCHUP
# ══════════════════════════════════════════════════════════════════════════════
with tab_changes:
    section("📊 Największe zmiany pitch mix (pitcher → batter)")
    st.caption("Delta per pitcher × batter × pitch type.")

    if md.empty:
        empty("Brak danych delt. Obniż progi lub rozszerz zakres dat.")
    else:
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            pt_f = st.multiselect("Pitch type", sorted(md["PT"].unique()),
                                  format_func=lambda x: f"{x} – {PITCH_TYPES.get(x, x)}", key="chg_pt")
        with c2:
            direction = st.radio("Kierunek", ["Oba", "↑ Wzrost", "↓ Spadek"], horizontal=True, key="chg_dir")
        with c3:
            top_n = st.slider("Top N", 10, 100, 25, 5, key="chg_n")

        tbl_md = md.copy()
        if pt_f: tbl_md = tbl_md[tbl_md["PT"].isin(pt_f)]
        if direction == "↑ Wzrost": tbl_md = tbl_md[tbl_md["Δ pp"] > 0]
        elif direction == "↓ Spadek": tbl_md = tbl_md[tbl_md["Δ pp"] < 0]
        tbl_md = tbl_md.head(top_n)

        st.dataframe(
            tbl_md[["Pitcher","Batter","Week","Prev Week","Pitch Name","Now %","Prev %","Δ pp","Pitches"]]
            .style.background_gradient(subset=["Δ pp"], cmap="RdYlGn", vmin=-30, vmax=30)
            .format({"Now %": "{:.1f}%", "Prev %": "{:.1f}%", "Δ pp": "{:+.1f} pp"}),
            use_container_width=True, height=420,
        )
        col_dl, _ = st.columns([1, 4])
        with col_dl:
            export_csv(tbl_md, "biggest_changes.csv", "⬇ CSV")

        section("Top 20 zmian – wykres")
        st.plotly_chart(chart_biggest_changes(md, top_n=min(top_n, 25)), use_container_width=True, key="changes_top_chart")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 – SZCZEGÓŁY MATCHUPU
# ══════════════════════════════════════════════════════════════════════════════
with tab_matchup:
    section("🔍 Szczegóły matchupu pitcher → batter")

    if mw.empty:
        empty("Brak danych matchup. Zmień filtry.")
    else:
        avail_p = sorted(mw["pitcher_name"].unique())
        c1, c2 = st.columns(2)
        with c1:
            sel_p = st.selectbox("🎯 Pitcher", avail_p, key="mq_p")
        with c2:
            faced = sorted(mw[mw["pitcher_name"] == sel_p]["batter_name"].unique())
            sel_b = st.selectbox("🏏 Batter", faced, key="mq_b")

        mw_mb = mw[(mw["pitcher_name"] == sel_p) & (mw["batter_name"] == sel_b)]
        md_mb = md[(md["Pitcher"] == sel_p) & (md["Batter"] == sel_b)]

        if mw_mb.empty:
            empty("Brak danych dla tego matchupu.")
        else:
            render_kpis([
                {"label": "Tygodni razem",  "value": str(mw_mb["week_start"].nunique()), "sub": "obserwacji"},
                {"label": "Łącznie pitchy", "value": str(int(mw_mb.groupby("week_start")["n"].sum().sum())), "sub": "przez cały okres"},
                {"label": "Pitch types",    "value": str(mw_mb["pitch_type"].nunique()), "sub": "różnych typów"},
                {"label": "Max Δ pp",       "value": f"{md_mb['Abs Δ'].max():.1f}" if not md_mb.empty else "—",
                 "sub": "największa zmiana", "highlight": True},
            ])
            st.plotly_chart(chart_matchup_line(mw, sel_p, sel_b), use_container_width=True, key="matchup_line_chart")

            c_ht, c_tbl = st.columns([3, 2])
            with c_ht:
                section("Heatmapa pitch type × tydzień")
                st.plotly_chart(chart_matchup_heatmap(mw, sel_p, sel_b), use_container_width=True, key="matchup_heatmap_chart")
            with c_tbl:
                section("Delty dla tego matchupu")
                if md_mb.empty:
                    st.info("Za mało tygodni by policzyć deltę.")
                else:
                    show_md = md_mb[["Week", "Pitch Name", "Now %", "Prev %", "Δ pp", "Pitches"]].head(20)
                    st.dataframe(
                        show_md.style.background_gradient(subset=["Δ pp"], cmap="RdYlGn", vmin=-30, vmax=30)
                               .format({"Now %": "{:.1f}%", "Prev %": "{:.1f}%", "Δ pp": "{:+.1f} pp"}),
                        use_container_width=True, height=280,
                    )
                    export_csv(md_mb, f"matchup_{sel_p.split()[-1]}_{sel_b.split()[-1]}.csv", "⬇ CSV")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 – RANKINGI
# ══════════════════════════════════════════════════════════════════════════════
with tab_ranking:
    section("📈 Ranking pałkarzy — Adjustment Score")
    st.caption(
        "**Adjustment Score** = mean(|Δ|) po WSZYSTKICH 16 kategoriach × √(min_pitches/10). "
        "Im wyższy, tym bardziej pitcherzy zmieniali swoje podejście do tego battera."
    )

    if bd.empty:
        empty()
    else:
        c1, c2 = st.columns([1, 3])
        with c1:
            top_n_rank = st.slider("Top N", 5, 30, 15, key="rank_n")
        with c2:
            st.plotly_chart(chart_adj_score_ranking(bd, top_n_rank), use_container_width=True, key="adj_score_ranking_chart")

        section("🏆 Biggest Movers — dowolna z 16 kategorii")
        st.caption(
            "Ranking pojedynczych, największych tygodniowych zmian (nie średnia — pojedynczy rekord). "
            f"Sample-size guard: domyślnie tylko wiersze z ≥{MIN_RELIABLE_PITCHES} pitchy w obu tygodniach."
        )
        rmc1, rmc2, rmc3 = st.columns([1, 1, 1])
        with rmc1:
            top_n_mov = st.slider("Top N ruchów", 5, 40, 15, key="mov_n")
        with rmc2:
            rel_only_rank = st.checkbox("Tylko wiarygodne (reliable)", value=True, key="rank_rel_toggle")
        with rmc3:
            base_mode_rank = st.checkbox(f"Rolling baseline ({BASELINE_WEEKS} tyg.)", value=False, key="rank_base_toggle")
        lb_rank = biggest_movers_leaderboard(bd, top_n=top_n_mov, reliable_only=rel_only_rank, use_baseline=base_mode_rank)
        st.plotly_chart(chart_biggest_movers(lb_rank), use_container_width=True, key="rank_biggest_movers")
        export_csv(lb_rank, "biggest_movers_ranking.csv", "⬇ CSV rankingu")

        section("📈 Sustained Movers — trwałe trendy (≥3 tygodnie)")
        st.caption("Bardziej odporne na szum niż pojedynczy tydzień: streak_weeks × |skumulowana zmiana|.")
        sust_rank = sustained_movers_leaderboard(bd, top_n=15, min_streak=3)
        if sust_rank.empty:
            st.info("Brak trendów ≥3 tygodnie w obecnym filtrze.")
        else:
            st.plotly_chart(chart_sustained_movers(sust_rank), use_container_width=True, key="rank_sustained_movers")
            export_csv(sust_rank, "sustained_movers_ranking.csv", "⬇ CSV")

        rank_tbl = (
            bd.groupby("batter_name")
              .agg(Max_Adj=("adj_score", "max"), Avg_Adj=("adj_score", "mean"),
                   N_Weeks=("adj_score", "count"), Avg_FB=("fb_pct", "mean"),
                   Avg_BB=("bb_pct", "mean"), Avg_OS=("os_pct", "mean"))
              .round(1).sort_values("Max_Adj", ascending=False).head(top_n_rank).reset_index()
        )
        rank_tbl.columns = ["Batter", "Max Adj.", "Avg Adj.", "Tygodni", "Śr. FB%", "Śr. BB%", "Śr. OS%"]
        section("📋 Tabela rankingowa (pitch type)")
        st.dataframe(
            rank_tbl.style.background_gradient(subset=["Max Adj.", "Avg Adj."], cmap="YlOrRd")
                    .format({c: "{:.1f}" for c in rank_tbl.columns if c not in ("Batter", "Tygodni")}),
            use_container_width=True,
        )
        export_csv(rank_tbl, "adj_score_ranking.csv", "⬇ CSV rankingu")

        section("Ranking per kategoria pitch-type (max |Δ| per batter)")
        cat_cols_ui = st.columns(len(PITCH_CAT_COLS))
        for ci, col_cat in enumerate(PITCH_CAT_COLS):
            with cat_cols_ui[ci]:
                label = ALL_CATEGORIES[col_cat]["short"]
                color = ALL_CATEGORIES[col_cat]["color"]
                d_col = "d_" + col_cat.replace("_pct", "")
                abs_col = "abs_" + d_col
                if abs_col not in bd.columns:
                    st.caption(f"{label}: brak danych")
                    continue
                cat_rank = bd.groupby("batter_name")[abs_col].max().sort_values(ascending=False).head(10).reset_index()
                cat_rank.columns = ["Batter", f"Max |Δ| {label}"]
                fig_cr = go.Figure(go.Bar(
                    y=cat_rank["Batter"], x=cat_rank[f"Max |Δ| {label}"], orientation="h",
                    marker_color=color, text=cat_rank[f"Max |Δ| {label}"].round(1),
                    texttemplate="  %{text:.1f}", textposition="outside", cliponaxis=False,
                    textfont=dict(color="#c9d1d9", size=10),
                ))
                themed(fig_cr, height=320, title=f"Top {label}", xaxis_title="pp", yaxis_title="",
                       margin=dict(l=10, r=60, t=40, b=10))
                fig_cr.update_yaxes(autorange="reversed")
                st.plotly_chart(fig_cr, use_container_width=True, key=f"cat_rank_chart_{col_cat}")

        section("Ranking per strefa (max |Δ| per batter)")
        sel_zone_cat = st.selectbox(
            "Wybierz strefę", ZONE_CAT_COLS, format_func=lambda x: ALL_CATEGORIES[x]["label"], key="zone_rank_cat",
        )
        d_col_z = "d_" + sel_zone_cat.replace("_pct", "")
        abs_col_z = "abs_" + d_col_z
        if abs_col_z in bd.columns:
            zone_rank = bd.groupby("batter_name")[abs_col_z].max().sort_values(ascending=False).head(15).reset_index()
            zone_rank.columns = ["Batter", f"Max |Δ| {ALL_CATEGORIES[sel_zone_cat]['short']}"]
            fig_zr = go.Figure(go.Bar(
                y=zone_rank["Batter"], x=zone_rank.iloc[:, 1], orientation="h",
                marker_color=ALL_CATEGORIES[sel_zone_cat]["color"],
                text=zone_rank.iloc[:, 1].round(1), texttemplate="  %{text:.1f}",
                textposition="outside", cliponaxis=False, textfont=dict(color="#c9d1d9", size=10),
            ))
            themed(fig_zr, height=400, title=f"Top 15 · {ALL_CATEGORIES[sel_zone_cat]['label']}",
                   xaxis_title="pp", yaxis_title="")
            fig_zr.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_zr, use_container_width=True, key="zone_rank_chart")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 8 – TEAM VIEW & WEEKLY DIGEST  — NOWE
# ══════════════════════════════════════════════════════════════════════════════
with tab_team:
    section("🏟️ Team Rollup")
    st.caption(
        "Agreguje Adjustment Score na poziom drużyny pałkarza (syntetyczne przypisanie zespołów w tej "
        "wersji demo) — pokazuje, których drużyn hitterzy jako grupa są najbardziej 'atakowani' inaczej "
        "niż wcześniej."
    )
    if bd.empty:
        empty("Brak danych.")
    else:
        team_tbl = team_rollup_table(bd)
        st.plotly_chart(chart_team_rollup(team_tbl), use_container_width=True, key="team_rollup_chart")
        st.dataframe(
            team_tbl.rename(columns={
                "team": "Drużyna", "avg_adj": "Śr. Adj.Score", "max_adj": "Max Adj.Score",
                "n_batter_weeks": "N batter-tyg.", "top_batter": "Top batter",
                "top_mover_label": "Kategoria", "top_mover_delta": "Δ pp", "top_week": "Tydzień",
            }).style.background_gradient(subset=["Śr. Adj.Score", "Max Adj.Score"], cmap="YlOrRd")
              .format({"Śr. Adj.Score": "{:.1f}", "Max Adj.Score": "{:.1f}", "Δ pp": "{:+.1f}"}),
            use_container_width=True,
        )
        export_csv(team_tbl, "team_rollup.csv", "⬇ CSV team rollup")

    st.divider()
    section("📰 Weekly Digest — auto-wygenerowany, gotowy do skopiowania/wysłania")
    st.caption(
        "Digest dla NAJNOWSZEGO tygodnia w obecnym filtrze dat. To jest generator treści — żeby "
        "faktycznie wysyłać go automatycznie (email/Slack) co tydzień, potrzeba osobnej integracji "
        "poza samą aplikacją Streamlit (np. scheduled job odpalający tę samą funkcję)."
    )
    if bd.empty:
        empty("Brak danych.")
    else:
        digest_n = st.slider("Liczba pozycji w digest", 3, 10, 5, key="digest_n")
        digest_text = generate_weekly_digest(bd, top_n=digest_n)
        render_digest_block(digest_text)


# ─────────────────────────────────────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("""
<div style="text-align:center; color:#7d8590; font-size:.76rem; padding:8px 0">
    ⚾ Pitch Mix Dashboard v6 &nbsp;·&nbsp;
    <a href="https://baseballsavant.mlb.com" style="color:#58a6ff">Baseball Savant</a>
    &nbsp;·&nbsp;
    <a href="https://github.com/jldbc/pybaseball" style="color:#58a6ff">pybaseball</a>
    &nbsp;·&nbsp; Streamlit + Plotly + pandas
</div>
""", unsafe_allow_html=True)
