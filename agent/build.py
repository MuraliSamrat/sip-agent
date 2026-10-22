"""Assemble the agent: model + tools + middleware stack."""
from __future__ import annotations

import datetime as dt
import json
import os

from langchain.agents import create_agent
from langchain.agents.middleware import (HumanInTheLoopMiddleware, ModelCallLimitMiddleware,
                                         ModelFallbackMiddleware, ModelRetryMiddleware,
                                         SummarizationMiddleware, ToolRetryMiddleware, dynamic_prompt)
from langgraph.checkpoint.memory import InMemorySaver

from core import planner, settings
from .middleware import DecisionJournalMiddleware, fact_check, risk_guard
from .tools import ALL_TOOLS, READ_TOOLS

KEY_FOR = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "google_genai": "GOOGLE_API_KEY"}


def _has_key(model_id) -> bool:
    if not isinstance(model_id, str):
        return True
    provider = model_id.split(":", 1)[0]
    return bool(os.environ.get(KEY_FOR.get(provider, ""), ""))


@dynamic_prompt
def system_prompt(request) -> str:
    """Rebuilt every call so it always reflects current settings and date."""
    s = settings.load()
    today = dt.date.today()
    return f"""You are a careful long-term investment analyst for one Indian investor.
Today: {today:%d %b %Y}. Plan: SIP for {s['goal_years']} years starting {s['start_month']},
month #{planner.months_elapsed(s, today) + 1}, {planner.years_left(s, today)} years left.
This month's total: ₹{planner.monthly_amount(s, today):,.0f} (step-up {s['step_up_pct']}%/yr).
Of that, ₹{s['ai_bucket']['monthly']:,} (scaled with step-up) goes to an AI/agentic Indian-stock bucket.
Current target MF split: {json.dumps(planner.target_weights(s, today))}.
Broker: Zerodha (Kite for stocks, Coin for mutual funds).

Rules:
- Get EVERY number from tools. Never invent prices, NAVs, returns, analyst counts or targets.
- "Plan"/"what to buy this month" → call monthly_plan, then explain it simply with the checklist.
- SIPs are for decades: never suggest stopping or selling funds because of a market fall.
- Stocks in the AI bucket: buy as CNC (Delivery) and protect with a GTT OCO (stop-loss + target).
  Never suggest Bracket/Cover orders (intraday only) for holdings.
- Only call record_trade when the user says the order is ALREADY placed; ask for missing values
  (units, actual price/NAV, bucket). Use carry_cash for leftover AI money.
- Be honest about uncertainty. Mention once: educational tool, not SEBI-registered advice.
- Reply in the user's language if they write in Tamil or another language."""


def make_agent(model=None, checkpointer=None):
    s = settings.load()
    primary = model or s["model"]
    fallbacks = [m for m in s.get("fallback_models", []) if _has_key(m)] if model is None else []

    middleware = []
    if fallbacks:
        middleware.append(ModelFallbackMiddleware(*fallbacks))
    middleware += [
        ModelRetryMiddleware(max_retries=2),
        ToolRetryMiddleware(max_retries=2, tools=READ_TOOLS),
        SummarizationMiddleware(model=primary, trigger=("tokens", 12000), keep=("messages", 20)),
        ModelCallLimitMiddleware(run_limit=15, exit_behavior="end"),
        system_prompt,
        DecisionJournalMiddleware(),
        risk_guard,
        fact_check,
        HumanInTheLoopMiddleware(interrupt_on={
            "record_trade": {"allowed_decisions": ["approve", "edit", "reject"]},
            "carry_cash": {"allowed_decisions": ["approve", "edit", "reject"]},
            "update_setting": {"allowed_decisions": ["approve", "reject"]},
        }),
    ]
    return create_agent(model=primary, tools=ALL_TOOLS, middleware=middleware,
                        checkpointer=checkpointer or InMemorySaver())


def final_text(result) -> str:
    from langchain.messages import AIMessage
    from .middleware import _text
    for m in reversed(result["messages"]):
        if isinstance(m, AIMessage) and m.content and not m.tool_calls:
            return _text(m.content)
    return "(no answer)"


def pending_actions(result) -> list[dict]:
    """Actions waiting for human approval (empty list if none)."""
    intr = result.get("__interrupt__")
    if not intr:
        return []
    return intr[0].value.get("action_requests", [])
