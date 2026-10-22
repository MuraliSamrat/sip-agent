"""Custom middleware (guardrails + documentation).

Order in build.py (outer → inner for tool calls):
  DecisionJournal → RiskGuard → (tool)
after_model hooks: FactCheck, HumanInTheLoop
"""
from __future__ import annotations

import json
import re

from langchain.agents.middleware import AgentMiddleware, AgentState, after_model, wrap_tool_call
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from core import portfolio, settings

DOCUMENTED_TOOLS = {"monthly_plan", "record_trade", "carry_cash", "update_setting"}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


# ------------------------- documentation middleware ---------------------
class DecisionJournalMiddleware(AgentMiddleware):
    """Writes an audit trail to the SQLite journal:
    - every important tool call (args + result, including blocked ones)
    - every final answer with the question that produced it.
    Over 30 years this is your "why did I buy that?" record."""

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        name = request.tool_call["name"]
        if name in DOCUMENTED_TOOLS:
            content = _text(getattr(result, "content", result))
            portfolio.journal_add("tool", f"{name} {'BLOCKED' if 'BLOCKED' in content else 'ran'}",
                                  {"args": request.tool_call.get("args"), "result": content[:3000]})
        return result

    def after_agent(self, state, runtime):
        msgs = state["messages"]
        q = next((m for m in reversed(msgs) if isinstance(m, HumanMessage)), None)
        a = next((m for m in reversed(msgs) if isinstance(m, AIMessage) and not m.tool_calls), None)
        if q and a:
            portfolio.journal_add("answer", _text(q.content)[:150], _text(a.content))
        return None


# ------------------------------ risk guard ------------------------------
@wrap_tool_call
def risk_guard(request, handler):
    """Hard rules the LLM cannot talk its way around."""
    call = request.tool_call
    a = call.get("args", {})
    problem = None
    if call["name"] == "record_trade" and str(a.get("kind", "")).upper() == "BUY":
        s = settings.load()
        amount = float(a.get("units", 0)) * float(a.get("price", 0))
        from core.planner import monthly_amount
        import datetime as dt
        month_money = monthly_amount(s, dt.date.today()) + portfolio.cash_balance("ai")
        if amount > 3 * month_money:
            problem = f"₹{amount:,.0f} is far more than your monthly money (₹{month_money:,.0f}). Check units/price."
        elif str(a.get("bucket", "")).lower() == "ai":
            h = portfolio.holdings()
            owned = (h["invested"].sum() if not h.empty else 0) + amount
            already = h.loc[h["symbol"] == a.get("symbol"), "invested"].sum() if not h.empty else 0
            cap = s["ai_bucket"]["max_single_stock_pct"]
            if owned > 3 * month_money and (already + amount) > cap * owned:
                problem = (f"{a.get('symbol')} would be {100*(already+amount)/owned:.1f}% of your portfolio "
                           f"(limit {cap:.0%}).")
    if call["name"] == "update_setting":
        k, v = a.get("key", ""), str(a.get("value", ""))
        try:
            if k == "ai_bucket.max_pct_of_portfolio" and float(v) > 0.25:
                problem = "AI bucket above 25% of the portfolio is too concentrated for a 30-year plan."
            if k == "monthly_budget" and float(v) <= 0:
                problem = "Monthly budget must be positive."
        except ValueError:
            problem = f"'{v}' is not a number."
    if problem:
        return ToolMessage(content=f"BLOCKED by risk guard: {problem}", tool_call_id=call["id"])
    return handler(request)


# ------------------------------ fact check ------------------------------
_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+\.\d+|\d{3,}")


def _nums(text: str) -> set[float]:
    return {float(x.replace(",", "")) for x in _NUM.findall(text or "")}


@after_model
def fact_check(state: AgentState, runtime):
    """Flag numbers in the final answer that no tool (or the user) provided."""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or last.tool_calls:
        return None
    text = _text(last.content)
    s = settings.load()
    known = _nums(json.dumps(s))
    for m in state["messages"][:-1]:
        if isinstance(m, (ToolMessage, HumanMessage)):
            known |= _nums(_text(m.content))
    unverified = sorted(n for n in _nums(text)
                        if n >= 100 and not (2000 <= n <= 2100)        # years are fine
                        and not any(abs(n - k) <= max(1, 0.01 * k) for k in known))
    if unverified:
        flagged = text + ("\n\n⚠️ Fact-check: these numbers did not come from live data — "
                          f"treat as unverified: {unverified[:8]}")
        return {"messages": [AIMessage(content=flagged, id=last.id)]}
    return None
