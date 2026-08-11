"""
ui_components.py – reusable UI components: themed charts, KPIs, sidebar, export

v5 CHANGE: generalized for 16 tracked categories (3 pitch-type + 13 zone).
New: chart_zone_diamond (strike-zone shaped heatmap), chart_biggest_movers,
render_share_card (Player Report / shareable card).
"""
from __future__ import annotations

import io
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from i18n import T, get_lang
from config import (
    AXIS_STYLE, CAT_COLS, CAT_COLORS, CAT_LABELS,
    AVAILABLE_SEASONS, BATTERS, ALL_CATEGORIES, PITCH_CATEGORIES,
    PITCH_CAT_COLS, ZONE_CAT_COLS, ZONE_GRID_LAYOUT, ZONE_DESCRIPTIONS,
    PITCH_COLORS, PITCH_TYPES, PLOTLY_BASE, LEGEND_DEFAULT,
)


# ─────────────────────────────────────────────────────────────────────────────
#  PLOTLY THEME HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_BASE_DICT_KEYS = {"font", "margin", "hoverlabel"}


def _apply_theme(fig: go.Figure, layout_kw: dict, x_angle: int | None = None) -> go.Figure:
    base = dict(PLOTLY_BASE)

    caller_legend  = layout_kw.pop("legend", {})
    base["legend"] = {**LEGEND_DEFAULT, **caller_legend}

    for key in _BASE_DICT_KEYS:
        if key in layout_kw:
            base[key] = {**base.get(key, {}), **layout_kw.pop(key)}

    if "title" in layout_kw and isinstance(layout_kw["title"], str):
        layout_kw["title"] = dict(
            text=layout_kw["title"],
            font=dict(color="#f0f6fc", size=13),
            x=0, xanchor="left",
        )

    fig.update_layout(**base, **layout_kw)

    ax = {**AXIS_STYLE}
    if x_angle is not None:
        ax["tickangle"] = x_angle
    fig.update_xaxes(**ax)
    fig.update_yaxes(**AXIS_STYLE)
    return fig


def themed(fig: go.Figure, **layout_kw: Any) -> go.Figure:
    return _apply_theme(fig, layout_kw)


def themed_rot(fig: go.Figure, angle: int = -30, **layout_kw: Any) -> go.Figure:
    return _apply_theme(fig, layout_kw, x_angle=angle)


# ─────────────────────────────────────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

class SidebarFilters:
    """Renderuje sidebar i przechowuje wartości filtrów."""

    def __init__(self, raw_df: pd.DataFrame, lang: str | None = None,
                 seasons_override: list[int] | None = None) -> None:
        self._render(raw_df, lang, seasons_override)

    def _render(self, raw_df: pd.DataFrame, lang: str | None = None,
                seasons_override: list[int] | None = None) -> None:
        with st.sidebar:
            # v6.5 FIX: app.py already renders the app-name header AND a seasons picker
            # before load_data() (it has to — seasons must be known before data loads).
            # This class used to *also* render both, producing a visibly duplicated
            # sidebar (two headers, two season pickers, only one of which actually did
            # anything — its value got silently overwritten). Now: if the caller already
            # picked seasons, just use that value and skip re-rendering the widget.
            if seasons_override is not None:
                self.seasons: list[int] = seasons_override
            else:
                st.markdown(T("sidebar_app_name", lang=lang))
                st.markdown(T("sidebar_seasons_header", lang=lang))
                self.seasons = st.multiselect(
                    T("sidebar_seasons_label", lang=lang), AVAILABLE_SEASONS, default=[2025, 2026],
                    label_visibility="collapsed",
                )
                if not self.seasons:
                    self.seasons = [2026]

            st.markdown(T("sidebar_date_header", lang=lang))
            min_d = raw_df["game_date"].min().date()
            max_d = raw_df["game_date"].max().date()

            preset_options = [T("sidebar_preset_month", lang=lang), T("sidebar_preset_8wk", lang=lang),
                               T("sidebar_preset_season", lang=lang), T("sidebar_preset_custom", lang=lang)]
            preset = st.radio(
                "Preset", preset_options,
                horizontal=False, label_visibility="collapsed",
                index=3,
            )
            import datetime
            today = max_d
            if preset == preset_options[0]:
                d_s = today.replace(day=1)
                d_e = today
            elif preset == preset_options[1]:
                d_s = today - datetime.timedelta(weeks=8)
                d_e = today
            elif preset == preset_options[2]:
                d_s = min_d
                d_e = max_d
            else:
                cols = st.columns(2)
                with cols[0]:
                    d_s = st.date_input(T("sidebar_date_from", lang=lang), value=min_d, min_value=min_d,
                                        max_value=max_d, label_visibility="visible")
                with cols[1]:
                    d_e = st.date_input(T("sidebar_date_to", lang=lang), value=max_d, min_value=min_d,
                                        max_value=max_d, label_visibility="visible")

            self.d_start = max(d_s, min_d)
            self.d_end   = min(d_e, max_d)
            if self.d_start > self.d_end:
                self.d_start, self.d_end = self.d_end, self.d_start

            st.markdown(T("sidebar_thresholds_header", lang=lang))
            self.min_pitches: int = st.slider(
                T("sidebar_min_pitches", lang=lang), 5, 80, 15, 5)
            self.min_prev: int    = st.slider(
                T("sidebar_min_prev", lang=lang), 5, 80, 10, 5)

            st.markdown(T("sidebar_players_header", lang=lang))
            all_pitchers = sorted(raw_df["pitcher_name"].dropna().unique())
            all_batters  = sorted(raw_df["batter_name"].dropna().unique())

            pitcher_q = st.text_input(T("sidebar_search_pitcher", lang=lang), placeholder=T("sidebar_search_pitcher", lang=lang),
                                      label_visibility="collapsed")
            filt_p = [p for p in all_pitchers if pitcher_q.lower() in p.lower()] \
                     if pitcher_q else all_pitchers
            self.sel_pitchers: list[str] = st.multiselect(
                T("sidebar_pitcher_label", lang=lang), filt_p, placeholder=T("sidebar_all_pitchers", lang=lang),
                label_visibility="collapsed", key="sb_pitchers",
            )

            batter_q = st.text_input(T("sidebar_search_batter", lang=lang), placeholder=T("sidebar_search_batter", lang=lang),
                                     label_visibility="collapsed")
            filt_b = [b for b in all_batters if batter_q.lower() in b.lower()] \
                     if batter_q else all_batters
            self.sel_batters: list[str] = st.multiselect(
                T("sidebar_batter_label", lang=lang), filt_b, placeholder=T("sidebar_all_batters", lang=lang),
                label_visibility="collapsed", key="sb_batters",
            )

            st.markdown(T("sidebar_pitchtype_header", lang=lang))
            avail_pt = sorted(raw_df["pitch_type"].dropna().unique())
            self.sel_pt: list[str] = st.multiselect(
                T("sidebar_pitchtype_label", lang=lang), avail_pt,
                format_func=lambda x: f"{x} – {PITCH_TYPES.get(x, x)}",
                placeholder=T("sidebar_pitchtype_all", lang=lang), label_visibility="collapsed",
            )

            st.divider()
            st.caption(T("sidebar_footer_caption", lang=lang))


