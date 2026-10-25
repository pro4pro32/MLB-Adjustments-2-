"""
insights_engine.py — LOCAL stats/ML that finds patterns and packs them into COMPACT evidence for Claude.

No LLM and no UI in here. Claude never sees raw rows: it only gets the small JSON these functions build,
and is instructed to use nothing else. Methods: robust z-score anomalies, change-point (max t-statistic split),
k-means clustering of approach changes, bootstrap confidence intervals, and honest noise thresholds.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from config import ALL_CATEGORIES, ALL_ZONES, CAT_COLS, PITCH_CAT_COLS, ZONE_CAT_COLS
from compute import (adjustments_vs_ops, compute_period_comparison, compute_period_correlations,
                     sustained_movers_leaderboard, weekly_top_pct_counts)


def _k(c: str) -> str:
    return c.replace("_pct", "")


D_LABEL = {f"d_{_k(c)}": ALL_CATEGORIES[c]["short"] for c in CAT_COLS}   # d_fb -> FB%, d_bb -> BR%, d_zone9 -> Z9%
MIX_D = ["d_fb", "d_bb", "d_os"]
ZONE_D = [f"d_{_k(c)}" for c in ZONE_CAT_COLS]


# ───────────────────────────── helpers ─────────────────────────────
def clean(o):
    """JSON-safe: numpy -> python, NaN/inf -> None, Timestamp -> 'YYYY-MM-DD', floats rounded."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    if o is None or o is pd.NaT or o is pd.NA:
        return None
    return o


def robust_z(s: pd.Series) -> pd.Series:
    """(x - median) / (1.4826 * MAD); falls back to the std when MAD is 0."""
    s = pd.to_numeric(s, errors="coerce")
    med = s.median()
    mad = (s - med).abs().median() * 1.4826
    if not mad or np.isnan(mad):
        sd = s.std()
        return (s - med) / sd if sd and not np.isnan(sd) else s * 0.0
    return (s - med) / mad


