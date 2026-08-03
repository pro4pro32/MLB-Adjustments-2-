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
            font=dict(color="#e6edf3", size=13),
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

    def __init__(self, raw_df: pd.DataFrame) -> None:
        self._render(raw_df)

    def _render(self, raw_df: pd.DataFrame) -> None:
        with st.sidebar:
            st.markdown("### ⚾ Pitch Mix Analyzer")

            st.markdown("### 📅 Sezony")
            self.seasons: list[int] = st.multiselect(
                "Sezony", AVAILABLE_SEASONS, default=[2025, 2026],
                label_visibility="collapsed",
            )
            if not self.seasons:
                self.seasons = [2026]

            st.markdown("### 📆 Zakres dat")
            min_d = raw_df["game_date"].min().date()
            max_d = raw_df["game_date"].max().date()

            preset = st.radio(
                "Preset", ["Bieżący miesiąc", "Ostatnie 8 tyg.", "Pełny sezon", "Własny"],
                horizontal=False, label_visibility="collapsed",
                index=3,
            )
            import datetime
            today = max_d
            if preset == "Bieżący miesiąc":
                d_s = today.replace(day=1)
                d_e = today
            elif preset == "Ostatnie 8 tyg.":
                d_s = today - datetime.timedelta(weeks=8)
                d_e = today
            elif preset == "Pełny sezon":
                d_s = min_d
                d_e = max_d
            else:
                cols = st.columns(2)
                with cols[0]:
                    d_s = st.date_input("Od", value=min_d, min_value=min_d,
                                        max_value=max_d, label_visibility="visible")
                with cols[1]:
                    d_e = st.date_input("Do", value=max_d, min_value=min_d,
                                        max_value=max_d, label_visibility="visible")

            self.d_start = max(d_s, min_d)
            self.d_end   = min(d_e, max_d)
            if self.d_start > self.d_end:
                self.d_start, self.d_end = self.d_end, self.d_start

            st.markdown("### 🎯 Progi")
            self.min_pitches: int = st.slider(
                "Min. narzutów / tydzień",    5, 80, 15, 5)
            self.min_prev: int    = st.slider(
                "Min. narzutów poprz. tydz.", 5, 80, 10, 5)

            st.markdown("### 🔍 Filtruj graczy")
            all_pitchers = sorted(raw_df["pitcher_name"].dropna().unique())
            all_batters  = sorted(raw_df["batter_name"].dropna().unique())

            pitcher_q = st.text_input("Szukaj pitcher", placeholder="np. Cole…",
                                      label_visibility="collapsed")
            filt_p = [p for p in all_pitchers if pitcher_q.lower() in p.lower()] \
                     if pitcher_q else all_pitchers
            self.sel_pitchers: list[str] = st.multiselect(
                "Pitcher", filt_p, placeholder="Wszyscy",
                label_visibility="collapsed", key="sb_pitchers",
            )

            batter_q = st.text_input("Szukaj batter", placeholder="np. Alvarez…",
                                     label_visibility="collapsed")
            filt_b = [b for b in all_batters if batter_q.lower() in b.lower()] \
                     if batter_q else all_batters
            self.sel_batters: list[str] = st.multiselect(
                "Batter", filt_b, placeholder="Wszyscy",
                label_visibility="collapsed", key="sb_batters",
            )

            st.markdown("### 🎳 Pitch type")
            avail_pt = sorted(raw_df["pitch_type"].dropna().unique())
            self.sel_pt: list[str] = st.multiselect(
                "Pitch type", avail_pt,
                format_func=lambda x: f"{x} – {PITCH_TYPES.get(x, x)}",
                placeholder="Wszystkie", label_visibility="collapsed",
            )

            st.divider()
            st.caption("Demo: dane syntetyczne.\nPodmień na `data/pitch_mix_RRRR.parquet`.")


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


def empty(msg: str = "Brak danych dla wybranych filtrów.") -> None:
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

def chart_batter_trend(bw: pd.DataFrame, batter: str) -> go.Figure:
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

    return themed(
        fig, height=380,
        title=f"Tygodniowy mix (pitch type) rzucony do: {batter}",
        xaxis_title="Tydzień", yaxis_title="Udział (%)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0,
                    font=dict(size=11, color="#c9d1d9")),
    )


def chart_batter_delta_bars(bd: pd.DataFrame, batter: str) -> go.Figure:
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

    return themed(
        fig, height=300, barmode="group",
        title=f"Zmiany tydzień-do-tygodnia (pitch type) · {batter}",
        xaxis_title="Tydzień", yaxis_title="Δ (pp)",
        bargap=0.15, bargroupgap=0.05,
    )


