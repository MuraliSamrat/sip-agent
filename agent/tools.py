"""Tools the LLM can call. Every number it reports must come from one of these."""
from __future__ import annotations

import json

from langchain.tools import tool

from core import analytics, data, planner, portfolio, settings


def _j(x) -> str:
    return json.dumps(x, default=str)


@tool
def monthly_plan() -> str:
    """Build THIS month's plan: SIP amount per fund (with step-up, glide path and rebalancing),
    the AI/agentic stock pick with GTT stop-loss/target, market mood and a checklist.
    Also saves a markdown report and journal entry."""
    p = planner.build_plan()
    path = planner.save_report(p)
    p["report_saved_to"] = path
    return _j(p)


@tool
def market_overview() -> str:
    """Nifty 50 health: level, distance from 52-week high, 1-year return and what it means for SIPs."""
    return _j(analytics.market_overview())


@tool
def search_funds(query: str) -> str:
    """Search Indian mutual funds by name. Returns scheme codes; prefer 'Direct' + 'Growth' plans."""
    return _j(data.mf_search(query)[:12])


@tool
def analyze_fund(scheme_code: int) -> str:
    """NAV, 1/3/5/10-year returns, volatility, worst fall and staleness for a mutual fund scheme code."""
    return _j(analytics.fund_report(scheme_code))


@tool
def analyze_stock(ticker: str) -> str:
    """Technical check of an NSE stock/ETF (ticker with .NS, e.g. PERSISTENT.NS): trend, RSI,
    52-week range, tick-rounded stop-loss and target for a GTT OCO, and BUY ZONE / WAIT / AVOID."""
    s = settings.load()
    return _j(analytics.stock_report(ticker, s["stop_atr_mult"], s["reward_risk"]))


@tool
def scan_ai_stocks() -> str:
    """Scan the AI/agentic watchlist of Indian companies and rank them by signal."""
    s = settings.load()
    out = []
    for t in s["ai_bucket"]["watchlist"]:
        try:
            r = analytics.stock_report(t, s["stop_atr_mult"], s["reward_risk"])
            out.append({k: r[k] for k in ("ticker", "price", "signal", "trend", "rsi14", "return_1y_pct", "score")})
        except Exception as e:
            out.append({"ticker": t, "error": str(e)})
    out.sort(key=lambda x: x.get("score", -99), reverse=True)
    return _j(out)


@tool
def portfolio_status() -> str:
    """Holdings with live value, P&L, bucket split vs target, sell alerts, and carried AI cash."""
    s = settings.load()
    vh = portfolio.valued_holdings(s["ai_bucket"]["style"])
    if vh.empty:
        return _j({"holdings": [], "carried_ai_cash": portfolio.cash_balance("ai")})
    by_bucket = vh.groupby("bucket")[["invested", "value"]].sum().round(2).to_dict("index")
    return _j({"holdings": vh.to_dict("records"), "by_bucket": by_bucket,
               "total_invested": round(vh["invested"].sum(), 2),
               "total_value": round(vh["value"].fillna(0).sum(), 2),
               "total_pnl": round(vh["value"].fillna(0).sum() - vh["invested"].sum(), 2),
               "carried_ai_cash": portfolio.cash_balance("ai")})


@tool
def long_term_projection(years: int = 30, annual_return_pct: float = 12.0) -> str:
    """Project future value of the user's SIP (current monthly amount and step-up) for N years
    at an assumed yearly return. Returns year-by-year invested vs value."""
    s = settings.load()
    df = planner.projection(s["monthly_budget"], years, annual_return_pct, s["step_up_pct"])
    rows = df.iloc[[i for i in range(len(df)) if (i + 1) % 5 == 0 or i == len(df) - 1]]
    return _j({"assumed_return_pct": annual_return_pct, "step_up_pct": s["step_up_pct"],
               "milestones": rows.to_dict("records")})


@tool
def read_journal(limit: int = 15, kind: str = "") -> str:
    """Read past decisions/plans/trades from the journal. kind: plan, trade, setting, answer, tool, or empty for all."""
    return portfolio.journal(limit, kind or None).to_json(orient="records")


@tool
def record_trade(kind: str, asset_type: str, bucket: str, symbol: str, units: float, price: float,
                 name: str = "", stop_loss: float = 0.0, target: float = 0.0, note: str = "") -> str:
    """Record a trade the user ALREADY placed on Kite/Coin.
    kind: BUY or SELL. asset_type: MF (symbol = scheme code) or STOCK (symbol = ticker like INFY.NS; ETFs too).
    bucket: index, flexi, debt (mutual funds) or ai (AI/agentic stocks and IT ETF).
    units: shares or MF units. price: price or NAV actually paid."""
    r = portfolio.record_trade(kind, asset_type, bucket.lower(), symbol, units, price, name,
                               stop_loss or None, target or None, note)
    portfolio.journal_add("trade", f"{r['kind']} {r['units']} {r['symbol']} @ {r['price']}", r)
    return f"Recorded {r['kind']} {r['units']} {r['symbol']} @ {r['price']} (₹{r['amount']:,.2f})."


@tool
def carry_cash(amount: float, note: str = "") -> str:
    """Add (positive) or use up (negative) AI-bucket cash carried to future months."""
    bal = portfolio.add_cash("ai", amount, note)
    portfolio.journal_add("cash", f"AI cash {amount:+,.2f}", {"balance": bal, "note": note})
    return f"Carried AI cash balance: ₹{bal:,.2f}"


@tool
def update_setting(key: str, value: str) -> str:
    """Change a setting by dotted key, e.g. 'monthly_budget'='12000', 'ai_bucket.monthly'='1500',
    'ai_bucket.watchlist'='INFY.NS,PERSISTENT.NS', 'funds.flexi.scheme_code'='122639'."""
    node = settings.load()
    for p in key.split("."):
        node = node.get(p) if isinstance(node, dict) else None
    settings.update(key, value)
    portfolio.journal_add("setting", f"{key} = {value}", {"key": key, "old": node, "new": value})
    return f"Updated {key} to {value}."


READ_TOOLS = [monthly_plan, market_overview, search_funds, analyze_fund, analyze_stock,
              scan_ai_stocks, portfolio_status, long_term_projection, read_journal]
WRITE_TOOLS = [record_trade, carry_cash, update_setting]
ALL_TOOLS = READ_TOOLS + WRITE_TOOLS
