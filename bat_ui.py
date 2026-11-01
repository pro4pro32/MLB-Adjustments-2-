"""bat_ui.py — real Statcast bat-tracking view (season summaries) + data-files panel + demo banner."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from i18n import T
from ui_components import export_csv, render_kpis, section, show_table, themed

GROUPS = ["Fastball", "Breaking", "Offspeed"]
GRID = {(0, 0): 11, (0, 2): 12, (1, 0): 1, (1, 1): 2, (1, 2): 3, (2, 0): 4, (2, 1): 5, (2, 2): 6,
        (3, 0): 7, (3, 1): 8, (3, 2): 9, (4, 0): 13, (4, 2): 14}
KIND_KEYS = {"pitch": "data_kind_pitch", "pitch_raw": "data_kind_pitch_raw", "bat_players": "data_kind_bat_players",
             "bat_zone": "data_kind_bat_zone", "bat_pitchgroup": "data_kind_bat_pitchgroup",
             "unknown": "data_kind_unknown", "unreadable": "data_kind_unreadable"}
USED_KINDS = ("pitch", "pitch_raw", "bat_players", "bat_zone")


def render_data_panel(lang: str, files: list, data_source: str) -> None:
    with st.sidebar:
        with st.expander(T("data_panel_header", lang=lang), expanded=(data_source == "syntetyczne")):
            if not files:
                st.caption(T("data_panel_none", lang=lang))
            for f in files:
                icon = "✅" if f["kind"] in USED_KINDS else "⚪"
                st.markdown(f"{icon} `{f['name']}` — {T(KIND_KEYS.get(f['kind'], 'data_kind_unknown'), lang=lang)}")


def render_demo_banner(lang: str, files: list, data_source: str) -> None:
    if data_source != "syntetyczne":
        return
    msg = T("demo_banner", lang=lang)
    if files and not any(f["kind"] in ("pitch", "pitch_raw") for f in files):
        msg += "\n\n" + T("demo_banner_files", lang=lang, n=len(files))
    st.warning(msg)


def _wavg(df: pd.DataFrame, col: str, w: str = "swings") -> float:
    if col not in df.columns:
        return np.nan
    d = df[[col, w]].dropna()
    return float(np.average(d[col], weights=d[w])) if len(d) and d[w].sum() > 0 else np.nan


def zone_figure(vals: dict, title: str, fmt: str) -> go.Figure:
    z = np.full((5, 3), np.nan)
    for (r, c), zn in GRID.items():
        v = vals.get(zn)
        if v is not None and not pd.isna(v):
            z[r, c] = v
    finite = z[~np.isnan(z)]
    lo = float(finite.min()) if finite.size else 0.0
    hi = float(finite.max()) if finite.size else 1.0
    span = (hi - lo) if hi > lo else 1.0
    fig = go.Figure(go.Heatmap(z=z, colorscale=[[0, "#1a2a44"], [0.5, "#c2571a"], [1, "#ffb703"]], zmin=lo, zmax=hi,
                               xgap=3, ygap=3, hoverongaps=False,
                               colorbar=dict(thickness=12, tickfont=dict(color="#c9d1d9"))))
    for (r, c), zn in GRID.items():
        v = z[r, c]
        txt = f"Z{zn}<br>{fmt.format(v)}" if not np.isnan(v) else f"Z{zn}<br>—"
        norm = 0.0 if np.isnan(v) else (v - lo) / span
        fig.add_annotation(x=c, y=r, text=txt, showarrow=False,
                           font=dict(size=12, color="#0d1117" if norm > 0.62 else "#f0f6fc"))
    fig.update_yaxes(autorange="reversed", showticklabels=False, showgrid=False)
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return themed(fig, height=420, title=title)


def render_bat_tab(bat, lang: str) -> None:
    section(T("bat_header", lang=lang))
    st.caption(T("bat_caption", lang=lang))
    players = bat["players"] if bat else pd.DataFrame()
    zone = bat["zone"] if bat else pd.DataFrame()
    if players.empty and zone.empty:
        st.info(T("bat_none", lang=lang))
        return
    seasons = sorted(set(players["season"]) if not players.empty else set(zone["season"]))
    c1, c2, c3 = st.columns([1, 2, 1])
    season = c1.selectbox(T("bat_season", lang=lang), seasons, index=len(seasons) - 1, key="bat_season",
                          format_func=lambda s: str(s) if s else "?")
    p = players[players["season"] == season] if not players.empty else players
    z = zone[zone["season"] == season] if not zone.empty else zone
    names = sorted(set(p["batter_name"]) if not p.empty else set(z["batter_name"]))
    if st.session_state.get("bat_batter") not in names:
        st.session_state.pop("bat_batter", None)
    batter = c2.selectbox(T("bat_batter", lang=lang), names, index=names.index("Aaron Judge") if "Aaron Judge" in names else 0,
                          key="bat_batter")
    min_sw = c3.slider(T("bat_min_swings", lang=lang), 50, 800, 200, 25, key="bat_min_swings")

    # ── KPIs with league context ──
    row = p[p["batter_name"] == batter] if not p.empty else p
    if not row.empty:
        r = row.iloc[0]
        qual = p[p["total_swings"] >= min_sw]
        cards = [{"label": T("bat_kpi_swings", lang=lang), "value": f"{r['total_swings']:,.0f}",
                  "sub": T("bat_sub_median", lang=lang, m=f"{p['total_swings'].median():.0f}")}]
        for key, col, fmt, hl in [("bat_kpi_speed", "avg_bat_speed", "{:.1f}", False), ("bat_kpi_length", "avg_swing_length", "{:.2f}", False),
                                  ("bat_kpi_aa", "avg_attack_angle", "{:.1f}", False), ("bat_kpi_xwoba", "xwoba", "{:.3f}", True),
                                  ("bat_kpi_ev", "avg_exit_velocity", "{:.1f}", False), ("bat_kpi_la", "avg_launch_angle", "{:.1f}", False)]:
            if col not in r.index:
                continue
            v = r[col]
            sub = ""
            if not qual.empty and not pd.isna(v):
                sub = T("bat_sub_pct", lang=lang, p=float((qual[col] < v).mean() * 100))
            cards.append({"label": T(key, lang=lang), "value": "—" if pd.isna(v) else fmt.format(v), "sub": sub, "highlight": hl})
        render_kpis(cards)

    # ── by pitch group + zone map (from the zone file) ──
    zb = z[z["batter_name"] == batter] if not z.empty else z
    if not zb.empty:
        section(T("bat_grp_title", lang=lang))
        tot = zb["swings"].sum()
        rows = []
        for g in GROUPS:
            gg = zb[zb["pitch_group"] == g]
            if gg.empty:
                continue
            rows.append({T("bat_col_group", lang=lang): T(f"bat_grp_{g}", lang=lang), T("bat_kpi_swings", lang=lang): int(gg["swings"].sum()),
                         T("bat_col_share", lang=lang): gg["swings"].sum() / tot * 100,
                         T("bat_kpi_speed", lang=lang): _wavg(gg, "avg_bat_speed"), "xwOBA": _wavg(gg, "xwoba"),
                         T("bat_kpi_ev", lang=lang): _wavg(gg, "avg_exit_velocity"), T("bat_kpi_la", lang=lang): _wavg(gg, "avg_launch_angle")})
        tg = pd.DataFrame(rows)
        fm = {T("bat_col_share", lang=lang): "{:.1f}%", T("bat_kpi_speed", lang=lang): "{:.1f}", "xwOBA": "{:.3f}",
              T("bat_kpi_ev", lang=lang): "{:.1f}", T("bat_kpi_la", lang=lang): "{:.1f}"}
        show_table(tg.style.format(fm, na_rep="—"))

        section(T("bat_zone_title", lang=lang))
        z1, z2 = st.columns(2)
        grp = z1.radio(T("bat_zone_group", lang=lang), ["all"] + GROUPS, horizontal=True, key="bat_zone_group",
                       format_func=lambda g: T("bat_zone_all", lang=lang) if g == "all" else T(f"bat_grp_{g}", lang=lang))
        metrics = {"share": ("bat_m_share", None, "{:.1f}%"), "xwoba": ("bat_m_xwoba", "xwoba", "{:.3f}"),
                   "speed": ("bat_m_speed", "avg_bat_speed", "{:.1f}"), "ev": ("bat_m_ev", "avg_exit_velocity", "{:.1f}")}
        met = z2.radio(T("bat_zone_metric", lang=lang), list(metrics), horizontal=True, key="bat_zone_metric",
                       format_func=lambda m: T(metrics[m][0], lang=lang))
        gz = zb if grp == "all" else zb[zb["pitch_group"] == grp]
        tot_g = gz["swings"].sum()
        vals = {}
        for zn, gg in gz.groupby("zone"):
            if met == "share":
                vals[int(zn)] = gg["swings"].sum() / tot_g * 100 if tot_g else np.nan
            elif gg["swings"].sum() >= 5:
                vals[int(zn)] = _wavg(gg, metrics[met][1])
        st.plotly_chart(zone_figure(vals, f"{batter} · {T(metrics[met][0], lang=lang)}", metrics[met][2]),
                        use_container_width=True, key="bat_zone_fig")
        st.caption(T("bat_zone_note", lang=lang))

    # ── season to season ──
    if len(seasons) > 1 and not players.empty:
        ps = players[players["batter_name"] == batter].sort_values("season")
        if len(ps) > 1:
            section(T("bat_seasons_title", lang=lang))
            cols = {"season": "Season", "total_swings": T("bat_kpi_swings", lang=lang), "avg_bat_speed": T("bat_kpi_speed", lang=lang),
                    "avg_swing_length": T("bat_kpi_length", lang=lang), "avg_attack_angle": T("bat_kpi_aa", lang=lang),
                    "xwoba": "xwOBA", "avg_exit_velocity": T("bat_kpi_ev", lang=lang)}
            t = ps[[c for c in cols if c in ps.columns]].rename(columns=cols)
            show_table(t.style.format({k: "{:.3f}" if k == "xwOBA" else "{:.1f}" for k in t.columns if k not in ("Season", T("bat_kpi_swings", lang=lang))}, na_rep="—"))

    # ── league leaders + scatter ──
    if not p.empty:
        qual = p[p["total_swings"] >= min_sw]
        if len(qual) >= 5:
            section(T("bat_leader_title", lang=lang))
            L1, L2 = st.columns(2)
            cols = {"batter_name": T("bat_batter", lang=lang), "total_swings": T("bat_kpi_swings", lang=lang),
                    "avg_bat_speed": T("bat_kpi_speed", lang=lang), "xwoba": "xwOBA", "avg_exit_velocity": T("bat_kpi_ev", lang=lang)}
            fm = {T("bat_kpi_speed", lang=lang): "{:.1f}", "xwOBA": "{:.3f}", T("bat_kpi_ev", lang=lang): "{:.1f}"}
            with L1:
                st.markdown("**" + T("bat_leader_speed", lang=lang) + "**")
                a = qual.nlargest(15, "avg_bat_speed")[[c for c in cols if c in qual.columns]].rename(columns=cols)
                show_table(a.style.format(fm, na_rep="—"))
            with L2:
                st.markdown("**" + T("bat_leader_xwoba", lang=lang) + "**")
                b = qual.nlargest(15, "xwoba")[[c for c in cols if c in qual.columns]].rename(columns=cols)
                show_table(b.style.format(fm, na_rep="—"))
            fig = go.Figure(go.Scattergl(x=qual["avg_bat_speed"], y=qual["xwoba"], mode="markers", text=qual["batter_name"],
                                         marker=dict(size=7, color="#58a6ff", opacity=0.55),
                                         hovertemplate="<b>%{text}</b><br>%{x:.1f} mph · xwOBA %{y:.3f}<extra></extra>"))
            sel = qual[qual["batter_name"] == batter]
            if not sel.empty:
                fig.add_trace(go.Scatter(x=sel["avg_bat_speed"], y=sel["xwoba"], mode="markers+text", text=[batter],
                                         textposition="top center", marker=dict(size=13, color="#ff6b35"), showlegend=False))
            fig.update_layout(showlegend=False)
            st.plotly_chart(themed(fig, height=420, title=T("bat_scatter_title", lang=lang),
                                   xaxis_title=T("bat_kpi_speed", lang=lang), yaxis_title="xwOBA"),
                            use_container_width=True, key="bat_scatter_fig")