def chart_batter_heatmap(bw: pd.DataFrame, batter: str) -> go.Figure:
    """Heatmapa tygodnie × FB%/BB%/OS%."""
    sub = bw[bw["batter_name"] == batter].sort_values("week_start")
    if sub.empty:
        return go.Figure()

    z_data    = sub[PITCH_CAT_COLS].T.values
    x_labels  = sub["week_label_short"].tolist()
    y_labels  = [ALL_CATEGORIES[c]["short"] for c in PITCH_CAT_COLS]
    text_data = np.round(z_data, 1)

    fig = go.Figure(go.Heatmap(
        z=z_data, x=x_labels, y=y_labels,
        colorscale=[[0.0, "#0d1117"], [0.2, "#1a2a1a"], [0.5, "#ff6b35"], [0.8, "#ffd166"], [1.0, "#ffffff"]],
        zmin=0, zmax=80,
        text=text_data, texttemplate="%{text:.1f}%",
        textfont=dict(size=11, family="JetBrains Mono"),
        hovertemplate="Kategoria: %{y}<br>Tydzień: %{x}<br>%: %{z:.1f}%<extra></extra>",
        showscale=True,
        colorbar=dict(title="%", tickfont=dict(color="#7d8590"), title_font=dict(color="#7d8590"),
                      thickness=12, len=0.8),
    ))
    themed_rot(fig, angle=-30, height=220,
               title=f"Heatmapa pitch mix · {batter}", xaxis_title="", yaxis_title="")
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
                        mode: str = "delta") -> go.Figure:
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
            title = f"Zmiana % rzutów per strefa (Δ pp) · {batter} · {wk_label}"
            zmin, zmax, colorscale = -25, 25, [
                [0, "#f85149"], [0.5, "#161b22"], [1, "#39d353"],
            ]

    if mode == "level":
        last = sub_bw.iloc[-1]
        values_by_zone = {z: last.get(f"zone{z}_pct", np.nan) for z in
                          [1,2,3,4,5,6,7,8,9,11,12,13,14]}
        wk_label = str(last["week_label"]).replace("\n", " ").replace("·", "").strip()
        title = f"% rzutów per strefa · {batter} · {wk_label}"
        zmin, zmax, colorscale = 0, 20, [
            [0, "#0d1117"], [0.4, "#1a3a5c"], [0.7, "#ff6b35"], [1, "#ffd166"],
        ]

    z, text = _zone_grid_values(values_by_zone)

    fig = go.Figure(go.Heatmap(
        z=z, text=text, texttemplate="%{text}",
        textfont=dict(size=13, family="JetBrains Mono", color="#e6edf3"),
        colorscale=colorscale, zmin=zmin, zmax=zmax,
        showscale=True,
        xgap=6, ygap=6,
        hoverongaps=False,
        colorbar=dict(thickness=12, title="pp" if mode == "delta" else "%",
                      tickfont=dict(color="#7d8590"), title_font=dict(color="#7d8590")),
    ))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, autorange="reversed")
    fig = themed(fig, height=380, title=title, margin=dict(l=10, r=10, t=48, b=10))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, autorange="reversed")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Adjustment Score ranking
# ─────────────────────────────────────────────────────────────────────────────

def chart_adj_score_ranking(bd: pd.DataFrame, top_n: int = 15) -> go.Figure:
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
        textfont=dict(color="#c9d1d9", size=11),
        hovertemplate="<b>%{y}</b><br>Adj. Score: %{x:.1f}<extra></extra>",
    ))
    return themed(fig, height=max(340, top_n * 30),
                  title="Ranking: Adjustment Score (śr. |Δ| po wszystkich 16 kategoriach)",
                  xaxis_title="Adjustment Score", yaxis_title="", margin=dict(r=80))


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Biggest Movers leaderboard (NOWE — "did you know" ranking)
# ─────────────────────────────────────────────────────────────────────────────

def chart_biggest_movers(lb: pd.DataFrame) -> go.Figure:
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
        textfont=dict(color="#c9d1d9", size=11),
        hovertemplate=(
            "<b>%{y}</b><br>Kategoria: %{customdata[0]}<br>"
            "Zmiana: <b>%{x:+.1f} pp</b><br>Pitchy: %{customdata[1]}<extra></extra>"
        ),
        customdata=bar[["top_mover_label", "total"]].values,
    ))
    return themed(fig, height=max(380, len(bar) * 34),
                  title="Największe pojedyncze zmiany — dowolna z 16 kategorii (pitch-type + strefy)",
                  xaxis_title="Δ (pp)", yaxis_title="", margin=dict(r=140))


