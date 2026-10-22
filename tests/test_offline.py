"""Offline tests: fake market data + fake LLM, no internet or API key needed.

Run:  python -m pytest -q      (or)   python tests/test_offline.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

os.environ["SIP_AGENT_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core import data, planner, portfolio, settings

RNG = np.random.default_rng(7)
_IDX = pd.bdate_range(end=dt.date.today(), periods=600)


def _fake_stock(ticker, period="2y"):
    base = {"ITBEES.NS": 40, "^NSEI": 24000}.get(ticker, 300 + 50 * (hash(ticker) % 20))
    drift = 0.0015 if ticker in ("HAPPSTMNDS.NS", "SAKSOFT.NS") else 0.0
    c = pd.Series(base * np.exp(np.cumsum(RNG.normal(drift, 0.01, len(_IDX)))), _IDX)
    return pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99})


_NAV = pd.Series(10 * np.exp(np.cumsum(RNG.normal(0.0004, 0.008, 3000))),
                 pd.bdate_range(end=dt.date.today(), periods=3000))
data.stock_history = _fake_stock
data.last_price = lambda t: float(_fake_stock(t)["Close"].iloc[-1])
data.mf_history = lambda code: ({"scheme_name": f"Fund {code} Direct Growth", "scheme_category": "Equity"}, _NAV)
data.mf_latest_nav = lambda code: (float(_NAV.iloc[-1]), "today")
data.mf_search = lambda q: [{"schemeCode": abs(hash(q)) % 100000, "schemeName": q + " - Direct Plan - Growth"}]


def test_glide_path_and_stepup():
    s = settings.load()
    s["start_month"] = "2026-01"
    assert planner.target_weights(s, dt.date(2026, 6, 1))["debt"] == 0
    late = planner.target_weights(s, dt.date(2054, 6, 1))           # ~1.6 years left
    assert 0.4 < late["debt"] <= 0.6
    assert planner.monthly_amount(s, dt.date(2027, 2, 1)) == 11000  # 10% step-up after a year


def test_plan_totals():
    p = planner.build_plan()
    total = sum(i["amount"] for i in p["sips"]) + p["ai"]["new_this_month"]
    assert total == p["monthly_total"]
    assert all(c for c in p["checklist"])
    path = planner.save_report(p)
    assert Path(path).exists()


def test_projection():
    df = planner.projection(10000, 30, 12)
    assert 300e5 < df.iloc[-1]["value"] < 320e5


def test_agent_flow():
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain.messages import AIMessage
    from langgraph.types import Command
    from agent.build import final_text, make_agent, pending_actions

    class Fake(GenericFakeChatModel):
        def bind_tools(self, tools, **kw):
            return self

    msgs = iter([
        AIMessage(content="", tool_calls=[{"name": "record_trade", "id": "1", "args": {
            "kind": "BUY", "asset_type": "STOCK", "bucket": "ai", "symbol": "INFY.NS", "units": 1, "price": 900}}]),
        AIMessage(content="Saved. It will reach 7777 soon."),
        AIMessage(content="", tool_calls=[{"name": "record_trade", "id": "2", "args": {
            "kind": "BUY", "asset_type": "STOCK", "bucket": "ai", "symbol": "INFY.NS", "units": 500, "price": 900}}]),
        AIMessage(content="That was blocked."),
    ])
    ag = make_agent(model=Fake(messages=msgs))
    cfg = {"configurable": {"thread_id": "t"}}
    r = ag.invoke({"messages": [{"role": "user", "content": "I bought 1 INFY.NS at 900"}]}, cfg)
    assert pending_actions(r)[0]["name"] == "record_trade"           # human-in-the-loop paused
    r = ag.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
    assert "Fact-check" in final_text(r)                              # 7777 flagged
    assert not portfolio.holdings().empty
    r = ag.invoke({"messages": [{"role": "user", "content": "buy 500 more"}]}, cfg)
    if pending_actions(r):
        r = ag.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
    tool_msgs = [m.content for m in r["messages"] if m.type == "tool"]
    assert "BLOCKED" in tool_msgs[-1]                                 # risk guard
    kinds = set(portfolio.journal(50)["kind"])
    assert {"tool", "trade", "answer"} <= kinds                       # documentation middleware


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