def change_point(values, min_seg: int = 3):
    """Best single mean-shift split of a series (max |t|). Returns None if the series is too short/flat."""
    v = np.asarray([x for x in values if x is not None and not np.isnan(x)], dtype=float)
    n = len(v)
    if n < 2 * min_seg or float(np.std(v)) == 0.0:
        return None
    best = None
    for k in range(min_seg, n - min_seg + 1):
        a, b = v[:k], v[k:]
        sp2 = ((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (n - 2)
        if sp2 <= 0:
            continue
        t = (b.mean() - a.mean()) / math.sqrt(sp2 * (1 / len(a) + 1 / len(b)))
        if best is None or abs(t) > abs(best["t"]):
            best = {"split_index": k, "mean_before": float(a.mean()), "mean_after": float(b.mean()),
                    "shift": float(b.mean() - a.mean()), "t": float(t)}
    return best


def strength(t: float) -> str:
    t = abs(t)
    return "strong" if t >= 4.5 else ("moderate" if t >= 3.5 else "weak")


def kmeans(X: np.ndarray, k: int, seed: int = 0, iters: int = 60):
    rng = np.random.default_rng(seed)
    n = len(X)
    centers = [X[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min([((X - c) ** 2).sum(1) for c in centers], axis=0)
        p = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1.0 / n)
        centers.append(X[rng.choice(n, p=p)])
    C = np.array(centers)
    lab = np.zeros(n, dtype=int)
    for _ in range(iters):
        lab = ((X[:, None, :] - C[None, :, :]) ** 2).sum(2).argmin(1)
        newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab, C


def boot_corr_ci(x, y, n_boot: int = 300, seed: int = 0):
    x = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce"), dtype=float)
    y = np.asarray(pd.to_numeric(pd.Series(y), errors="coerce"), dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 20:
        return None
    rng = np.random.default_rng(seed)
    rs = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        xs, ys = x[i], y[i]
        if xs.std() == 0 or ys.std() == 0:
            continue
        rs.append(float(np.corrcoef(xs, ys)[0, 1]))
    if len(rs) < 50:
        return None
    return float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5))


def _meta(data_source: str) -> dict:
    synth = data_source == "syntetyczne"
    return {"data_source": "synthetic_demo" if synth else "real_data",
            "note": "SIMULATED demo data - not real performance" if synth else "observed pitch-by-pitch data",
            "glossary": "FB=fastball share, BR=breaking-ball share (not walks), OS=offspeed share, Zn=Statcast zone n share; "
                        "changes are percentage points of pitches thrown TO the hitter; Adjustment Score = how much pitchers "
                        "changed their approach to him vs the previous week (all 16 categories, direction ignored)."}


def _top(df: pd.DataFrame, col: str, n: int, ascending: bool, extra=("total",)) -> list:
    sub = df.dropna(subset=[col]).sort_values(col, ascending=ascending).head(n)
    keep = [c for c in ["batter_name", "batter_team", "team", col, *extra] if c in sub.columns]
    return clean(sub[keep].to_dict("records"))


def _mean(df, c):
    return float(pd.to_numeric(df[c], errors="coerce").mean()) if c in df.columns else None


# ───────────────────────────── evidence builders ─────────────────────────────
def batter_evidence(bd, bw_all, batter, data_source="", recent_weeks=10) -> dict:
    w = bw_all[bw_all["batter_name"] == batter].sort_values("week_start")
    if w.empty:
        return {"error": f"No data for batter '{batter}'."}
    d = bd[bd["batter_name"] == batter].sort_values("week_start")
    out = {"meta": _meta(data_source), "batter": batter}
    if "batter_team" in w.columns:
        m = w["batter_team"].mode()
        out["team"] = str(m.iloc[0]) if len(m) else None
        out["teams_seen"] = [str(t) for t in w["batter_team"].dropna().unique()][:3]
    out["weeks_with_data"] = int(len(w))
    out["first_week"], out["last_week"] = str(w["week_label_short"].iloc[0]), str(w["week_label_short"].iloc[-1])
    out["total_pitches_seen"] = int(w["total"].sum())

    ws = list(w["week_start"])
    gaps = []
    for a, b in zip(ws[:-1], ws[1:]):
        days = (b - a).days
        if days > 14:
            gaps.append({"no_pitches_seen_between": f"{pd.Timestamp(a).date()} and {pd.Timestamp(b).date()}",
                         "weeks_missing": int(days // 7) - 1})
    out["gaps_in_data"] = gaps[:5]

    if not d.empty:
        last = d.iloc[-1]
        same = bd[bd["week_start"] == last["week_start"]]
        if "reliable" in same.columns:
            same = same[same["reliable"]]
        pct = float((same["adj_score"] < last["adj_score"]).mean() * 100) if len(same) else None
        latest = {"week": str(last["week_label_short"]), "pitches": int(last["total"]),
                  "reliable": bool(last["reliable"]) if "reliable" in d.columns else None,
                  "adj_score": last["adj_score"], "adj_score_percentile_in_league_that_week": pct,
                  "biggest_move": {"category": last.get("top_mover_label"), "delta_pp": last.get("top_mover_delta")}}
        for c in ("whiff_pct", "ops_wk", "d_ops_wk", "pa_wk"):
            if c in d.columns:
                latest[c] = last[c]
        out["latest_week"] = latest
        cols = {"week_label_short": "week", "total": "pitches", "adj_score": "adj_score", "fb_pct": "FB%",
                "bb_pct": "BR%", "os_pct": "OS%", "d_fb": "dFB", "d_bb": "dBR", "d_os": "dOS",
                "ops_wk": "OPS", "pa_wk": "PA", "reliable": "reliable"}
        out["recent_weeks"] = d.tail(recent_weeks)[[c for c in cols if c in d.columns]].rename(columns=cols).to_dict("records")
        if len(d) >= 6:
            z = robust_z(d["adj_score"])
            hot = d.assign(_z=z)[z > 2.5].sort_values("_z", ascending=False).head(3)
            out["unusual_adjustment_weeks_vs_own_history"] = [
                {"week": str(r["week_label_short"]), "adj_score": r["adj_score"], "robust_z": r["_z"]} for _, r in hot.iterrows()]

    def wavg(frame, col):
        return float(np.average(frame[col], weights=frame["total"])) if frame["total"].sum() > 0 else None

    if len(w) >= 6:
        early, late = w.iloc[:-4], w.iloc[-4:]
        mix = {}
        for c in PITCH_CAT_COLS:
            a, b = wavg(early, c), wavg(late, c)
            mix[ALL_CATEGORIES[c]["short"]] = {"before": a, "last_4_weeks": b, "change_pp": None if a is None or b is None else b - a}
        out["pitch_mix_before_vs_last4"] = mix
        zs = []
        for c in ZONE_CAT_COLS:
            a, b = wavg(early, c), wavg(late, c)
            if a is not None and b is not None:
                zs.append({"zone": ALL_CATEGORIES[c]["short"], "before": a, "last_4_weeks": b, "change_pp": b - a})
        zs.sort(key=lambda r: r["change_pp"])
        out["zone_shifts"] = {"biggest_increases": zs[::-1][:3], "biggest_decreases": zs[:3]}

    cps = {}
    for c in PITCH_CAT_COLS:
        cp = change_point(w[c].to_numpy(dtype=float))
        if cp and abs(cp["t"]) >= 3:
            cps[ALL_CATEGORIES[c]["short"]] = {"from_week": str(w["week_label_short"].iloc[cp["split_index"]]),
                                               "mean_before": cp["mean_before"], "mean_after": cp["mean_after"],
                                               "shift_pp": cp["shift"], "strength": strength(cp["t"])}
    out["detected_shifts"] = cps
    out["caveats"] = ["weeks with <20 pitches are flagged reliable=false", "weekly OPS rests on ~15-30 PA and is noisy",
                      "detected shifts are statistical heuristics, not proof of intent"]
    return clean(out)


def league_week_evidence(bd, data_source="", week_start=None, top_n=10) -> dict:
    if bd is None or bd.empty:
        return {"error": "No data."}
    d = bd[bd["reliable"]] if "reliable" in bd.columns else bd
    if d.empty:
        return {"error": "No reliable batter-weeks."}
    wk = week_start if week_start is not None else d["week_start"].max()
    dw = d[d["week_start"] == wk]
    if dw.empty:
        return {"error": "No reliable data for that week."}
    out = {"meta": _meta(data_source), "week": str(dw["week_label_short"].iloc[0]),
           "week_start": str(pd.Timestamp(wk).date()), "reliable_batters_this_week": int(len(dw)),
           "adj_score": {"mean": dw["adj_score"].mean(), "median": dw["adj_score"].median(),
                         "p90": dw["adj_score"].quantile(0.9)}}
    cols = [c for c in ["batter_name", "batter_team", "adj_score", "top_mover_label", "top_mover_delta", "total", "ops_wk", "d_ops_wk"] if c in dw.columns]
    out["top_adjusted_hitters"] = clean(dw.sort_values("adj_score", ascending=False).head(top_n)[cols].to_dict("records"))
    out["pitch_mix_movers"] = {D_LABEL[c]: {"biggest_increases": _top(dw, c, 3, False), "biggest_decreases": _top(dw, c, 3, True)}
                               for c in MIX_D if c in dw.columns}
    try:
        sus = sustained_movers_leaderboard(d, top_n=8, min_streak=3)
        out["sustained_trends_3plus_weeks"] = clean(sus[["batter_name", "category", "streak_weeks", "cumulative_delta"]].to_dict("records")) if not sus.empty else []
    except Exception:
        out["sustained_trends_3plus_weeks"] = []
    z = robust_z(dw["adj_score"])
    out["statistical_outliers_this_week"] = clean(dw.assign(_z=z)[z > 3].sort_values("_z", ascending=False).head(5)[
        [c for c in ["batter_name", "batter_team", "adj_score", "_z"] if c in dw.assign(_z=z).columns]].to_dict("records"))
    need = {"pa_wk", "pa_wk_prev", "d_ops_wk"}
    if need.issubset(dw.columns):
        q = dw[(dw["pa_wk"] >= 10) & (dw["pa_wk_prev"] >= 10)].dropna(subset=["d_ops_wk"])
        if len(q) >= 20:
            cut = q["adj_score"].quantile(0.75)
            hi, lo = q[q["adj_score"] >= cut], q[q["adj_score"] < cut]
            out["this_week_ops_check"] = {"n_most_adjusted_quartile": int(len(hi)), "n_rest": int(len(lo)),
                                          "mean_dOPS_most_adjusted_quartile": hi["d_ops_wk"].mean(),
                                          "mean_dOPS_rest": lo["d_ops_wk"].mean(),
                                          "note": "single-week snapshot - very noisy"}
    res = adjustments_vs_ops(d, min_pa=12)
    if res["n"] >= 10 and not np.isnan(res["r_adj_dops"]):
        ci = boot_corr_ci(res["data"]["adj_score"], res["data"]["d_ops_wk"])
        out["season_long_adjustments_vs_ops"] = {
            "batter_weeks": res["n"], "r_adjscore_vs_dOPS": res["r_adj_dops"], "ci95": None if ci is None else list(ci),
            "avg_dOPS_top_quarter_adj": res["q4_dops"], "avg_dOPS_bottom_quarter_adj": res["q1_dops"],
            "caveat": "correlation, not causation; regression to the mean and pitchers targeting hot hitters can create a negative link"}
    return clean(out)


def period_evidence(comp, delta_cols, delta_labels, weeks_p1, weeks_p2, min_pitches, data_source="") -> dict:
    if comp is None or comp.empty:
        return {"error": "No batters pass the filters."}
    n = len(comp)

    def span(ws):
        return f"{pd.Timestamp(min(ws)).date()} .. {pd.Timestamp(max(ws)).date()} ({len(ws)} weeks)"

    out = {"meta": _meta(data_source), "n_batters": n, "period_1": span(weeks_p1), "period_2": span(weeks_p2),
           "min_pitches_per_period": int(min_pitches)}
    present = [c for c in delta_cols if c in comp.columns]
    out["league_mean_change"] = {delta_labels.get(c, c): _mean(comp, c) for c in present}
    key = [c for c in ["d_fb", "d_bb", "d_os", "d_ops", "d_velo"] if c in comp.columns]
    zmeans = sorted([c for c in ZONE_D if c in comp.columns], key=lambda c: -abs(_mean(comp, c) or 0))[:2]
    extra = ("total_p1", "total_p2", "ops_p1", "ops_p2")
    out["notable_movers"] = {delta_labels.get(c, c): {"largest_increase": _top(comp, c, 4, False, extra),
                                                      "largest_decrease": _top(comp, c, 4, True, extra)}
                             for c in key + zmeans}

    corr = compute_period_correlations(comp, present)
    if not corr.empty:
        cols = list(corr.columns)

        def fam(c):
            return "mix" if c in MIX_D else ("ops" if c in ("d_ops", "d_obp", "d_slg") else ("zone" if c.startswith("d_zone") else "other"))

        pairs = []
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a, b, r = cols[i], cols[j], corr.iloc[i, j]
                if pd.isna(r):
                    continue
                pairs.append({"a": a, "b": b, "r": float(r), "structural": fam(a) == fam(b) and fam(a) in ("mix", "ops", "zone")})
        inter = sorted([p for p in pairs if not p["structural"]], key=lambda p: -abs(p["r"]))[:8]
        for p in inter[:5]:
            ci = boot_corr_ci(comp[p["a"]], comp[p["b"]])
            p["ci95"] = None if ci is None else [ci[0], ci[1]]
        for p in inter:
            p["a"], p["b"] = delta_labels.get(p["a"], p["a"]), delta_labels.get(p["b"], p["b"])
        out["strongest_non_structural_correlations"] = inter
        out["correlation_noise"] = {"n": n, "approx_noise_threshold_abs_r": 1.96 / math.sqrt(n),
                                    "pairs_tested": len([p for p in pairs if not p["structural"]]),
                                    "note": "structural pairs (mix vs mix, zones vs zones, OPS/OBP/SLG) excluded - they move together by construction; with this many pairs some look strong by chance"}
    if "d_ops" in comp.columns:
        rows = []
        for c in MIX_D + ZONE_D:
            if c in comp.columns:
                x = pd.to_numeric(comp[c], errors="coerce")
                y = pd.to_numeric(comp["d_ops"], errors="coerce")
                ok = x.notna() & y.notna()
                if ok.sum() >= 20 and x[ok].nunique() > 1:
                    rows.append((c, float(x[ok].corr(y[ok]))))
        rows.sort(key=lambda t: -abs(t[1]))
        top = []
        for c, r in rows[:5]:
            ci = boot_corr_ci(comp[c], comp["d_ops"])
            top.append({"change": delta_labels.get(c, c), "r_with_dOPS": r, "ci95": None if ci is None else list(ci)})
        out["changes_most_related_to_dOPS"] = top

    feats = [c for c in MIX_D + ZONE_D if c in comp.columns]
    X = comp[feats].apply(pd.to_numeric, errors="coerce")
    ok = X.notna().all(axis=1)
    if len(feats) >= 4 and ok.sum() >= 30:
        Xv = X[ok].to_numpy(dtype=float)
        mu, sd = Xv.mean(0), Xv.std(0)
        sd[sd == 0] = 1.0
        Z = (Xv - mu) / sd
        k = 4 if ok.sum() >= 60 else 3
        lab, C = kmeans(Z, k)
        sub = comp[ok].reset_index(drop=True)
        clusters = []
        for j in range(k):
            idx = np.where(lab == j)[0]
            if len(idx) == 0:
                continue
            m = sub.iloc[idx]
            top_z = sorted(((delta_labels.get(c, c), _mean(m, c)) for c in ZONE_D if c in feats), key=lambda t: -abs(t[1]))[:3]
            dist = ((Z[idx] - C[j]) ** 2).sum(1)
            clusters.append({"n": int(len(idx)), "mean_dFB": _mean(m, "d_fb"), "mean_dBR": _mean(m, "d_bb"),
                             "mean_dOS": _mean(m, "d_os"),
                             "biggest_zone_shifts": [{"zone": z, "mean_change_pp": v} for z, v in top_z],
                             "mean_dOPS": _mean(m, "d_ops"), "mean_dVelo": _mean(m, "d_velo"),
                             "typical_batters": [str(sub.iloc[idx[i]]["batter_name"]) for i in np.argsort(dist)[:3]]})
        clusters.sort(key=lambda c: -c["n"])
        eta = None
        if "d_ops" in sub.columns:
            y = pd.to_numeric(sub["d_ops"], errors="coerce")
            total_ss = float(((y - y.mean()) ** 2).sum())
            if total_ss > 0:
                between = sum(int((lab == j).sum()) * (y[lab == j].mean() - y.mean()) ** 2 for j in range(k) if (lab == j).any())
                eta = float(between / total_ss)
        out["approach_clusters"] = {"method": "k-means on standardized pitch-mix and zone changes", "k": k,
                                    "clusters": clusters, "eta_squared_dOPS_explained_by_cluster": eta}
    return clean(out)


def wbw_evidence(bd, data_source, week_start, m1, mode1, m2, top_pct, mode2, min_pa, labels) -> dict:
    if bd is None or bd.empty:
        return {"error": "No data."}
    out = {"meta": _meta(data_source)}
    d = bd[bd["reliable"]] if "reliable" in bd.columns else bd
    if m1 in d.columns:
        dw = d[d["week_start"] == week_start].dropna(subset=[m1])
        if not dw.empty:
            v = pd.to_numeric(dw[m1], errors="coerce")
            key = v if mode1 == "up" else (-v if mode1 == "down" else v.abs())
            dw = dw.assign(_k=key).sort_values("_k", ascending=False).head(10)
            cols = list(dict.fromkeys(c for c in ["batter_name", "batter_team", m1, "adj_score", "ops_wk"] if c in dw.columns))
            out["part1_week_ranking"] = {"week": str(dw["week_label_short"].iloc[0]), "metric": labels.get(m1, m1),
                                         "mode": mode1, "top10": clean(dw[cols].to_dict("records"))}
    t = weekly_top_pct_counts(bd, m2, float(top_pct), mode=mode2)
    if not t.empty:
        pos = t[t["weeks_in_top"] > 0]
        obs = float(t["weeks_observed"].mean())
        out["part2_top_pct_frequency"] = {
            "metric": labels.get(m2, m2), "mode": mode2, "top_pct": top_pct,
            "chance_share_pct_if_random": float(top_pct), "mean_weeks_observed": obs,
            "expected_weeks_in_top_if_random": obs * top_pct / 100.0,
            "max_share_pct": float(t["share_pct"].max()), "n_batters_ever_in_top": int(len(pos)),
            "leaders": clean(pos.head(10).to_dict("records"))}
    res = adjustments_vs_ops(bd, min_pa=min_pa)
    if res["n"] >= 10 and not res["corr"].empty:
        ci = boot_corr_ci(res["data"]["adj_score"], res["data"]["d_ops_wk"])
        lab = lambda m: "Adjustment Score" if m == "adj_score" else D_LABEL.get(m, m)
        c = res["corr"]
        out["part3_adjustments_vs_ops"] = {
            "min_pa": min_pa, "batter_weeks": res["n"], "r_adjscore_vs_dOPS": res["r_adj_dops"],
            "ci95": None if ci is None else list(ci),
            "avg_dOPS_top_quarter_adj": res["q4_dops"], "avg_dOPS_bottom_quarter_adj": res["q1_dops"],
            "most_negative_vs_dOPS": [{"metric": lab(r.metric), "r": r.r_dops} for r in c.head(3).itertuples()],
            "most_positive_vs_dOPS": [{"metric": lab(r.metric), "r": r.r_dops} for r in c.tail(3).iloc[::-1].itertuples()],
            "caveat": "correlation, not causation; weekly OPS is noisy"}
    return clean(out)


# ───────────────────────────── tools for the chat ─────────────────────────────
TOOLS = [
    {"name": "league_summary", "description": "Overview of the loaded data: data source, number of batters/weeks, date range, average Adjustment Score, metrics available.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_weeks", "description": "List available weeks as week_start dates (YYYY-MM-DD) with labels. Call this to map 'week 25' or 'last month' to dates.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "find_batters", "description": "Find batter names matching a partial name (e.g. 'judge').",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "batter_profile", "description": "Evidence pack for ONE hitter: team, data gaps, latest week, recent weeks, pitch-mix and zone shifts, detected change points, OPS trend.",
     "input_schema": {"type": "object", "properties": {"batter_name": {"type": "string"}}, "required": ["batter_name"]}},
    {"name": "top_movers", "description": "Top hitters in one week for a metric. metric: adj_score, fb, br, os, ops, or zone1..zone14 (zone10 does not exist). direction: abs (either way), up, down.",
     "input_schema": {"type": "object", "properties": {"metric": {"type": "string"}, "week_start": {"type": "string", "description": "YYYY-MM-DD from list_weeks; default = latest"},
                                                       "direction": {"type": "string", "enum": ["abs", "up", "down"]}, "top_n": {"type": "integer"}}, "required": ["metric"]}},
    {"name": "compare_periods", "description": "Whole-league Period 1 vs Period 2 comparison (every batter): changes in FB/BR/OS, zones, velocity, OPS, plus correlations and approach clusters. Use week_start dates from list_weeks.",
     "input_schema": {"type": "object", "properties": {"p1_start": {"type": "string"}, "p1_end": {"type": "string"}, "p2_start": {"type": "string"}, "p2_end": {"type": "string"},
                                                       "sort_by": {"type": "string", "description": "ops, fb, br, os, velo or zone1..zone14"},
                                                       "direction": {"type": "string", "enum": ["up", "down"]}, "top_n": {"type": "integer"}, "min_pitches": {"type": "integer"}},
                      "required": ["p1_start", "p1_end", "p2_start", "p2_end"]}},
    {"name": "adjustments_vs_ops", "description": "Do bigger pitcher adjustments go with lower OPS? Correlations (with bootstrap CI) and quartile comparison over batter-weeks.",
     "input_schema": {"type": "object", "properties": {"min_pa": {"type": "integer"}}}},
]


def _metric_col(key: str, weekly: bool):
    k = str(key).strip().lower().replace("%", "")
    if k in ("adj", "adj_score", "adjustment", "adjustment_score"):
        return "adj_score" if weekly else None
    if k in ("fb", "fastball"):
        return "d_fb"
    if k in ("br", "bb", "breaking", "breaking_ball"):
        return "d_bb"
    if k in ("os", "offspeed"):
        return "d_os"
    if k == "ops":
        return "d_ops_wk" if weekly else "d_ops"
    if k == "velo" and not weekly:
        return "d_velo"
    m = re.fullmatch(r"(?:z|zone)(\d+)", k)
    if m and int(m.group(1)) in ALL_ZONES:
        return f"d_zone{int(m.group(1))}"
    return None


def _ts(s):
    return pd.Timestamp(str(s)).normalize()


def run_tool(name, args, bd, bw_all, raw_df, data_source="") -> dict:
    """Execute one chat tool on the loaded data. Never raises; always returns compact JSON-safe data."""
    try:
        args = args or {}
        if name == "league_summary":
            d = bd[bd["reliable"]] if "reliable" in bd.columns else bd
            ws = sorted(bw_all["week_start"].unique())
            return clean({"meta": _meta(data_source), "n_batters": int(bw_all["batter_name"].nunique()), "n_weeks": len(ws),
                          "first_week_start": ws[0], "last_week_start": ws[-1],
                          "mean_adj_score_reliable": d["adj_score"].mean() if len(d) else None,
                          "metrics": ["adj_score", "fb", "br", "os", "ops", "velo (periods only)"] + [f"zone{z}" for z in ALL_ZONES]})
        if name == "list_weeks":
            w = bw_all[["week_start", "week_label_short"]].drop_duplicates().sort_values("week_start").tail(60)
            return clean({"weeks": [{"week_start": r.week_start, "label": r.week_label_short} for r in w.itertuples()]})
        if name == "find_batters":
            toks = str(args.get("query", "")).lower().split()
            names = sorted(set(bw_all["batter_name"].astype(str)))
            return {"matches": [n for n in names if toks and all(t in n.lower() for t in toks)][:10]}
        if name == "batter_profile":
            nm = str(args.get("batter_name", ""))
            names = sorted(set(bw_all["batter_name"].astype(str)))
            if nm not in names:
                toks = nm.lower().split()
                hits = [n for n in names if toks and all(t in n.lower() for t in toks)]
                if len(hits) == 1:
                    nm = hits[0]
                else:
                    return {"error": f"Batter '{nm}' not found or ambiguous.", "did_you_mean": hits[:8]}
            return batter_evidence(bd, bw_all, nm, data_source)
        if name == "top_movers":
            col = _metric_col(args.get("metric", ""), weekly=True)
            if col is None or col not in bd.columns:
                return {"error": "Unknown metric. Use adj_score, fb, br, os, ops or zone1..zone14."}
            d = bd[bd["reliable"]] if "reliable" in bd.columns else bd
            wk = _ts(args["week_start"]) if args.get("week_start") else d["week_start"].max()
            dw = d[d["week_start"].dt.normalize() == pd.Timestamp(wk).normalize()].dropna(subset=[col])
            if dw.empty:
                return {"error": "No reliable data for that week. Call list_weeks."}
            v = pd.to_numeric(dw[col], errors="coerce")
            mode = args.get("direction", "abs")
            key = v if (mode == "up" or col == "adj_score") else (-v if mode == "down" else v.abs())
            n = max(1, min(int(args.get("top_n", 10)), 15))
            dw = dw.assign(_k=key).sort_values("_k", ascending=False).head(n)
            cols = list(dict.fromkeys(c for c in ["batter_name", "batter_team", col, "adj_score", "total", "ops_wk", "d_ops_wk"] if c in dw.columns))
            return clean({"week": str(dw["week_label_short"].iloc[0]), "metric": col, "direction": mode, "rows": dw[cols].to_dict("records")})
        if name == "compare_periods":
            ws = bw_all["week_start"].drop_duplicates().sort_values()
            w1 = list(ws[(ws >= _ts(args["p1_start"])) & (ws <= _ts(args["p1_end"]))])
            w2 = list(ws[(ws >= _ts(args["p2_start"])) & (ws <= _ts(args["p2_end"]))])
            if not w1 or not w2:
                return {"error": "A period contains no weeks. Call list_weeks and use week_start dates."}
            minp = max(5, int(args.get("min_pitches", 30)))
            comp = compute_period_comparison(raw_df, bw_all, w1, w2, min_pitches=minp)
            if comp.empty:
                return {"error": "No batters pass the min_pitches filter for both periods."}
            labels = dict(D_LABEL, d_ops="OPS", d_obp="OBP", d_slg="SLG", d_velo="Velo")
            dcols = [c for c in ["d_ops", "d_obp", "d_slg", "d_velo"] + MIX_D + ZONE_D if c in comp.columns]
            ev = period_evidence(comp, dcols, labels, w1, w2, minp, data_source)
            ev["notable_movers"] = {k: v for k, v in ev.get("notable_movers", {}).items() if k in ("OPS", "FB%", "BR%", "OS%")}
            sc = _metric_col(args.get("sort_by", "ops"), weekly=False) or "d_ops"
            asc = args.get("direction", "up") == "down"
            n = max(1, min(int(args.get("top_n", 8)), 15))
            ev["sorted_rows"] = {"sort_by": sc, "direction": "down" if asc else "up",
                                 "rows": _top(comp, sc, n, asc, ("total_p1", "total_p2", "ops_p1", "ops_p2", "d_ops", "d_fb", "d_bb", "d_os"))}
            return ev
        if name == "adjustments_vs_ops":
            minpa = max(3, int(args.get("min_pa", 12)))
            return wbw_evidence(bd, data_source, bd["week_start"].max(), "adj_score", "up", "adj_score", 10, "up", minpa,
                                {"adj_score": "Adjustment Score"})
        return {"error": f"Unknown tool '{name}'."}
    except Exception as e:  # tools must never crash the chat
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