# ─────────────────────────────────────────────────────────────────────────────
#  SHAREABLE PLAYER REPORT CARD (NOWE)
# ─────────────────────────────────────────────────────────────────────────────

def render_share_card(batter: str, headline: dict) -> None:
    """
    Renderuje 'shareable' kartę do wysłania graczowi/drużynie:
    'Did you know you were the hitter with the biggest change in X this week?'
    v6: dodaje outcome context (whiff%/BA), reliability i platoon confound note.
    """
    direction_word = "wzrost" if headline["delta"] > 0 else "spadek"
    sign = "+" if headline["delta"] > 0 else ""
    rel_note = "" if headline.get("reliable", True) else \
        '<br><span style="color:#e3b341">⚠️ Mała próba w tym tygodniu — traktuj ostrożnie.</span>'

    outcome_bits = []
    if "whiff_pct" in headline:
        outcome_bits.append(f"Whiff%: {headline['whiff_pct']:.1f}%")
    if "ba_proxy" in headline:
        outcome_bits.append(f"BA (proxy): {headline['ba_proxy']:.3f}")
    outcome_line = " &nbsp;·&nbsp; ".join(outcome_bits)

    confound_note = ""
    if headline.get("platoon_confound_flag"):
        confound_note = ('<br><span style="color:#e3b341">⚠️ Duża zmiana w % rzutów vs LHP w tym '
                         'tygodniu — część zmiany może wynikać z innego matchupu, nie z adjustmentu.</span>')

    html = f"""
    <div class="share-card">
        <div class="sc-eyebrow">⚾ Pitch Mix Report · {headline['week_label']}</div>
        <div class="sc-name">{batter}</div>
        <div class="sc-headline">
            Czy wiesz, że byłeś pałkarzem z największą zmianą podejścia pitcherów
            w tym tygodniu? Rzucono do Ciebie
            <b>{sign}{headline['delta']:.1f} pp {direction_word}</b> udziału
            <b>{headline['category_label']}</b> względem poprzedniego tygodnia.
            {rel_note}{confound_note}
        </div>
        <div class="sc-meta">
            Adjustment Score: {headline['adj_score']:.1f} &nbsp;·&nbsp;
            Pitchy w tygodniu: {headline['total']}
            {" &nbsp;·&nbsp; " + outcome_line if outcome_line else ""}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Comparison – dowolna kategoria (pitch-type LUB zone) dla 2-4 batters
# ─────────────────────────────────────────────────────────────────────────────

def chart_comparison(bw: pd.DataFrame, batters: list[str], cat_col: str) -> go.Figure:
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

    themed(fig, height=340, title=f"Porównanie: {full}",
           xaxis_title="Tydzień", yaxis_title=f"{label} (%)", hovermode="x unified")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Matchup line + heatmap (bez zmian — nadal per pitch type)
# ─────────────────────────────────────────────────────────────────────────────

def chart_matchup_line(mw: pd.DataFrame, pitcher: str, batter: str) -> go.Figure:
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

    themed(fig, height=360, title=f"{pitcher} → {batter}: pitch mix per tydzień",
           xaxis_title="Tydzień", yaxis_title="Udział (%)", hovermode="x unified")
    return fig


def chart_matchup_heatmap(mw: pd.DataFrame, pitcher: str, batter: str) -> go.Figure:
    sub = mw[(mw["pitcher_name"] == pitcher) & (mw["batter_name"] == batter)].sort_values("week_start")

    pivot = (sub.pivot_table(index="pitch_type", columns="week_label_short", values="pitch_pct", aggfunc="sum")
             .fillna(0))
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
    pivot.index = [f"{pt} – {PITCH_TYPES.get(pt, pt)}" for pt in pivot.index]

    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=list(pivot.columns), y=pivot.index.tolist(),
        colorscale=[[0, "#0d1117"], [0.25, "#1a3a5c"], [0.55, "#ff6b35"], [0.8, "#ffd166"], [1, "#fff"]],
        zmin=0, zmax=80, text=np.round(pivot.values, 1), texttemplate="%{text:.1f}%",
        textfont=dict(size=10, family="JetBrains Mono"),
        hovertemplate="Pitch: %{y}<br>Tydzień: %{x}<br>%: %{z:.1f}%<extra></extra>",
        showscale=True,
        colorbar=dict(thickness=10, title="%", tickfont=dict(color="#7d8590"), title_font=dict(color="#7d8590")),
    ))
    themed_rot(fig, angle=-30, height=max(240, len(pivot) * 48 + 80),
               title=f"Heatmapa: {pitcher} → {batter}", xaxis_title="", yaxis_title="")
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART: Biggest matchup changes (Tab Zmiany) — bez zmian
# ─────────────────────────────────────────────────────────────────────────────

def chart_biggest_changes(md: pd.DataFrame, top_n: int = 20) -> go.Figure:
    if md.empty:
        return go.Figure()
    bar = md.head(top_n).copy()
    bar["label"] = bar["Pitcher"] + " → " + bar["Batter"]
    bar["color"] = bar["Δ pp"].apply(lambda x: "#39d353" if x > 0 else "#f85149")

    fig = go.Figure(go.Bar(
        x=bar["Δ pp"], y=bar["label"], orientation="h", marker_color=bar["color"],
        text=bar.apply(lambda r: f"{r['Pitch Name']} {r['Δ pp']:+.1f}pp", axis=1),
        textposition="outside", cliponaxis=False, textfont=dict(color="#c9d1d9", size=10),
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
    return themed(fig, height=max(420, top_n * 27),
                  title=f"Top {top_n} zmian pitch mix (pitcher → batter)",
                  xaxis_title="Δ (pp)", yaxis_title="", margin=dict(r=160))


# ─────────────────────────────────────────────────────────────────────────────
#  v6 CHART: Outcome overlay — czy zmiana pitch-mix faktycznie zadziałała?
# ─────────────────────────────────────────────────────────────────────────────

def chart_outcome_trend(bd: pd.DataFrame, batter: str) -> go.Figure:
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

    fig = themed(fig, height=340,
                 title=f"Outcome overlay · {batter} — czy adjustment pitcherów zadziałał?",
                 xaxis_title="Tydzień", yaxis_title="% (whiff / BA×100)",
                 hovermode="x unified",
                 yaxis2=dict(overlaying="y", side="right", title="Adj. Score",
                             showgrid=False, tickfont=dict(color="#7d8590")))
    return fig


def chart_platoon_context(bd: pd.DataFrame, batter: str) -> go.Figure:
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
    fig = themed(fig, height=260,
                 title=f"Kontekst: % rzutów widzianych vs LHP · {batter} (czerwony = duża zmiana tydz./tydz.)",
                 xaxis_title="Tydzień", yaxis_title="% vs LHP")
    fig.update_yaxes(range=[0, 100])
    return fig


def chart_velo_trend(velo: pd.DataFrame, batter: str) -> go.Figure:
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
    return themed(fig, height=340,
                  title=f"Prędkość rzutów per pitch type · {batter}",
                  xaxis_title="Tydzień", yaxis_title="mph", hovermode="x unified")


def chart_team_rollup(team_df: pd.DataFrame) -> go.Figure:
    """Bar chart: average Adjustment Score per drużyna (batter's team)."""
    if team_df.empty:
        return go.Figure()
    d = team_df.sort_values("avg_adj")
    fig = go.Figure(go.Bar(
        x=d["avg_adj"], y=d["team"], orientation="h",
        marker_color="#ff6b35",
        text=d["avg_adj"].round(1), textposition="outside", cliponaxis=False,
        customdata=d[["top_batter", "top_mover_label", "top_mover_delta", "n_batter_weeks"]].values,
        hovertemplate=(
            "<b>%{y}</b><br>Śr. Adj. Score: %{x:.1f}<br>"
            "Top mover: %{customdata[0]} (%{customdata[1]} %{customdata[2]:+.1f}pp)<br>"
            "N batter-tygodni: %{customdata[3]}<extra></extra>"
        ),
    ))
    return themed(fig, height=max(300, len(d) * 45),
                  title="Team rollup — średni Adjustment Score per drużyna",
                  xaxis_title="Avg Adj. Score", yaxis_title="", margin=dict(r=80))


def chart_sustained_movers(df: pd.DataFrame) -> go.Figure:
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
        textposition="outside", cliponaxis=False, textfont=dict(color="#c9d1d9", size=10),
        hovertemplate="<b>%{y}</b><br>Streak: %{customdata} tygodni<br>Skumulowana zmiana: %{x:+.1f} pp<extra></extra>",
        customdata=d["streak_weeks"],
    ))
    return themed(fig, height=max(360, len(d) * 32),
                  title="Sustained Movers — trwałe (≥3 tyg.) trendy, nie pojedynczy skok",
                  xaxis_title="Skumulowana zmiana (pp)", yaxis_title="", margin=dict(r=140))


def render_digest_block(digest_text: str) -> None:
    """Wyświetla auto-wygenerowany weekly digest jako kopiowalny blok tekstu."""
    st.markdown(digest_text)
    st.download_button(
        "⬇ Pobierz digest (.md)", data=digest_text.encode("utf-8"),
        file_name="weekly_digest.md", mime="text/markdown",
    )

