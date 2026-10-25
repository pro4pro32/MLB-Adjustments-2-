"""ai_ui.py — Streamlit renderers for the AI layer (sidebar, per-tab explain blocks, chat)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import streamlit as st

import ai_client
import insights_engine as eng
from i18n import T
from ui_components import section


@dataclass
class AIConfig:
    api_key: str | None
    model: str


@dataclass
class AIContext:
    bd_league: Any
    bw_all: Any
    raw_df: Any
    data_source: str
    lang: str
    cfg: AIConfig


def _secret_key() -> str | None:
    try:
        v = st.secrets["ANTHROPIC_API_KEY"]
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or None


def render_ai_sidebar(lang: str) -> AIConfig:
    with st.sidebar:
        st.markdown(T("ai_sidebar_header", lang=lang))
        key = _secret_key()
        if key:
            st.caption(T("ai_key_found", lang=lang))
        else:
            key = st.text_input(T("ai_key_label", lang=lang), type="password", key="ai_api_key_input",
                                help=T("ai_key_help", lang=lang)).strip() or None
        model = st.selectbox(T("ai_model_label", lang=lang), list(ai_client.MODELS), key="ai_model",
                             format_func=lambda m: ai_client.MODELS[m])
        st.caption(T("ai_privacy", lang=lang))
    return AIConfig(api_key=key, model=model)


def _generate_block(ctx: AIContext, key: str, sig: str, title: str, task: str, build_evidence, max_tokens: int = 1100) -> None:
    section(title)
    if ctx.data_source == "syntetyczne":
        st.warning(T("ai_synth_warning", lang=ctx.lang))
    if not ctx.cfg.api_key:
        st.info(T("ai_need_key", lang=ctx.lang))
        return
    state_key = f"ai_out::{key}"
    saved = st.session_state.get(state_key)
    have = bool(saved and saved.get("sig") == sig)
    if st.button(T("ai_regenerate" if have else "ai_generate", lang=ctx.lang), key=f"ai_btn::{key}"):
        try:
            with st.spinner(T("ai_generating", lang=ctx.lang)):
                ev = build_evidence()
                if "error" in ev:
                    st.info(T("ai_no_data", lang=ctx.lang))
                    return
                client = ai_client.make_client(ctx.cfg.api_key)
                text = ai_client.generate(client, ctx.cfg.model, ai_client.build_system(ctx.lang), task, ev, max_tokens)
            saved = {"sig": sig, "text": text, "evidence": ev, "model": ctx.cfg.model}
            st.session_state[state_key] = saved
            have = True
        except Exception as e:
            st.error(T("ai_error", lang=ctx.lang, err=ai_client.safe_error(e)))
            return
    if have:
        st.markdown(saved["text"])
        st.caption(T("ai_footer", lang=ctx.lang, model=saved["model"]))
        with st.expander(T("ai_evidence", lang=ctx.lang)):
            st.json(saved["evidence"], expanded=False)


def render_ai_scouting(ctx: AIContext, batter) -> None:
    if not batter or ctx.bd_league is None or ctx.bd_league.empty:
        return
    sig = f"{batter}|{ctx.data_source}|{len(ctx.bd_league)}|{ctx.cfg.model}|{ctx.lang}"
    _generate_block(ctx, "scout", sig, T("ai_scout_title", lang=ctx.lang), "scout",
                    lambda: eng.batter_evidence(ctx.bd_league, ctx.bw_all, batter, ctx.data_source), 900)


def render_ai_digest(ctx: AIContext) -> None:
    if ctx.bd_league is None or ctx.bd_league.empty:
        return
    wk = ctx.bd_league["week_start"].max()
    sig = f"{wk}|{ctx.data_source}|{len(ctx.bd_league)}|{ctx.cfg.model}|{ctx.lang}"
    _generate_block(ctx, "digest", sig, T("ai_digest_title", lang=ctx.lang), "digest",
                    lambda: eng.league_week_evidence(ctx.bd_league, ctx.data_source, wk), 1000)


def render_ai_explain_period(ctx: AIContext, comp, delta_cols, delta_labels, weeks_p1, weeks_p2, min_pitches) -> None:
    sig = f"{min(weeks_p1)}|{max(weeks_p1)}|{min(weeks_p2)}|{max(weeks_p2)}|{min_pitches}|{len(comp)}|{ctx.cfg.model}|{ctx.lang}"
    _generate_block(ctx, "period", sig, T("ai_explain_title", lang=ctx.lang), "period",
                    lambda: eng.period_evidence(comp, delta_cols, delta_labels, weeks_p1, weeks_p2, min_pitches, ctx.data_source), 1100)


def render_ai_explain_wbw(ctx: AIContext, week_start, m1, mode1, m2, top_pct, mode2, min_pa, labels) -> None:
    sig = f"{week_start}|{m1}|{mode1}|{m2}|{top_pct}|{mode2}|{min_pa}|{ctx.cfg.model}|{ctx.lang}"
    _generate_block(ctx, "wbw", sig, T("ai_explain_title", lang=ctx.lang), "wbw",
                    lambda: eng.wbw_evidence(ctx.bd_league, ctx.data_source, week_start, m1, mode1, m2, top_pct, mode2, min_pa, labels), 1100)


def render_ai_chat(ctx: AIContext) -> None:
    section(T("ai_chat_header", lang=ctx.lang))
    st.caption(T("ai_chat_caption", lang=ctx.lang))
    if ctx.data_source == "syntetyczne":
        st.warning(T("ai_synth_warning", lang=ctx.lang))
    if not ctx.cfg.api_key:
        st.info(T("ai_need_key", lang=ctx.lang))
        return
    hist = st.session_state.setdefault("ai_chat_history", [])
    cols = st.columns(4)
    for i, k in enumerate(("ai_ex1", "ai_ex2", "ai_ex3", "ai_ex4")):
        if cols[i].button(T(k, lang=ctx.lang), key=f"ai_ex_btn_{i}"):
            st.session_state["ai_chat_pending"] = T(k, lang=ctx.lang)
    if hist and st.button(T("ai_chat_clear", lang=ctx.lang), key="ai_chat_clear_btn"):
        st.session_state["ai_chat_history"] = hist = []
    for m in hist:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("tools"):
                st.caption(T("ai_tools_used", lang=ctx.lang, tools=", ".join(m["tools"])))
    typed = st.chat_input(T("ai_chat_placeholder", lang=ctx.lang), key="ai_chat_input")
    q = st.session_state.pop("ai_chat_pending", None) or typed
    if not q:
        return
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        try:
            with st.spinner(T("ai_generating", lang=ctx.lang)):
                client = ai_client.make_client(ctx.cfg.api_key)
                runner = lambda name, args: eng.run_tool(name, args, ctx.bd_league, ctx.bw_all, ctx.raw_df, ctx.data_source)
                text, used = ai_client.chat(client, ctx.cfg.model, ai_client.build_system(ctx.lang, chat=True),
                                            hist, q, eng.TOOLS, runner)
            st.markdown(text)
            tools = list(dict.fromkeys(used))
            if tools:
                st.caption(T("ai_tools_used", lang=ctx.lang, tools=", ".join(tools)))
            hist.append({"role": "user", "content": q})
            hist.append({"role": "assistant", "content": text, "tools": tools})
        except Exception as e:
            st.error(T("ai_error", lang=ctx.lang, err=ai_client.safe_error(e)))
