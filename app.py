"""
app.py – Pitch Mix Dashboard v6.2
Analiza pitch mix rzucanego DO pałkarzy w ujęciu tygodniowym.
16 śledzonych kategorii (FB%/BB%/OS% + 13 stref Statcast), outcome-aware,
opt-in bounded live-data fetch (v6.1 crash fix), i pełny language switcher
(en/pl/fr/es/ja — v6.2).

Uruchomienie:
    pip install -r requirements.txt
    streamlit run app.py
"""
from __future__ import annotations

import time as _time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from i18n import T, LANGUAGES, get_lang, set_lang
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
    biggest_movers_leaderboard, latest_week_headline, batter_week_rank, batter_week_matchup_table,
    sustained_movers_leaderboard, team_rollup_table, generate_weekly_digest,
    compute_period_comparison,
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
#  LANGUAGE SWITCHER  (must run before anything else renders text)
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(T("sidebar_language"))
    _lang_codes = list(LANGUAGES.keys())
    _current = get_lang()
    _sel_lang = st.selectbox(
        "Language", _lang_codes, index=_lang_codes.index(_current),
        format_func=lambda c: LANGUAGES[c], label_visibility="collapsed", key="_lang_select",
    )
    set_lang(_sel_lang)
lang = get_lang()

# ─────────────────────────────────────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="dash-header">
    <h1>{T("header_title", lang=lang)}</h1>
    <p class="subtitle">{T("header_subtitle", lang=lang)}</p>
    <span class="badge">{T("header_badge", lang=lang)}</span>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
#  SIDEBAR + LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(T("sidebar_app_name", lang=lang))
    st.markdown(T("sidebar_seasons_header", lang=lang))
    _seasons_sel = st.multiselect(
        T("sidebar_seasons_label", lang=lang), AVAILABLE_SEASONS, default=[2025, 2026],
        label_visibility="collapsed", key="_seasons_pre",
    )
    if not _seasons_sel:
        _seasons_sel = [2026]

    st.markdown(T("sidebar_live_header", lang=lang))
    _use_live = st.checkbox(
        T("sidebar_live_checkbox", lang=lang), value=False, key="use_live_data",
        help=T("sidebar_live_help", lang=lang),
    )
    _live_days = 14
    if _use_live:
        _live_days = st.slider(
            T("sidebar_live_days_label", lang=lang), 3, 30, 14, key="live_days_back",
            help=T("sidebar_live_days_help", lang=lang),
        )
        st.caption(T("sidebar_live_caption", lang=lang))

with st.spinner(f"⚾ {T('sidebar_app_name', lang=lang)}…"):
    raw_df, data_source = load_data(tuple(sorted(_seasons_sel)), use_live=_use_live, live_days_back=_live_days)

raw_df["game_date"] = pd.to_datetime(raw_df["game_date"])

filters = SidebarFilters(raw_df, lang=lang, seasons_override=_seasons_sel)

# ─────────────────────────────────────────────────────────────────────────────
#  PRECOMPUTE
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner("📊 …"):
    pc = precompute_all(raw_df)

bw_all   = pc["batter_weekly"]
bd_all   = pc["batter_delta"]
mw_all   = pc["matchup_weekly"]
md_all   = pc["matchup_delta"]
velo_all = pc["velo_weekly"]
pc_ms    = pc["perf_ms"]

season_str = ", ".join(str(y) for y in sorted(filters.seasons))
_source_label = {"parquet": T("source_parquet", lang=lang), "syntetyczne": T("source_synthetic", lang=lang)}.get(
    data_source, T("source_live", lang=lang) if "Statcast" in data_source else data_source
)
src_icon = "📂" if data_source == "parquet" else ("🌐" if "Statcast" in data_source else "🎲")
st.markdown(
    f'<span class="perf-pill">' +
    T("perf_pill", lang=lang, icon=src_icon, source=_source_label, season_str=season_str,
      ms=pc_ms, min_pitches=MIN_RELIABLE_PITCHES, baseline=BASELINE_WEEKS) +
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
# v6.3: league-wide view (ignores the sidebar batter search filter) so the Player
# Report "did you know" claim can be checked against the WHOLE league, not just
# whichever batters happen to be selected in the sidebar right now.
bd_league = filter_batter_delta(bd_all, filters.d_start, filters.d_end, [], filters.seasons,
                                 filters.min_pitches, filters.min_prev)
_tf_ms = round((_time.perf_counter() - _tf) * 1000, 1)

if bw.empty and mw.empty:
    st.warning(T("warn_no_data", lang=lang))
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
    {"label": T("kpi_pitches", lang=lang), "value": f"{n_pitches_f:,}", "sub": T("kpi_pitches_sub", lang=lang)},
    {"label": T("kpi_weeks", lang=lang),   "value": str(n_weeks_f),      "sub": T("kpi_weeks_sub", lang=lang)},
    {"label": T("kpi_batters", lang=lang), "value": str(n_batters_f),    "sub": T("kpi_batters_sub", lang=lang)},
    {"label": T("kpi_pitchers", lang=lang),"value": str(n_pitchers_f),   "sub": T("kpi_pitchers_sub", lang=lang)},
    {"label": T("kpi_matchups", lang=lang),"value": f"{n_matchups_f:,}", "sub": T("kpi_matchups_sub", lang=lang)},
    {"label": T("kpi_avg_adj", lang=lang), "value": str(avg_adj), "sub": T("kpi_avg_adj_sub", lang=lang), "highlight": True},
    {"label": T("kpi_filter", lang=lang),  "value": str(_tf_ms), "sub": T("kpi_filter_sub", lang=lang)},
])