# ─────────────────────────────────────────────────────────────────────────────
#  KPI CARDS / MISC
# ─────────────────────────────────────────────────────────────────────────────

def render_kpis(cards: list[dict]) -> None:
    parts = []
    for c in cards:
        hl = " highlight" if c.get("highlight") else ""
        parts.append(
            f'<div class="kpi-card{hl}">'
            f'<div class="kpi-label">{c["label"]}</div>'
            f'<div class="kpi-value">{c["value"]}</div>'
            f'<div class="kpi-sub">{c.get("sub", "")}</div>'
            f'</div>'
        )
    st.markdown(f'<div class="kpi-row">{"".join(parts)}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="section-hdr">{title}</div>', unsafe_allow_html=True)


def empty(msg: str | None = None) -> None:
    msg = msg if msg is not None else T("empty_default")
    st.markdown(
        f'<div class="empty-state"><span class="icon">⚾</span>{msg}</div>',
        unsafe_allow_html=True,
    )


def insight_box(text: str) -> None:
    st.markdown(f'<div class="insight-box">{text}</div>', unsafe_allow_html=True)


def export_csv(df: pd.DataFrame, filename: str, label: str = "⬇ CSV") -> None:
    st.download_button(
        label=label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        use_container_width=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Pitch-type trend (FB%/BB%/OS%) — główny wykres profilu pałkarza
# ─────────────────────────────────────────────────────────────────────────────

def _thin_week_ticks(fig: go.Figure, x_labels: list, max_ticks: int = 15) -> go.Figure:
    """v6.5: with many weeks on a time-series x-axis, rotated tick labels still get
    visually dense/hard to scan even without literal pixel overlap. Thin to ~max_ticks
    evenly-spaced labels for readability, consistent with the heatmap fix."""
    n = len(x_labels)
    if n > max_ticks:
        step = max(1, -(-n // max_ticks))
        fig.update_xaxes(tickmode="array", tickvals=x_labels[::step])
    return fig


def chart_batter_trend(bw: pd.DataFrame, batter: str, lang: str | None = None) -> go.Figure:
    """Line chart: FB%/BB%/OS% per week dla jednego battera."""
    sub = bw[bw["batter_name"] == batter].sort_values("week_start")

    fig = go.Figure()
    for col in PITCH_CAT_COLS:
        label = ALL_CATEGORIES[col]["short"]
        full  = ALL_CATEGORIES[col]["label"]
        color = CAT_COLORS[col]

        fig.add_trace(go.Scatter(
            x=sub["week_label_short"],
            y=sub[col],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=2.5),
            marker=dict(size=7, color=color, line=dict(color="#0d1117", width=1.5)),
            customdata=sub[["week_label", "total"]].values,
            hovertemplate=(
                f"<b>{full}</b><br>Tydzień: %{{customdata[0]}}<br>"
                "<b>%{y:.1f}%</b> pitchy do battera<br>"
                "Łącznie pitchy: %{customdata[1]}<extra></extra>"
            ),
        ))

    fig = themed_rot(
        fig, angle=-30, height=380,
        title=T("chart_trend_title", lang=lang, batter=batter),
        xaxis_title=T("axis_week", lang=lang), yaxis_title=T("axis_share_pct", lang=lang),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0,
                    font=dict(size=11, color="#f0f6fc")),
    )
    return _thin_week_ticks(fig, sub["week_label_short"].tolist())


def chart_batter_delta_bars(bd: pd.DataFrame, batter: str, lang: str | None = None) -> go.Figure:
    """Grouped bar chart: zmiana FB%/BB%/OS% tydzień do tygodnia."""
    sub = bd[bd["batter_name"] == batter].sort_values("week_start")
    if sub.empty:
        return go.Figure()

    fig = go.Figure()
    for col in PITCH_CAT_COLS:
        d_col = "d_" + col.replace("_pct", "")
        if d_col not in sub.columns:
            continue
        lbl, color = ALL_CATEGORIES[col]["short"], CAT_COLORS[col]
        fig.add_trace(go.Bar(
            name=lbl, x=sub["week_label_short"], y=sub[d_col],
            marker_color=color, opacity=0.85,
            hovertemplate=f"<b>{lbl} Δ</b><br>Tydzień: %{{x}}<br>Zmiana: <b>%{{y:+.1f}} pp</b><extra></extra>",
        ))

    fig = themed_rot(
        fig, angle=-30, height=300, barmode="group",
        title=T("chart_delta_title", lang=lang, batter=batter),
        xaxis_title=T("axis_week", lang=lang), yaxis_title=T("axis_delta_pp", lang=lang),
        bargap=0.15, bargroupgap=0.05,
    )
    return _thin_week_ticks(fig, sub["week_label_short"].tolist())


def chart_batter_heatmap(bw: pd.DataFrame, batter: str, lang: str | None = None) -> go.Figure:
    """Heatmapa tygodnie × FB%/BB%/OS%."""
    sub = bw[bw["batter_name"] == batter].sort_values("week_start")
    if sub.empty:
        return go.Figure()

    z_data    = sub[PITCH_CAT_COLS].T.values
    x_labels  = sub["week_label_short"].tolist()
    y_labels  = [ALL_CATEGORIES[c]["short"] for c in PITCH_CAT_COLS]
    text_data = np.round(z_data, 1)
    n_weeks   = len(x_labels)

    # v6.5 FIX: with many weeks selected (e.g. a full 1-2 season date range), forcing a
    # "42.6%" text label into every cell makes them all smear into an unreadable block.
    # Past a threshold, drop the per-cell text (color + hover tooltip still convey the
    # value) and thin out x-axis tick labels so they don't crowd together either.
    show_text = n_weeks <= 20
    heatmap_kwargs = dict(
        z=z_data, x=x_labels, y=y_labels,
        colorscale=[[0.0, "#161b22"], [0.25, "#7a3a1a"], [0.55, "#ff6b35"], [0.8, "#ffd166"], [1.0, "#ffb703"]],
        zmin=0, zmax=80,
        hovertemplate="Kategoria: %{y}<br>Tydzień: %{x}<br>%: %{z:.1f}%<extra></extra>",
        showscale=True,
        colorbar=dict(title="%", tickfont=dict(color="#c9d1d9"), title_font=dict(color="#f0f6fc"),
                      thickness=12, len=0.8),
    )
    if show_text:
        heatmap_kwargs.update(text=text_data, texttemplate="%{text:.1f}%",
                               textfont=dict(size=11, family="JetBrains Mono", color="#0d1117"))

    fig = go.Figure(go.Heatmap(**heatmap_kwargs))
    themed_rot(fig, angle=-35, height=220,
               title=T("chart_heatmap_title", lang=lang, batter=batter), xaxis_title="", yaxis_title="")
    if n_weeks > 20:
        # thin ticks to ~15 evenly-spaced labels instead of cramming every week in
        # (ceil division so step actually reduces the count, not floor division which
        # can round down to a no-op step of 1 for moderate week counts)
        step = max(1, -(-n_weeks // 15))
        fig.update_xaxes(tickmode="array", tickvals=x_labels[::step])
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Zone diamond — strefa Statcast w kształcie "diamentu" (NOWE)
# ─────────────────────────────────────────────────────────────────────────────

def _zone_grid_values(values_by_zone: dict[int, float]) -> tuple[np.ndarray, list[list[str]]]:
    """Konwertuje dict {zone: value} na macierz 5x3 wg ZONE_GRID_LAYOUT (NaN = puste pole)."""
    n_rows, n_cols = len(ZONE_GRID_LAYOUT), len(ZONE_GRID_LAYOUT[0])
    z = np.full((n_rows, n_cols), np.nan)
    text = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    for r, row in enumerate(ZONE_GRID_LAYOUT):
        for c, zone in enumerate(row):
            if zone is None:
                continue
            v = values_by_zone.get(zone, np.nan)
            z[r, c] = v
            text[r][c] = f"Z{zone}<br>{v:+.1f}" if not np.isnan(v) else f"Z{zone}"
    return z, text


def chart_zone_diamond(bw: pd.DataFrame, batter: str, bd: Optional[pd.DataFrame] = None,
                        mode: str = "delta", lang: str | None = None) -> go.Figure:
    """
    Rysuje strefy Statcast w kształcie diamentu:
        11      12
        1  2  3
        4  5  6
        7  8  9
       13      14

    mode="delta": pokazuje zmianę % (pp) między ostatnim a poprzednim tygodniem (wymaga bd).
    mode="level": pokazuje % w ostatnim dostępnym tygodniu.
    """
    sub_bw = bw[bw["batter_name"] == batter].sort_values("week_start")
    if sub_bw.empty:
        return go.Figure()

    if mode == "delta" and bd is not None:
        sub_bd = bd[bd["batter_name"] == batter].sort_values("week_start")
        if sub_bd.empty:
            mode = "level"
        else:
            last = sub_bd.iloc[-1]
            values_by_zone = {z: last.get(f"d_zone{z}", np.nan) for z in
                              [1,2,3,4,5,6,7,8,9,11,12,13,14]}
            wk_label = str(last["week_label"]).replace("\n", " ").replace("·", "").strip()
            title = T("chart_zone_delta_title", lang=lang, batter=batter, week=wk_label)
            zmin, zmax, colorscale = -25, 25, [
                [0, "#c0392b"], [0.5, "#161b22"], [1, "#1f8b3a"],
            ]

    if mode == "level":
        last = sub_bw.iloc[-1]
        values_by_zone = {z: last.get(f"zone{z}_pct", np.nan) for z in
                          [1,2,3,4,5,6,7,8,9,11,12,13,14]}
        wk_label = str(last["week_label"]).replace("\n", " ").replace("·", "").strip()
        title = T("chart_zone_level_title", lang=lang, batter=batter, week=wk_label)
        zmin, zmax, colorscale = 0, 20, [
            [0, "#161b22"], [0.4, "#1a3a5c"], [0.7, "#ff6b35"], [1, "#ffb703"],
        ]

    z, text = _zone_grid_values(values_by_zone)

    fig = go.Figure(go.Heatmap(
        z=z, text=text, texttemplate="%{text}",
        textfont=dict(size=13, family="JetBrains Mono", color="#f0f6fc"),
        colorscale=colorscale, zmin=zmin, zmax=zmax,
        showscale=True,
        xgap=8, ygap=8,
        hoverongaps=False,
        colorbar=dict(thickness=12, title="pp" if mode == "delta" else "%",
                      tickfont=dict(color="#c9d1d9"), title_font=dict(color="#f0f6fc")),
    ))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, autorange="reversed")
    fig = themed(fig, height=380, title=title, margin=dict(l=16, r=16, t=56, b=16))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, autorange="reversed")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Adjustment Score ranking
# ─────────────────────────────────────────────────────────────────────────────

def chart_adj_score_ranking(bd: pd.DataFrame, top_n: int = 15, lang: str | None = None) -> go.Figure:
    rank = (
        bd.groupby("batter_name")["adj_score"]
          .max().sort_values(ascending=True).tail(top_n).reset_index()
    )
    q75, q50 = rank["adj_score"].quantile(0.75), rank["adj_score"].quantile(0.50)
    colors = ["#ff6b35" if v >= q75 else "#ffd166" if v >= q50 else "#4cc9f0"
              for v in rank["adj_score"]]
    fig = go.Figure(go.Bar(
        x=rank["adj_score"], y=rank["batter_name"], orientation="h",
        marker_color=colors, text=rank["adj_score"].round(1),
        texttemplate="  %{text:.1f}", textposition="outside", cliponaxis=False,
        textfont=dict(color="#f0f6fc", size=11),
        hovertemplate="<b>%{y}</b><br>Adj. Score: %{x:.1f}<extra></extra>",
    ))
    fig = themed(fig, height=max(340, top_n * 30),
                  title=T("chart_adjrank_title", lang=lang),
                  xaxis_title="Adjustment Score", yaxis_title="", margin=dict(r=110, l=20, t=64, b=40))
    return _pad_bar_xaxis(fig, rank["adj_score"].tolist(), pad=1.3, positive_only=True)


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Biggest Movers leaderboard (NOWE — "did you know" ranking)
# ─────────────────────────────────────────────────────────────────────────────

def _pad_bar_xaxis(fig: go.Figure, values, pad: float = 1.45, positive_only: bool = False) -> go.Figure:
    """
    v6.5 FIX: Plotly's textposition='outside' places bar-tip text just past the bar's
    end — but when a bar's magnitude approaches the x-axis extreme, that text has
    nowhere left to go and visually collides with the y-axis category label sitting
    right there. Padding the axis range beyond the data's min/max gives the outside
    text room to breathe so it never overlaps the row label next to it.
    """
    vals = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not vals:
        return fig
    if positive_only:
        hi = max(vals) if vals else 0
        fig.update_xaxes(range=[0, max(hi * pad, 1)])
    else:
        hi = max(abs(min(vals)), abs(max(vals)), 1e-9)
        fig.update_xaxes(range=[-hi * pad, hi * pad])
    return fig


def chart_biggest_movers(lb: pd.DataFrame, lang: str | None = None) -> go.Figure:
    """
    Leaderboard: dla każdego battera×tygodnia jego NAJWIĘKSZA pojedyncza zmiana
    (dowolna z 16 kategorii — pitch-type lub zone). To jest sedno funkcji
    'kto miał największą zmianę podejścia pitcherów w danym tygodniu'.
    """
    if lb.empty:
        return go.Figure()

    bar = lb.copy()
    bar["label"] = bar["batter_name"] + " · " + bar["week_label_short"].astype(str)
    bar["color"] = bar["top_mover_delta"].apply(lambda x: "#39d353" if x > 0 else "#f85149")
    bar = bar.sort_values("top_mover_abs")

    fig = go.Figure(go.Bar(
        x=bar["top_mover_delta"], y=bar["label"], orientation="h",
        marker_color=bar["color"],
        text=bar.apply(lambda r: f"{r['top_mover_label']} {r['top_mover_delta']:+.1f}pp", axis=1),
        textposition="outside", cliponaxis=False,
        textfont=dict(color="#f0f6fc", size=11),
        hovertemplate=(
            "<b>%{y}</b><br>Kategoria: %{customdata[0]}<br>"
            "Zmiana: <b>%{x:+.1f} pp</b><br>Pitchy: %{customdata[1]}<extra></extra>"
        ),
        customdata=bar[["top_mover_label", "total"]].values,
    ))
    fig = themed(fig, height=max(380, len(bar) * 34),
                  title=T("chart_movers_title", lang=lang),
                  xaxis_title=T("axis_delta_pp", lang=lang), yaxis_title="", margin=dict(r=180, l=20, t=64, b=40))
    return _pad_bar_xaxis(fig, bar["top_mover_delta"].tolist(), pad=1.5)




# ─────────────────────────────────────────────────────────────────────────────
#  SHAREABLE PLAYER REPORT CARD (NOWE)
# ─────────────────────────────────────────────────────────────────────────────

def render_share_card(batter: str, headline: dict, rank_info: dict | None = None, lang: str | None = None) -> None:
    """
    Renderuje 'shareable' kartę do wysłania graczowi/drużynie.
    v6.3 FIX: headline text was previously always claiming "you had THE biggest
    change in the league" regardless of whether that was true — it only ever
    showed the SELECTED player's own biggest category change, not a league
    comparison. Now it only uses the superlative framing when `rank_info`
    confirms this player is actually #1 league-wide that week; otherwise it
    states the fact plus their honest rank (or a neutral framing if rank is
    unknown, e.g. too few reliable data points to rank).
    """
    direction_word = T("share_direction_up", lang=lang) if headline["delta"] > 0 else T("share_direction_down", lang=lang)
    sign = "+" if headline["delta"] > 0 else ""
    rel_note = "" if headline.get("reliable", True) else T("share_low_sample", lang=lang)

    if rank_info and rank_info.get("is_top"):
        headline_html = T("share_headline", lang=lang, sign=sign, delta=headline["delta"],
                           direction=direction_word, category=headline["category_label"])
    elif rank_info:
        headline_html = T("share_headline_ranked", lang=lang, sign=sign, delta=headline["delta"],
                           direction=direction_word, category=headline["category_label"],
                           rank=rank_info["rank"], total=rank_info["total"])
    else:
        headline_html = T("share_headline_neutral", lang=lang, sign=sign, delta=headline["delta"],
                           direction=direction_word, category=headline["category_label"])

    outcome_bits = []
    if "whiff_pct" in headline:
        outcome_bits.append(T("share_whiff_label", lang=lang, v=headline["whiff_pct"]))
    if "ba_proxy" in headline:
        outcome_bits.append(T("share_ba_label", lang=lang, v=headline["ba_proxy"]))
    outcome_line = " &nbsp;·&nbsp; ".join(outcome_bits)

    confound_note = T("share_confound", lang=lang) if headline.get("platoon_confound_flag") else ""

    eyebrow  = T("share_eyebrow", lang=lang, week=headline["week_label"])
    meta = T("share_meta", lang=lang, adj=headline["adj_score"], total=headline["total"])

    html = f"""
    <div class="share-card">
        <div class="sc-eyebrow">{eyebrow}</div>
        <div class="sc-name">{batter}</div>
        <div class="sc-headline">
            {headline_html}
            {rel_note}{confound_note}
        </div>
        <div class="sc-meta">
            {meta}
            {" &nbsp;·&nbsp; " + outcome_line if outcome_line else ""}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Comparison – dowolna kategoria (pitch-type LUB zone) dla 2-4 batters
# ─────────────────────────────────────────────────────────────────────────────

def chart_comparison(bw: pd.DataFrame, batters: list[str], cat_col: str, lang: str | None = None) -> go.Figure:
    label = ALL_CATEGORIES[cat_col]["short"]
    full  = ALL_CATEGORIES[cat_col]["label"]
    colors_comp = ["#ff6b35", "#4cc9f0", "#39d353", "#bc8cff"]

    fig = go.Figure()
    for i, b in enumerate(batters):
        sub = bw[bw["batter_name"] == b].sort_values("week_start")
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["week_label_short"], y=sub[cat_col], mode="lines+markers", name=b,
            line=dict(color=colors_comp[i % len(colors_comp)], width=2.5),
            marker=dict(size=7),
            hovertemplate=f"<b>{b}</b><br>Tydzień: %{{x}}<br>{label}: %{{y:.1f}}%<extra></extra>",
        ))

    themed_rot(fig, angle=-30, height=340, title=T("chart_compare_title", lang=lang, full=full),
           xaxis_title=T("axis_week", lang=lang), yaxis_title=f"{label} (%)", hovermode="x unified")
    all_weeks = (bw[bw["batter_name"].isin(batters)][["week_start", "week_label_short"]]
                 .drop_duplicates().sort_values("week_start")["week_label_short"].tolist())
    return _thin_week_ticks(fig, all_weeks)


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Matchup line + heatmap (bez zmian — nadal per pitch type)
# ─────────────────────────────────────────────────────────────────────────────

def chart_matchup_line(mw: pd.DataFrame, pitcher: str, batter: str, lang: str | None = None) -> go.Figure:
    sub = mw[(mw["pitcher_name"] == pitcher) & (mw["batter_name"] == batter)].sort_values("week_start")

    fig = go.Figure()
    for pt in sorted(sub["pitch_type"].unique()):
        ptd = sub[sub["pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=ptd["week_label_short"], y=ptd["pitch_pct"], mode="lines+markers",
            name=f"{pt} – {PITCH_TYPES.get(pt, pt)}",
            line=dict(color=PITCH_COLORS.get(pt, "#aaa"), width=2.5), marker=dict(size=7),
            customdata=ptd[["week_label", "pitch_pct", "total"]].values,
            hovertemplate=(f"<b>{pt}</b><br>Tydzień: %{{customdata[0]}}<br>"
                          "%: %{y:.1f}%<br>Total pitchy: %{customdata[2]}<extra></extra>"),
        ))

    themed_rot(fig, angle=-30, height=360, title=T("chart_matchup_line_title", lang=lang, pitcher=pitcher, batter=batter),
           xaxis_title=T("axis_week", lang=lang), yaxis_title=T("axis_share_pct", lang=lang), hovermode="x unified")
    return _thin_week_ticks(fig, sub["week_label_short"].drop_duplicates().tolist())


def chart_matchup_heatmap(mw: pd.DataFrame, pitcher: str, batter: str, lang: str | None = None) -> go.Figure:
    sub = mw[(mw["pitcher_name"] == pitcher) & (mw["batter_name"] == batter)].sort_values("week_start")

    pivot = (sub.pivot_table(index="pitch_type", columns="week_label_short", values="pitch_pct", aggfunc="sum")
             .fillna(0))
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
    pivot.index = [f"{pt} – {PITCH_TYPES.get(pt, pt)}" for pt in pivot.index]
    n_weeks_mh = len(pivot.columns)

    mh_kwargs = dict(
        z=pivot.values, x=list(pivot.columns), y=pivot.index.tolist(),
        colorscale=[[0, "#161b22"], [0.25, "#1a3a5c"], [0.55, "#ff6b35"], [0.8, "#ffd166"], [1, "#ffb703"]],
        zmin=0, zmax=80,
        hovertemplate="Pitch: %{y}<br>Tydzień: %{x}<br>%: %{z:.1f}%<extra></extra>",
        showscale=True,
        colorbar=dict(thickness=10, title="%", tickfont=dict(color="#c9d1d9"), title_font=dict(color="#f0f6fc")),
    )
    if n_weeks_mh <= 20:
        mh_kwargs.update(text=np.round(pivot.values, 1), texttemplate="%{text:.1f}%",
                          textfont=dict(size=10, family="JetBrains Mono", color="#0d1117"))
    fig = go.Figure(go.Heatmap(**mh_kwargs))
    themed_rot(fig, angle=-35, height=max(240, len(pivot) * 48 + 80),
               title=T("chart_matchup_heatmap_title", lang=lang, pitcher=pitcher, batter=batter), xaxis_title="", yaxis_title="")
    if n_weeks_mh > 20:
        step = max(1, -(-n_weeks_mh // 15))
        fig.update_xaxes(tickmode="array", tickvals=list(pivot.columns)[::step])
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Biggest matchup changes (Tab Zmiany) — bez zmian
# ─────────────────────────────────────────────────────────────────────────────

def chart_biggest_changes(md: pd.DataFrame, top_n: int = 20, lang: str | None = None) -> go.Figure:
    if md.empty:
        return go.Figure()
    bar = md.head(top_n).copy()
    bar["label"] = bar["Pitcher"] + " → " + bar["Batter"]
    bar["color"] = bar["Δ pp"].apply(lambda x: "#39d353" if x > 0 else "#f85149")

    fig = go.Figure(go.Bar(
        x=bar["Δ pp"], y=bar["label"], orientation="h", marker_color=bar["color"],
        text=bar.apply(lambda r: f"{r['Pitch Name']} {r['Δ pp']:+.1f}pp", axis=1),
        textposition="outside", cliponaxis=False, textfont=dict(color="#f0f6fc", size=10),
        customdata=np.stack([
            bar["Pitch Name"], bar["Now %"], bar["Prev %"], bar["Pitches"],
            bar["Week"].str.split("\n").str[0],
        ], axis=-1),
        hovertemplate=(
            "<b>%{y}</b><br>Pitch: %{customdata[0]}<br>"
            "Teraz: %{customdata[1]:.1f}% · Poprzednio: %{customdata[2]:.1f}%<br>"
            "Δ: <b>%{x:+.1f} pp</b><br>Pitchy: %{customdata[3]} · Tydzień: %{customdata[4]}<extra></extra>"
        ),
    ))
    fig = themed(fig, height=max(420, top_n * 27),
                  title=T("chart_changes_title", lang=lang, n=top_n),
                  xaxis_title=T("axis_delta_pp", lang=lang), yaxis_title="", margin=dict(r=200, l=20, t=64, b=40))
    return _pad_bar_xaxis(fig, bar["Δ pp"].tolist(), pad=1.5)


# ─────────────────────────────────────────────────────────────────────────────
#  v6 CHART: Outcome overlay — czy zmiana pitch-mix faktycznie zadziałała?
# ─────────────────────────────────────────────────────────────────────────────

def chart_outcome_trend(bd: pd.DataFrame, batter: str, lang: str | None = None) -> go.Figure:
    """Whiff% i BA(proxy) w czasie + Adjustment Score jako tło (bar), żeby
    zobaczyć czy tygodnie z dużym adjustmentem pokrywają się ze zmianą wyników."""
    sub = bd[bd["batter_name"] == batter].sort_values("week_start")
    if sub.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=sub["week_label_short"], y=sub["adj_score"], name="Adj. Score",
        marker_color="rgba(255,107,53,0.25)", yaxis="y2",
        hovertemplate="Adj. Score: %{y:.1f}<extra></extra>",
    ))
    if "whiff_pct" in sub.columns:
        fig.add_trace(go.Scatter(
            x=sub["week_label_short"], y=sub["whiff_pct"], name="Whiff%",
            mode="lines+markers", line=dict(color="#f85149", width=2.5), marker=dict(size=7),
            hovertemplate="Whiff%%: %{y:.1f}%%<extra></extra>",
        ))
    if "ba_proxy" in sub.columns:
        fig.add_trace(go.Scatter(
            x=sub["week_label_short"], y=sub["ba_proxy"] * 100, name="BA (proxy, ×100)",
            mode="lines+markers", line=dict(color="#4cc9f0", width=2.5), marker=dict(size=7),
            hovertemplate="BA proxy: %{customdata:.3f}<extra></extra>",
            customdata=sub["ba_proxy"],
        ))

    fig = themed_rot(fig, angle=-30, height=340,
                 title=T("chart_outcome_title", lang=lang, batter=batter),
                 xaxis_title=T("axis_week", lang=lang), yaxis_title=T("axis_outcome_pct", lang=lang),
                 hovermode="x unified",
                 yaxis2=dict(overlaying="y", side="right", title="Adj. Score",
                             showgrid=False, tickfont=dict(color="#c9d1d9")))
    return _thin_week_ticks(fig, sub["week_label_short"].tolist())


def chart_platoon_context(bd: pd.DataFrame, batter: str, lang: str | None = None) -> go.Figure:
    """% rzutów widzianych vs LHP per tydzień — do wykrywania confoundów."""
    sub = bd[bd["batter_name"] == batter].sort_values("week_start")
    if sub.empty or "pct_vs_lhp" not in sub.columns:
        return go.Figure()

    colors = ["#f85149" if f else "#58a6ff" for f in sub.get("platoon_confound_flag", False)]
    fig = go.Figure(go.Bar(
        x=sub["week_label_short"], y=sub["pct_vs_lhp"], marker_color=colors,
        text=sub["pct_vs_lhp"].round(0).astype(int).astype(str) + "%",
        textposition="outside",
        hovertemplate="Tydzień: %{x}<br>%% rzutów vs LHP: %{y:.1f}%%<extra></extra>",
    ))
    fig = themed_rot(fig, angle=-30, height=260,
                 title=T("chart_platoon_title", lang=lang, batter=batter),
                 xaxis_title=T("axis_week", lang=lang), yaxis_title=T("axis_pct_vs_lhp", lang=lang))
    fig.update_yaxes(range=[0, 100])
    return _thin_week_ticks(fig, sub["week_label_short"].tolist())


def chart_velo_trend(velo: pd.DataFrame, batter: str, lang: str | None = None) -> go.Figure:
    """Średnia prędkość (mph) per pitch type, per tydzień — 'ten sam pitch, mocniej/słabiej'."""
    from config import PITCH_COLORS, PITCH_TYPES
    sub = velo[velo["batter_name"] == batter].sort_values("week_start")
    if sub.empty:
        return go.Figure()

    fig = go.Figure()
    for pt in sorted(sub["pitch_type"].unique()):
        ptd = sub[sub["pitch_type"] == pt]
        fig.add_trace(go.Scatter(
            x=ptd["week_label_short"], y=ptd["avg_velo"], mode="lines+markers",
            name=f"{pt} – {PITCH_TYPES.get(pt, pt)}",
            line=dict(color=PITCH_COLORS.get(pt, "#aaa"), width=2.3), marker=dict(size=6),
            customdata=ptd[["d_velo", "n"]].values,
            hovertemplate=(f"<b>{pt}</b><br>Tydzień: %{{x}}<br>Śr. prędkość: %{{y:.1f}} mph<br>"
                          "Δ vs poprz. tydz.: %{customdata[0]:+.1f} mph<br>N: %{customdata[1]}<extra></extra>"),
        ))
    fig = themed_rot(fig, angle=-30, height=340,
                  title=T("chart_velo_title", lang=lang, batter=batter),
                  xaxis_title=T("axis_week", lang=lang), yaxis_title=T("axis_mph", lang=lang), hovermode="x unified")
    return _thin_week_ticks(fig, sub["week_label_short"].drop_duplicates().tolist())


def chart_team_rollup(team_df: pd.DataFrame, lang: str | None = None) -> go.Figure:
    """Bar chart: average Adjustment Score per drużyna (batter's team)."""
    if team_df.empty:
        return go.Figure()
    d = team_df.sort_values("avg_adj")
    fig = go.Figure(go.Bar(
        x=d["avg_adj"], y=d["team"], orientation="h",
        marker_color="#ff6b35",
        text=d["avg_adj"].round(1), textposition="outside", cliponaxis=False,
        textfont=dict(color="#f0f6fc", size=11),
        customdata=d[["top_batter", "top_mover_label", "top_mover_delta", "n_batter_weeks"]].values,
        hovertemplate=(
            "<b>%{y}</b><br>Śr. Adj. Score: %{x:.1f}<br>"
            "Top mover: %{customdata[0]} (%{customdata[1]} %{customdata[2]:+.1f}pp)<br>"
            "N batter-tygodni: %{customdata[3]}<extra></extra>"
        ),
    ))
    fig = themed(fig, height=max(300, len(d) * 45),
                  title=T("chart_team_title", lang=lang),
                  xaxis_title=T("axis_avg_adj_score", lang=lang), yaxis_title="", margin=dict(r=110, l=20, t=64, b=40))
    return _pad_bar_xaxis(fig, d["avg_adj"].tolist(), pad=1.3, positive_only=True)


def chart_sustained_movers(df: pd.DataFrame, lang: str | None = None) -> go.Figure:
    """Ranking sustained trendów (streak_weeks × |cumulative_delta|) — bardziej
    wiarygodny sygnał niż pojedynczy tygodniowy skok."""
    if df.empty:
        return go.Figure()
    d = df.sort_values("score")
    d["label"] = d["batter_name"] + " · " + d["category"]
    colors = d["cumulative_delta"].apply(lambda x: "#39d353" if x > 0 else "#f85149")

    fig = go.Figure(go.Bar(
        x=d["cumulative_delta"], y=d["label"], orientation="h", marker_color=colors,
        text=d.apply(lambda r: f"{r['streak_weeks']} tyg. · {r['cumulative_delta']:+.1f}pp", axis=1),
        textposition="outside", cliponaxis=False, textfont=dict(color="#f0f6fc", size=10),
        hovertemplate="<b>%{y}</b><br>Streak: %{customdata} tygodni<br>Skumulowana zmiana: %{x:+.1f} pp<extra></extra>",
        customdata=d["streak_weeks"],
    ))
    fig = themed(fig, height=max(360, len(d) * 32),
                  title=T("chart_sustained_title", lang=lang),
                  xaxis_title=T("axis_cumulative_delta", lang=lang), yaxis_title="", margin=dict(r=190, l=20, t=64, b=40))
    return _pad_bar_xaxis(fig, d["cumulative_delta"].tolist(), pad=1.55)


def render_digest_block(digest_text: str, lang: str | None = None) -> None:
    """Wyświetla auto-wygenerowany weekly digest jako kopiowalny blok tekstu."""
    st.markdown(digest_text)
    st.download_button(
        T("digest_dl_button", lang=lang), data=digest_text.encode("utf-8"),
        file_name="weekly_digest.md", mime="text/markdown",
    )

