"""ai_client.py — thin Anthropic wrapper: system prompt, single-shot generation, tool-using chat loop."""
from __future__ import annotations

import json
import re

LANG_NAMES = {"en": "English", "pl": "Polish", "fr": "French", "es": "Spanish", "ja": "Japanese"}
MODELS = {
    "claude-sonnet-5-5": "Sonnet 5.5 — balanced (default)",
    "claude-haiku-4-5-20251001": "Haiku 4.5 — fastest / cheapest",
    "claude-opus-5-5": "Opus 5.5 — deepest",
}
DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM_BASE = """You are the analyst inside a baseball dashboard that tracks how pitchers change their approach toward each hitter week by week (pitch mix: FB = fastball share, BR = breaking-ball share (NOT walks), OS = offspeed share, plus 13 Statcast strike-zone shares) and whether the hitter's OPS moves.

HARD RULES
- Use ONLY numbers and facts present in the evidence/tool results. Never invent statistics, injuries, trades, causes or quotes. If something is not in the evidence, say it is not available.
- Pitch-mix and zone figures describe what was thrown TO the hitter (usage), not how he performed. OPS is the performance side.
- Correlation is not causation. Weekly OPS is noisy (about 15-30 plate appearances). When many correlations were tested, some look strong by chance: quote the confidence interval / noise threshold when given, and call something 'worth checking' only if its interval excludes 0.
- Weeks with no pitches seen are an absence from the data. Say 'consistent with a layoff' at most; never state an injury unless the user told you.
- If evidence.meta.data_source is 'synthetic_demo', START with one short line saying the numbers come from SIMULATED demo data and do not describe real performance.
- Be concise and scannable: short bold headings or bullets, numbers with units (pp = percentage points), no filler, no repetition of the raw JSON.
- Write the whole answer in {language}."""

CHAT_EXTRA = """
CHAT MODE: call the tools to fetch facts before answering (list_weeks to map 'week 25'/'last month' to dates; find_batters for partial names). Prefer one or two well-chosen tool calls. Keep answers under ~200 words unless asked for detail, lead with the answer, and end with one useful follow-up question or suggestion."""

TASKS = {
    "scout": "Write a scouting-style report on this hitter from the evidence. Use these bold headings: **Headline** (one sentence), **How pitchers are attacking him** (pitch mix + zones with numbers and the week of any detected shift), **Did it work?** (OPS trend vs the adjustments; state the sample size honestly), **Availability** (only if gaps_in_data is not empty), **Caveats & what to watch** (two bullets). About 220 words.",
    "digest": "Write this week's league digest from the evidence: up to 5 short items, most notable first, each 1-2 sentences with numbers (top adjustment stories, a sustained trend, outliers), then the adjustments-vs-OPS check with its confidence interval and what it does NOT prove. End with one line **Pattern of the week**. About 250 words.",
    "period": "Explain this Period 1 vs Period 2 table to a coach. Give 3-5 bullets on the main league-wide changes and the notable individual movers; one bullet on the approach clusters (what separates them, and whether their mean dOPS differs: use eta_squared); one bullet on correlations (structural pairs were excluded; mention the noise threshold and number of pairs tested; only call out relationships whose ci95 excludes 0 as 'worth checking'; never imply causation). About 250 words.",
    "wbw": "Explain the Week by Week views: (1) who moved most in the chosen week/metric, (2) whether the 'top X%' repeaters beat chance (compare max_share_pct and the leaders' shares with chance_share_pct and expected_weeks_in_top_if_random), (3) the adjustments-vs-OPS result with its confidence interval and an honest interpretation (regression to the mean, reverse causality). About 250 words.",
}


def build_system(lang: str, chat: bool = False) -> str:
    s = SYSTEM_BASE.replace("{language}", LANG_NAMES.get(lang, "English"))
    return s + (CHAT_EXTRA if chat else "")


def make_client(api_key: str):
    import anthropic  # lazy: the app still runs without the package until AI is used
    return anthropic.Anthropic(api_key=api_key, timeout=90.0, max_retries=2)


def _text(resp) -> str:
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()


def generate(client, model: str, system: str, task: str, evidence: dict, max_tokens: int = 1100) -> str:
    user = TASKS[task] + "\n\nEVIDENCE (JSON - the only facts you may use):\n" + json.dumps(evidence, ensure_ascii=False, default=str)
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}])
    return _text(resp)


def chat(client, model: str, system: str, history: list, question: str, tools: list, runner,
         max_steps: int = 6, max_tokens: int = 1500):
    """Tool-use loop. history = [{'role','content'(str)}...]. Returns (final_text, [tool names used])."""
    messages = [{"role": m["role"], "content": m["content"]} for m in history[-12:]] + [{"role": "user", "content": question}]
    used: list = []
    for _ in range(max_steps):
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system, tools=tools, messages=messages)
        if getattr(resp, "stop_reason", None) != "tool_use":
            return _text(resp), used
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if getattr(b, "type", "") == "tool_use":
                used.append(b.name)
                out = runner(b.name, dict(b.input or {}))
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:18000]})
        messages.append({"role": "user", "content": results})
    return "I reached my lookup limit before finishing - please ask a narrower question.", used


def safe_error(e: Exception) -> str:
    s = f"{type(e).__name__}: {e}"
    s = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", s)
    return s[:300]