# ─────────────────────────────────────────────────────────────────────────────
#  TABY
# ─────────────────────────────────────────────────────────────────────────────
(tab_profile, tab_report, tab_velo, tab_compare, tab_changes,
 tab_matchup, tab_ranking, tab_team, tab_period) = st.tabs([
    T("tab_profile", lang=lang), T("tab_report", lang=lang), T("tab_velo", lang=lang),
    T("tab_compare", lang=lang), T("tab_changes", lang=lang), T("tab_matchup", lang=lang),
    T("tab_ranking", lang=lang), T("tab_team", lang=lang), T("tab_period", lang=lang),
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 – PROFIL PAŁKARZA
# ══════════════════════════════════════════════════════════════════════════════
with tab_profile:
    st.markdown(T("profile_intro", lang=lang))

    if bw.empty:
        empty()
        st.stop()

    avail_batters = sorted(bw["batter_name"].unique())
    col_sel, col_info = st.columns([2, 3])
    with col_sel:
        sel_batter = st.selectbox(T("profile_select_batter", lang=lang), avail_batters, key="profile_batter")

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
                {"label": T("profile_kpi_pitches", lang=lang), "value": f"{total_px:,}", "sub": T("profile_kpi_pitches_sub", lang=lang)},
                {"label": T("kpi_weeks", lang=lang),            "value": str(n_wk),      "sub": T("profile_kpi_weeks_sub", lang=lang)},
                {"label": T("profile_kpi_fb", lang=lang),       "value": f"{avg_fb}%",   "sub": T("profile_kpi_fb_sub", lang=lang)},
                {"label": T("profile_kpi_maxadj", lang=lang),   "value": top_adj_wk,     "sub": T("profile_kpi_maxadj_sub", lang=lang), "highlight": True},
            ])

    if not bd_b.empty:
        for ins in generate_batter_insights(bd_b, sel_batter, lang=lang):
            insight_box(ins)

    section(T("profile_section_mix", lang=lang))
    if bw_b.empty:
        empty(T("profile_empty_weekly", lang=lang, batter=sel_batter))
    else:
        st.plotly_chart(chart_batter_trend(bw, sel_batter, lang=lang), use_container_width=True, key="profile_trend")

        section(T("profile_section_changes", lang=lang))
        if bd_b.empty:
            st.info(T("profile_info_fewweeks", lang=lang))
        else:
            st.plotly_chart(chart_batter_delta_bars(bd, sel_batter, lang=lang), use_container_width=True, key="profile_delta_bars")

        col_ht, col_tbl = st.columns([3, 2])
        with col_ht:
            section(T("profile_section_heatmap", lang=lang))
            st.plotly_chart(chart_batter_heatmap(bw, sel_batter, lang=lang), use_container_width=True, key="profile_heatmap")
        with col_tbl:
            section(T("profile_section_table", lang=lang))
            if not bd_b.empty:
                disp_cols = {
                    "week_label_short": T("col_week", lang=lang),
                    "fb_pct": "FB%", "bb_pct": "BB%", "os_pct": "OS%",
                    "d_fb": "ΔFB", "d_bb": "ΔBB", "d_os": "ΔOS",
                    "adj_score": "Adj.Score", "total": T("col_pitches", lang=lang),
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
                export_csv(bd_b, f"batter_delta_{sel_batter.replace(' ','_')}.csv", T("profile_dl_csv", lang=lang))

        section(T("profile_section_zone", lang=lang))
        st.caption(T("profile_zone_caption", lang=lang))
        zc1, zc2 = st.columns(2)
        with zc1:
            zmode = st.radio(T("profile_view_label", lang=lang),
                              [T("profile_zone_radio_delta", lang=lang), T("profile_zone_radio_level", lang=lang)],
                              horizontal=True, key="zone_mode")
        mode_key = "delta" if zmode == T("profile_zone_radio_delta", lang=lang) else "level"
        st.plotly_chart(chart_zone_diamond(bw, sel_batter, bd=bd, mode=mode_key, lang=lang),
                        use_container_width=True, key="profile_zone_diamond")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 – PLAYER REPORT (shareable)
# ══════════════════════════════════════════════════════════════════════════════
with tab_report:
    section(T("report_header", lang=lang))
    st.caption(T("report_caption", lang=lang))

    if bd.empty:
        empty()
    else:
        rc0a, rc0b = st.columns([2, 1])
        with rc0a:
            rep_batter = st.selectbox(T("report_select_batter", lang=lang), sorted(bd["batter_name"].unique()),
                                       key="report_batter")
        with rc0b:
            use_base = st.checkbox(
                T("report_use_baseline", lang=lang, n=BASELINE_WEEKS),
                value=False, key="report_use_base",
                help=T("report_use_baseline_help", lang=lang, n=BASELINE_WEEKS),
            )
        bd_rep = bd[bd["batter_name"] == rep_batter].sort_values("week_start")
        headline = latest_week_headline(bd_rep, use_baseline=use_base)

        if headline is None:
            empty(T("report_empty_headline", lang=lang))
        else:
            _headline_week_start = bd_rep.sort_values("week_start").iloc[-1]["week_start"]
            rank_info = batter_week_rank(bd_league, rep_batter, _headline_week_start, use_baseline=use_base)
            render_share_card(rep_batter, headline, rank_info=rank_info, lang=lang)
            if not headline.get("reliable", True):
                st.warning(T("report_low_sample_warning", lang=lang, n=MIN_RELIABLE_PITCHES))

            rc1, rc2 = st.columns([1, 1])
            with rc1:
                section(T("report_section_trend", lang=lang))
                st.plotly_chart(chart_batter_trend(bw, rep_batter, lang=lang), use_container_width=True, key="report_trend")
            with rc2:
                section(T("report_section_zone", lang=lang))
                st.plotly_chart(chart_zone_diamond(bw, rep_batter, bd=bd, mode="delta", lang=lang),
                                use_container_width=True, key="report_zone_diamond")

            section(T("report_section_outcome", lang=lang))
            st.caption(T("report_outcome_caption", lang=lang))
            st.plotly_chart(chart_outcome_trend(bd, rep_batter, lang=lang), use_container_width=True, key="report_outcome_trend")

            st.divider()
            section(T("report_section_movers", lang=lang))
            st.caption(T("report_movers_caption", lang=lang, n=MIN_RELIABLE_PITCHES))
            rel_toggle = st.checkbox(T("report_reliable_only", lang=lang), value=True, key="report_rel_toggle")
            lb = biggest_movers_leaderboard(bd, top_n=15, reliable_only=rel_toggle, use_baseline=use_base)
            st.plotly_chart(chart_biggest_movers(lb, lang=lang), use_container_width=True, key="report_biggest_movers")
            export_csv(lb, "biggest_movers_leaderboard.csv", T("report_dl_leaderboard", lang=lang))

            section(T("report_section_sustained", lang=lang))
            st.caption(T("report_sustained_caption", lang=lang))
            sust = sustained_movers_leaderboard(bd, top_n=12, min_streak=3)
            if sust.empty:
                st.info(T("report_sustained_empty", lang=lang))
            else:
                st.plotly_chart(chart_sustained_movers(sust, lang=lang), use_container_width=True, key="report_sustained_movers")
                export_csv(sust, "sustained_movers.csv", T("report_dl_sustained", lang=lang))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 – VELOCITY & KONTEKST (platoon/count)
# ══════════════════════════════════════════════════════════════════════════════
with tab_velo:
    section(T("velo_header", lang=lang))
    st.caption(T("velo_caption", lang=lang))

    if bd.empty:
        empty()
    else:
        avail_vc = sorted(bd["batter_name"].unique())
        sel_vc = st.selectbox(T("profile_select_batter", lang=lang), avail_vc, key="velo_ctx_batter")

        section(T("velo_section_speed", lang=lang))
        st.caption(T("velo_speed_caption", lang=lang))
        if velo.empty or velo[velo["batter_name"] == sel_vc].empty:
            empty(T("velo_empty", lang=lang, batter=sel_vc))
        else:
            st.plotly_chart(chart_velo_trend(velo, sel_vc, lang=lang), use_container_width=True, key="velo_trend_chart")
            velo_b = velo[velo["batter_name"] == sel_vc].dropna(subset=["d_velo"])
            if not velo_b.empty:
                big_velo = velo_b.loc[velo_b["d_velo"].abs().idxmax()]
                st.info(T("velo_biggest_change", lang=lang, pt=big_velo["pitch_type"], delta=big_velo["d_velo"],
                          week=big_velo["week_label_short"], n=int(big_velo["n"])))

        section(T("velo_section_platoon", lang=lang))
        st.plotly_chart(chart_platoon_context(bd, sel_vc, lang=lang), use_container_width=True, key="platoon_context_chart")
        st.caption(T("velo_platoon_caption", lang=lang))

        section(T("velo_section_twostrike", lang=lang))
        bd_vc = bd[bd["batter_name"] == sel_vc].sort_values("week_start")
        if "pct_two_strike" in bd_vc.columns and not bd_vc.empty:
            st.plotly_chart(
                themed(
                    go.Figure(go.Bar(
                        x=bd_vc["week_label_short"], y=bd_vc["pct_two_strike"],
                        marker_color="#bc8cff",
                        hovertemplate=T("axis_week", lang=lang) + ": %{x}<br>%: %{y:.1f}%<extra></extra>",
                    )),
                    height=240, title=T("chart_two_strike_title", lang=lang, batter=sel_vc),
                    xaxis_title=T("axis_week", lang=lang), yaxis_title="%",
                ),
                use_container_width=True,
                key="two_strike_chart",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 – PORÓWNANIE
# ══════════════════════════════════════════════════════════════════════════════
with tab_compare:
    section(T("compare_header", lang=lang))
    st.caption(T("compare_caption", lang=lang))

    if bw.empty:
        empty()
    else:
        avail_cmp = sorted(bw["batter_name"].unique())
        c1, c2 = st.columns([3, 1])
        with c1:
            cmp_batters = st.multiselect(
                T("compare_select_batters", lang=lang), avail_cmp,
                default=avail_cmp[:3] if len(avail_cmp) >= 3 else avail_cmp,
                max_selections=4, key="cmp_batters",
            )
        with c2:
            cmp_mode = st.radio(T("compare_mode_label", lang=lang),
                                [T("compare_mode_pitchtype", lang=lang), T("compare_mode_single", lang=lang)],
                                horizontal=False, key="cmp_mode")

        if not cmp_batters:
            empty(T("compare_empty", lang=lang))
        elif cmp_mode == T("compare_mode_single", lang=lang):
            sel_cat_cmp = st.selectbox(
                T("compare_category_label", lang=lang), CAT_COLS,
                format_func=lambda x: ALL_CATEGORIES[x]["label"],
                key="cmp_cat",
            )
            st.plotly_chart(chart_comparison(bw, cmp_batters, sel_cat_cmp, lang=lang), use_container_width=True, key="compare_single_cat")
        else:
            grid_cols = st.columns(len(PITCH_CAT_COLS))
            for ci, col_cat in enumerate(PITCH_CAT_COLS):
                with grid_cols[ci]:
                    st.plotly_chart(chart_comparison(bw, cmp_batters, col_cat, lang=lang), use_container_width=True, key=f"compare_grid_{col_cat}")

        section(T("compare_section_avgtable", lang=lang))
        if cmp_batters and not bw.empty:
            bw_cmp = bw[bw["batter_name"].isin(cmp_batters)]
            avg_tbl = bw_cmp.groupby("batter_name")[PITCH_CAT_COLS].mean().round(1).reset_index()
            avg_tbl.columns = [T("col_batter", lang=lang)] + [ALL_CATEGORIES[c]["short"] for c in PITCH_CAT_COLS]
            st.dataframe(
                avg_tbl.style.background_gradient(cmap="RdYlGn", subset=avg_tbl.columns[1:].tolist())
                       .format({c: "{:.1f}%" for c in avg_tbl.columns[1:]}),
                use_container_width=True,
            )
            export_csv(avg_tbl, "comparison_avg.csv", T("changes_dl_csv", lang=lang))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 – ZMIANY MATCHUP
# ══════════════════════════════════════════════════════════════════════════════
with tab_changes:
    section(T("changes_header", lang=lang))
    st.caption(T("changes_caption", lang=lang))

    if md.empty:
        empty()
    else:
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            pt_f = st.multiselect(T("changes_pitchtype_label", lang=lang), sorted(md["PT"].unique()),
                                  format_func=lambda x: f"{x} – {PITCH_TYPES.get(x, x)}", key="chg_pt")
        with c2:
            dir_opts = [T("changes_direction_both", lang=lang), T("changes_direction_up", lang=lang), T("changes_direction_down", lang=lang)]
            direction = st.radio(T("changes_direction_label", lang=lang), dir_opts, horizontal=True, key="chg_dir")
        with c3:
            top_n = st.slider(T("changes_topn_label", lang=lang), 10, 100, 25, 5, key="chg_n")

        tbl_md = md.copy()
        if pt_f: tbl_md = tbl_md[tbl_md["PT"].isin(pt_f)]
        if direction == dir_opts[1]: tbl_md = tbl_md[tbl_md["Δ pp"] > 0]
        elif direction == dir_opts[2]: tbl_md = tbl_md[tbl_md["Δ pp"] < 0]
        tbl_md = tbl_md.head(top_n)

        st.dataframe(
            tbl_md[["Pitcher","Batter","Week","Prev Week","Pitch Name","Now %","Prev %","Δ pp","Pitches"]]
            .style.background_gradient(subset=["Δ pp"], cmap="RdYlGn", vmin=-30, vmax=30)
            .format({"Now %": "{:.1f}%", "Prev %": "{:.1f}%", "Δ pp": "{:+.1f} pp"}),
            use_container_width=True, height=420,
        )
        col_dl, _ = st.columns([1, 4])
        with col_dl:
            export_csv(tbl_md, "biggest_changes.csv", T("changes_dl_csv", lang=lang))

        section(T("changes_section_top", lang=lang))
        st.plotly_chart(chart_biggest_changes(md, top_n=min(top_n, 25), lang=lang), use_container_width=True, key="changes_top_chart")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 – BATTER × WEEK MATCHUPS  (v6.3: batter-first, not pitcher-first)
# ══════════════════════════════════════════════════════════════════════════════
with tab_matchup:
    section(T("matchup_header_v2", lang=lang))
    st.caption(T("matchup_caption_v2", lang=lang))

    if mw.empty:
        empty(T("matchup_empty", lang=lang))
    else:
        avail_b = sorted(mw["batter_name"].unique())
        c1, c2 = st.columns(2)
        with c1:
            sel_b = st.selectbox(T("matchup_select_batter", lang=lang), avail_b, key="mq_b")
        with c2:
            weeks_for_b = (mw[mw["batter_name"] == sel_b][["week_start", "week_label_short"]]
                           .drop_duplicates().sort_values("week_start"))
            week_options = weeks_for_b["week_start"].tolist()
            week_labels = dict(zip(weeks_for_b["week_start"], weeks_for_b["week_label_short"]))
            sel_week = st.selectbox(T("matchup_select_week", lang=lang), week_options,
                                     format_func=lambda w: week_labels.get(w, str(w)), key="mq_week")

        bwk_tbl = batter_week_matchup_table(mw, sel_b, sel_week)

        if bwk_tbl.empty:
            empty(T("matchup_empty_week", lang=lang, batter=sel_b))
        else:
            total_pitches_wk = int(bwk_tbl["total"].sum())
            render_kpis([
                {"label": T("matchup_kpi_pitchers_faced", lang=lang), "value": str(len(bwk_tbl)),
                 "sub": T("matchup_kpi_pitchers_faced_sub", lang=lang), "highlight": True},
                {"label": T("col_pitches", lang=lang), "value": str(total_pitches_wk),
                 "sub": T("matchup_kpi_total_sub", lang=lang)},
            ])

            section(T("matchup_section_table", lang=lang))
            disp = bwk_tbl.rename(columns={
                "pitcher_name": T("matchup_col_pitcher", lang=lang),
                "total": T("matchup_col_pitches", lang=lang),
                "top_pitch_type": T("matchup_col_toppt", lang=lang),
                "fb_pct": "FB%", "bb_pct": "BB%", "os_pct": "OS%",
            })
            st.dataframe(
                disp.style.background_gradient(subset=["FB%", "BB%", "OS%"], cmap="RdYlGn")
                   .format({"FB%": "{:.1f}%", "BB%": "{:.1f}%", "OS%": "{:.1f}%"}),
                use_container_width=True,
            )
            export_csv(bwk_tbl, f"batter_week_{sel_b.replace(' ', '_')}.csv", T("changes_dl_csv", lang=lang))

            section(T("matchup_section_chart", lang=lang))
            wk_label_str = week_labels.get(sel_week, str(sel_week))
            fig_stack = go.Figure()
            for cat_col, label in [("fb_pct", "FB%"), ("bb_pct", "BB%"), ("os_pct", "OS%")]:
                fig_stack.add_trace(go.Bar(
                    x=bwk_tbl["pitcher_name"], y=bwk_tbl[cat_col], name=label,
                    marker_color=CAT_COLORS[cat_col],
                ))
            fig_stack = themed(
                fig_stack, height=360, barmode="stack",
                title=T("matchup_stack_chart_title", lang=lang, batter=sel_b, week=wk_label_str),
                xaxis_title=T("matchup_col_pitcher", lang=lang), yaxis_title=T("axis_share_pct", lang=lang),
            )
            st.plotly_chart(fig_stack, use_container_width=True, key="batter_week_stack_chart")

            with st.expander(T("matchup_expander_drilldown", lang=lang)):
                avail_p_wk = bwk_tbl["pitcher_name"].tolist()
                sel_p_drill = st.selectbox(T("matchup_select_pitcher_drill", lang=lang), avail_p_wk, key="mq_p_drill")

                mw_mb = mw[(mw["pitcher_name"] == sel_p_drill) & (mw["batter_name"] == sel_b)]
                md_mb = md[(md["Pitcher"] == sel_p_drill) & (md["Batter"] == sel_b)]

                if mw_mb.empty:
                    empty(T("matchup_empty_pair", lang=lang))
                else:
                    render_kpis([
                        {"label": T("matchup_kpi_weeks", lang=lang), "value": str(mw_mb["week_start"].nunique()),
                         "sub": T("matchup_kpi_weeks_sub", lang=lang)},
                        {"label": T("matchup_kpi_total", lang=lang), "value": str(int(mw_mb.groupby("week_start")["n"].sum().sum())),
                         "sub": T("matchup_kpi_total_sub", lang=lang)},
                        {"label": T("matchup_kpi_types", lang=lang), "value": str(mw_mb["pitch_type"].nunique()),
                         "sub": T("matchup_kpi_types_sub", lang=lang)},
                        {"label": T("matchup_kpi_maxdelta", lang=lang), "value": f"{md_mb['Abs Δ'].max():.1f}" if not md_mb.empty else "—",
                         "sub": T("matchup_kpi_maxdelta_sub", lang=lang), "highlight": True},
                    ])
                    st.plotly_chart(chart_matchup_line(mw, sel_p_drill, sel_b, lang=lang), use_container_width=True, key="matchup_line_chart")

                    c_ht, c_tbl = st.columns([3, 2])
                    with c_ht:
                        section(T("matchup_section_heatmap", lang=lang))
                        st.plotly_chart(chart_matchup_heatmap(mw, sel_p_drill, sel_b, lang=lang), use_container_width=True, key="matchup_heatmap_chart")
                    with c_tbl:
                        section(T("matchup_section_deltas", lang=lang))
                        if md_mb.empty:
                            st.info(T("matchup_info_fewweeks", lang=lang))
                        else:
                            show_md = md_mb[["Week", "Pitch Name", "Now %", "Prev %", "Δ pp", "Pitches"]].head(20)
                            st.dataframe(
                                show_md.style.background_gradient(subset=["Δ pp"], cmap="RdYlGn", vmin=-30, vmax=30)
                                       .format({"Now %": "{:.1f}%", "Prev %": "{:.1f}%", "Δ pp": "{:+.1f} pp"}),
                                use_container_width=True, height=280,
                            )
                            export_csv(md_mb, f"matchup_{sel_p_drill.split()[-1]}_{sel_b.split()[-1]}.csv", T("changes_dl_csv", lang=lang))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 – RANKINGI
# ══════════════════════════════════════════════════════════════════════════════
with tab_ranking:
    section(T("rank_header", lang=lang))
    st.caption(T("rank_caption", lang=lang))

    if bd.empty:
        empty()
    else:
        c1, c2 = st.columns([1, 3])
        with c1:
            top_n_rank = st.slider(T("changes_topn_label", lang=lang), 5, 30, 15, key="rank_n")
        with c2:
            st.plotly_chart(chart_adj_score_ranking(bd, top_n_rank, lang=lang), use_container_width=True, key="adj_score_ranking_chart")

        section(T("rank_section_movers", lang=lang))
        st.caption(T("rank_movers_caption", lang=lang, n=MIN_RELIABLE_PITCHES))
        rmc1, rmc2, rmc3 = st.columns([1, 1, 1])
        with rmc1:
            top_n_mov = st.slider(T("rank_topn_moves", lang=lang), 5, 40, 15, key="mov_n")
        with rmc2:
            rel_only_rank = st.checkbox(T("rank_reliable_only", lang=lang), value=True, key="rank_rel_toggle")
        with rmc3:
            base_mode_rank = st.checkbox(T("rank_baseline_toggle", lang=lang, n=BASELINE_WEEKS), value=False, key="rank_base_toggle")
        lb_rank = biggest_movers_leaderboard(bd, top_n=top_n_mov, reliable_only=rel_only_rank, use_baseline=base_mode_rank)
        st.plotly_chart(chart_biggest_movers(lb_rank, lang=lang), use_container_width=True, key="rank_biggest_movers")
        export_csv(lb_rank, "biggest_movers_ranking.csv", T("rank_dl_movers", lang=lang))

        section(T("rank_section_sustained", lang=lang))
        st.caption(T("rank_sustained_caption", lang=lang))
        sust_rank = sustained_movers_leaderboard(bd, top_n=15, min_streak=3)
        if sust_rank.empty:
            st.info(T("rank_sustained_empty", lang=lang))
        else:
            st.plotly_chart(chart_sustained_movers(sust_rank, lang=lang), use_container_width=True, key="rank_sustained_movers")
            export_csv(sust_rank, "sustained_movers_ranking.csv", T("changes_dl_csv", lang=lang))

        rank_tbl = (
            bd.groupby("batter_name")
              .agg(Max_Adj=("adj_score", "max"), Avg_Adj=("adj_score", "mean"),
                   N_Weeks=("adj_score", "count"), Avg_FB=("fb_pct", "mean"),
                   Avg_BB=("bb_pct", "mean"), Avg_OS=("os_pct", "mean"))
              .round(1).sort_values("Max_Adj", ascending=False).head(top_n_rank).reset_index()
        )
        rank_tbl.columns = [T("col_batter", lang=lang), T("rank_col_maxadj", lang=lang), T("rank_col_avgadj", lang=lang),
                             T("rank_col_weeks", lang=lang), T("rank_col_fb", lang=lang), T("rank_col_bb", lang=lang),
                             T("rank_col_os", lang=lang)]
        section(T("rank_section_table", lang=lang))
        st.dataframe(
            rank_tbl.style.background_gradient(subset=[T("rank_col_maxadj", lang=lang), T("rank_col_avgadj", lang=lang)], cmap="YlOrRd")
                    .format({c: "{:.1f}" for c in rank_tbl.columns if c not in (T("col_batter", lang=lang), T("rank_col_weeks", lang=lang))}),
            use_container_width=True,
        )
        export_csv(rank_tbl, "adj_score_ranking.csv", T("rank_dl_movers", lang=lang))

        section(T("rank_section_percategory", lang=lang))
        cat_cols_ui = st.columns(len(PITCH_CAT_COLS))
        for ci, col_cat in enumerate(PITCH_CAT_COLS):
            with cat_cols_ui[ci]:
                cat_label = ALL_CATEGORIES[col_cat]["short"]
                color = ALL_CATEGORIES[col_cat]["color"]
                d_col = "d_" + col_cat.replace("_pct", "")
                abs_col = "abs_" + d_col
                if abs_col not in bd.columns:
                    st.caption(T("cat_no_data", lang=lang, label=cat_label))
                    continue
                cat_rank = bd.groupby("batter_name")[abs_col].max().sort_values(ascending=False).head(10).reset_index()
                cat_rank.columns = [T("col_batter", lang=lang), f"Max |Δ| {cat_label}"]
                fig_cr = go.Figure(go.Bar(
                    y=cat_rank[T("col_batter", lang=lang)], x=cat_rank[f"Max |Δ| {cat_label}"], orientation="h",
                    marker_color=color, text=cat_rank[f"Max |Δ| {cat_label}"].round(1),
                    texttemplate="  %{text:.1f}", textposition="outside", cliponaxis=False,
                    textfont=dict(color="#c9d1d9", size=10),
                ))
                themed(fig_cr, height=320, title=T("chart_top_cat_title", lang=lang, label=cat_label),
                       xaxis_title="pp", yaxis_title="", margin=dict(l=10, r=60, t=40, b=10))
                fig_cr.update_yaxes(autorange="reversed")
                st.plotly_chart(fig_cr, use_container_width=True, key=f"cat_rank_chart_{col_cat}")

        section(T("rank_section_perzone", lang=lang))
        sel_zone_cat = st.selectbox(
            T("rank_select_zone", lang=lang), ZONE_CAT_COLS, format_func=lambda x: ALL_CATEGORIES[x]["label"], key="zone_rank_cat",
        )
        d_col_z = "d_" + sel_zone_cat.replace("_pct", "")
        abs_col_z = "abs_" + d_col_z
        if abs_col_z in bd.columns:
            zone_rank = bd.groupby("batter_name")[abs_col_z].max().sort_values(ascending=False).head(15).reset_index()
            zone_rank.columns = [T("col_batter", lang=lang), f"Max |Δ| {ALL_CATEGORIES[sel_zone_cat]['short']}"]
            fig_zr = go.Figure(go.Bar(
                y=zone_rank[T("col_batter", lang=lang)], x=zone_rank.iloc[:, 1], orientation="h",
                marker_color=ALL_CATEGORIES[sel_zone_cat]["color"],
                text=zone_rank.iloc[:, 1].round(1), texttemplate="  %{text:.1f}",
                textposition="outside", cliponaxis=False, textfont=dict(color="#c9d1d9", size=10),
            ))
            themed(fig_zr, height=400, title=T("chart_top15_zone_title", lang=lang, label=ALL_CATEGORIES[sel_zone_cat]['label']),
                   xaxis_title="pp", yaxis_title="")
            fig_zr.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_zr, use_container_width=True, key="zone_rank_chart")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 8 – TEAM VIEW & WEEKLY DIGEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_team:
    section(T("team_header", lang=lang))
    st.caption(T("team_caption", lang=lang))
    if bd.empty:
        empty()
    else:
        team_tbl = team_rollup_table(bd)
        st.plotly_chart(chart_team_rollup(team_tbl, lang=lang), use_container_width=True, key="team_rollup_chart")
        st.dataframe(
            team_tbl.rename(columns={
                "team": T("team_col_team", lang=lang), "avg_adj": T("team_col_avgadj", lang=lang),
                "max_adj": T("team_col_maxadj", lang=lang), "n_batter_weeks": T("team_col_n", lang=lang),
                "top_batter": T("team_col_topbatter", lang=lang), "top_mover_label": T("team_col_cat", lang=lang),
                "top_mover_delta": T("team_col_delta", lang=lang), "top_week": T("team_col_week", lang=lang),
            }).style.background_gradient(subset=[T("team_col_avgadj", lang=lang), T("team_col_maxadj", lang=lang)], cmap="YlOrRd")
              .format({T("team_col_avgadj", lang=lang): "{:.1f}", T("team_col_maxadj", lang=lang): "{:.1f}",
                       T("team_col_delta", lang=lang): "{:+.1f}"}),
            use_container_width=True,
        )
        export_csv(team_tbl, "team_rollup.csv", T("team_dl_csv", lang=lang))

    st.divider()
    section(T("digest_header", lang=lang))
    st.caption(T("digest_caption", lang=lang))
    if bd.empty:
        empty()
    else:
        digest_n = st.slider(T("digest_n_items", lang=lang), 3, 10, 5, key="digest_n")
        digest_text = generate_weekly_digest(bd, top_n=digest_n, lang=lang)
        render_digest_block(digest_text, lang=lang)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 9 – PERIOD COMPARISON  (v6.5: custom week range A vs B, whole league)
# ══════════════════════════════════════════════════════════════════════════════
with tab_period:
    section(T("period_header", lang=lang))
    st.caption(T("period_caption", lang=lang))

    # Whole league, independent of the sidebar's batter-name search filter — only
    # bounded by season selection, same as the rest of the app's "raw" data.
    if bw_all.empty:
        empty()
    else:
        weeks_tbl = bw_all[["week_start", "week_label_short"]].drop_duplicates().sort_values("week_start")
        week_starts = weeks_tbl["week_start"].tolist()
        week_opts = weeks_tbl["week_label_short"].tolist()

        if len(week_opts) < 2:
            empty()
        else:
            pc1, pc2 = st.columns(2)
            mid = max(1, len(week_opts) // 2)
            with pc1:
                st.markdown(T("period_1_label", lang=lang))
                p1_range = st.select_slider(
                    T("period_weeks_label", lang=lang), options=week_opts,
                    value=(week_opts[0], week_opts[min(mid - 1, len(week_opts) - 1)]),
                    key="period1_range",
                )
            with pc2:
                st.markdown(T("period_2_label", lang=lang))
                p2_default_start = week_opts[min(mid, len(week_opts) - 1)]
                p2_range = st.select_slider(
                    T("period_weeks_label", lang=lang), options=week_opts,
                    value=(p2_default_start, week_opts[-1]),
                    key="period2_range",
                )

            def _label_range_to_weeks(label_range):
                i1, i2 = week_opts.index(label_range[0]), week_opts.index(label_range[1])
                lo, hi = min(i1, i2), max(i1, i2)
                return week_starts[lo:hi + 1]

            weeks_p1 = _label_range_to_weeks(p1_range)
            weeks_p2 = _label_range_to_weeks(p2_range)

            min_pitches_period = st.slider(T("period_min_pitches", lang=lang), 5, 200, 30, key="period_min_pitches")

            comp = compute_period_comparison(raw_df, bw_all, weeks_p1, weeks_p2, min_pitches=min_pitches_period)

            if comp.empty:
                empty(T("period_empty", lang=lang))
            else:
                delta_specs = [("d_ops", "Δ OPS"), ("d_obp", "Δ OBP"), ("d_slg", "Δ SLG"),
                                ("d_velo", "Δ Velo (mph)")] + [
                    (f"d_{c.replace('_pct', '')}", f"Δ {ALL_CATEGORIES[c]['short']}") for c in CAT_COLS
                ]
                delta_cols = [c for c, _ in delta_specs]
                delta_labels = {c: lbl for c, lbl in delta_specs}

                sc1, sc2, sc3 = st.columns([2, 1, 1])
                with sc1:
                    sort_col = st.selectbox(T("period_sort_by", lang=lang), delta_cols,
                                             format_func=lambda c: delta_labels[c], key="period_sort_col",
                                             index=0)
                with sc2:
                    sort_dir = st.radio(T("period_sort_dir", lang=lang),
                                         [T("period_sort_desc", lang=lang), T("period_sort_asc", lang=lang)],
                                         key="period_sort_dir")
                with sc3:
                    st.metric(T("period_n_batters", lang=lang), len(comp))

                ascending = sort_dir == T("period_sort_asc", lang=lang)
                ops_abs_cols = ["ops_p1", "ops_p2"]
                shown_cols = ["batter_name", "team", "total_p1", "total_p2"] + ops_abs_cols + delta_cols
                sorted_tbl = comp.sort_values(sort_col, ascending=ascending)[shown_cols].reset_index(drop=True)

                ops_abs_labels = {"ops_p1": T("period_col_opsp1", lang=lang), "ops_p2": T("period_col_opsp2", lang=lang)}
                rename_map = {
                    "batter_name": T("period_col_batter", lang=lang), "team": T("period_col_team", lang=lang),
                    "total_p1": T("period_col_p1n", lang=lang), "total_p2": T("period_col_p2n", lang=lang),
                    **ops_abs_labels, **delta_labels,
                }
                disp = sorted_tbl.rename(columns=rename_map)
                ops_abs_disp_cols = [ops_abs_labels[c] for c in ops_abs_cols]
                delta_disp_cols = [delta_labels[c] for c in delta_cols]
                ops_delta_disp_cols = [delta_labels[c] for c in ("d_ops", "d_obp", "d_slg")]
                pct_delta_disp_cols = [c for c in delta_disp_cols if c not in ops_delta_disp_cols]

                fmt = {c: "{:+.1f}" for c in pct_delta_disp_cols}
                fmt.update({c: "{:+.3f}" for c in ops_delta_disp_cols})
                fmt.update({c: "{:.3f}" for c in ops_abs_disp_cols})

                st.dataframe(
                    disp.style
                       .background_gradient(subset=ops_delta_disp_cols, cmap="RdYlGn", vmin=-0.3, vmax=0.3)
                       .background_gradient(subset=pct_delta_disp_cols, cmap="RdYlGn", vmin=-20, vmax=20)
                       .format(fmt, na_rep="—"),
                    use_container_width=True, height=600,
                )
                export_csv(comp, "period_comparison_full.csv", T("period_dl_csv", lang=lang))


# ─────────────────────────────────────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown(f"""
<div style="text-align:center; color:#7d8590; font-size:.76rem; padding:8px 0">
    {T("footer_text", lang=lang)}
</div>
""", unsafe_allow_html=True)
