"""Monthly plan for a 30-year SIP journey.

What "adjusting the portfolio every month" means here (on purpose, conservative):
  1. Step-up: monthly amount rises step_up_pct once a year.
  2. Glide path: in the last N years, money shifts gradually from equity to debt.
  3. Drift rebalancing: if a bucket is more than drift_band_pct off target, this
     month's money is steered toward the underweight bucket (no selling = no tax).
  4. AI bucket: small monthly amount into Indian AI/agent companies, only when a
     stock is in a buy zone; otherwise a cheap IT ETF or cash carried forward.
  5. Market mood is reported but never stops the SIP.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from . import analytics, data, portfolio
from .settings import DATA_DIR, load

REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
BUCKETS = ("index", "flexi", "debt")


# ------------------------------ timeline --------------------------------
def months_elapsed(s: dict, today: dt.date) -> int:
    y, m = map(int, s["start_month"].split("-"))
    return max(0, (today.year - y) * 12 + today.month - m)


def monthly_amount(s: dict, today: dt.date) -> float:
    years = months_elapsed(s, today) // 12
    amt = s["monthly_budget"] * (1 + s["step_up_pct"] / 100) ** years
    return float(round(amt / 100) * 100)


def years_left(s: dict, today: dt.date) -> float:
    return round(s["goal_years"] - months_elapsed(s, today) / 12, 2)


def target_weights(s: dict, today: dt.date) -> dict:
    gp = s["glide_path"]
    yl = years_left(s, today)
    debt = 0.0 if yl >= gp["start_years_left"] else \
        min(gp["max_debt"], gp["max_debt"] * (gp["start_years_left"] - yl) / gp["start_years_left"])
    eq = 1 - debt
    tot = sum(s["equity_split"].values())
    return {"index": round(eq * s["equity_split"]["index"] / tot, 4),
            "flexi": round(eq * s["equity_split"]["flexi"] / tot, 4),
            "debt": round(debt, 4)}


def _round100(x: float) -> int:
    return int(round(x / 100) * 100)


# ------------------------------- plan -----------------------------------
def build_plan(s: dict | None = None, today: dt.date | None = None) -> dict:
    s = s or load()
    today = today or dt.date.today()
    total = monthly_amount(s, today)
    scale = total / s["monthly_budget"]
    ai_cfg = s["ai_bucket"]
    elapsed = months_elapsed(s, today)

    plan = {"month_key": today.strftime("%Y-%m"), "month": today.strftime("%B %Y"),
            "monthly_total": total, "month_number": elapsed + 1,
            "years_left": years_left(s, today), "notes": [], "warnings": []}
    if elapsed and elapsed % 12 == 0:
        plan["notes"].append(f"🎉 Step-up month: your SIP total is now ₹{total:,.0f}. "
                             "Update SIP amounts in Coin and do the yearly review (README).")

    try:
        plan["market"] = analytics.market_overview()
    except Exception as e:
        plan["market"] = {"error": str(e)}

    # ---- current portfolio
    vh = portfolio.valued_holdings(ai_cfg["style"])
    ai_cash = portfolio.cash_balance("ai")
    port_total = (vh["value"].fillna(vh["invested"]).sum() if not vh.empty else 0) + ai_cash
    ai_value = (vh.loc[vh.bucket == "ai", "value"].fillna(0).sum() if not vh.empty else 0) + ai_cash
    plan["portfolio_value"] = round(port_total, 2)
    if not vh.empty:
        for _, r in vh[vh["alert"].notna()].iterrows():
            plan["warnings"].append(f"{r.symbol}: {r.alert}")

    # ---- AI bucket size
    ai_amt = _round100(ai_cfg["monthly"] * scale) if ai_cfg["monthly"] > 0 else 0
    big_enough = port_total > 3 * total
    if ai_amt and big_enough and ai_value > ai_cfg["max_pct_of_portfolio"] * port_total:
        plan["notes"].append(f"AI bucket is {100*ai_value/port_total:.0f}% of portfolio "
                             f"(limit {ai_cfg['max_pct_of_portfolio']:.0%}) — this month its ₹{ai_amt:,} goes to the index fund.")
        ai_amt = 0
    mf_money = total - ai_amt

    # ---- MF split: target, then drift steering
    w = target_weights(s, today)
    plan["target_weights"] = w
    amounts = {b: w[b] * mf_money for b in BUCKETS}
    mf_vals = {b: (vh.loc[(vh.asset_type == "MF") & (vh.bucket == b), "value"].fillna(0).sum()
                   if not vh.empty else 0.0) for b in BUCKETS}
    mf_total = sum(mf_vals.values())
    drift = {}
    if mf_total > 0:
        drift = {b: round(100 * (mf_vals[b] / mf_total - w[b]), 1) for b in BUCKETS}
        if mf_total >= 2 * mf_money and max(abs(d) for d in drift.values()) > s["drift_band_pct"]:
            after = mf_total + mf_money
            gaps = {b: max(0.0, w[b] * after - mf_vals[b]) for b in BUCKETS}
            if sum(gaps.values()) > 0:
                amounts = {b: mf_money * gaps[b] / sum(gaps.values()) for b in BUCKETS}
                plan["notes"].append("Rebalancing: a bucket drifted off target, so this month's money is "
                                     "steered to the underweight fund(s). Change SIP amounts only for this month "
                                     "(or add a one-time lump sum) — no selling needed.")
    plan["drift_pts"] = drift

    rounded = {b: _round100(a) for b, a in amounts.items()}
    rounded["index"] += _round100(mf_money) - sum(rounded.values())   # keep the total exact
    for b in ("flexi", "debt"):                                          # respect fund minimum SIP
        if 0 < rounded[b] < s["funds"][b]["min_sip"]:
            rounded["index"] += rounded[b]
            rounded[b] = 0

    sips = []
    for b in BUCKETS:
        if rounded[b] <= 0:
            continue
        item = {"bucket": b, "amount": rounded[b]}
        try:
            code = data.resolve_fund(s["funds"][b])
            rep = analytics.fund_report(code)
            item.update(scheme_code=code, name=rep["name"], nav=rep["nav"], nav_date=rep["nav_date"],
                        approx_units=round(rounded[b] / rep["nav"], 3),
                        cagr_3y_pct=rep["cagr_3y_pct"], cagr_5y_pct=rep["cagr_5y_pct"],
                        max_drawdown_3y_pct=rep["max_drawdown_3y_pct"])
            if rep["stale"]:
                plan["warnings"].append(f"{rep['name']}: NAV not updated since {rep['nav_date']} — "
                                        "fund may be merged/closed. Pick a replacement in Settings.")
        except Exception as e:
            item["error"] = str(e)
            plan["warnings"].append(f"{b} fund data error: {e}")
        sips.append(item)
    plan["sips"] = sips

    plan["ai"] = _ai_pick(s, ai_amt, ai_cash, vh, port_total, total) if ai_amt or ai_cash else \
        {"money": 0, "pick": None, "carry": 0, "scan": []}
    plan["checklist"] = _checklist(plan, s)
    return plan


def _ai_pick(s, ai_amt, ai_cash, vh, port_total, total) -> dict:
    cfg = s["ai_bucket"]
    money = ai_amt + ai_cash
    scans = []
    for t in cfg["watchlist"]:
        try:
            scans.append(analytics.stock_report(t, s["stop_atr_mult"], s["reward_risk"]))
        except Exception as e:
            scans.append({"ticker": t, "error": str(e)})
    ok = [x for x in scans if "error" not in x]
    ranked = sorted([x for x in ok if x["signal"] == "BUY ZONE"],
                    key=lambda x: (x["score"], x["return_1y_pct"] or 0), reverse=True)
    limit = cfg["max_single_stock_pct"] * (port_total + total) if port_total > 3 * total else money

    pick = None
    for x in ranked:
        already = vh.loc[vh.symbol == x["ticker"], "invested"].sum() if not vh.empty else 0
        qty = int(money // x["price"])
        if qty >= 1 and already + qty * x["price"] <= max(limit, x["price"]):
            pick = {"type": "STOCK", "ticker": x["ticker"], "qty": qty, "price": x["price"],
                    "amount": round(qty * x["price"], 2), "stop_loss": x["stop_loss"],
                    "target": x["target"], "risk_pct": x["risk_pct"], "trend": x["trend"],
                    "rsi14": x["rsi14"], "why": f"score {x['score']}, trend {x['trend']}, RSI {x['rsi14']}"}
            break
    if not pick and cfg.get("fallback_etf"):
        try:
            e = analytics.stock_report(cfg["fallback_etf"], s["stop_atr_mult"], s["reward_risk"])
            qty = int(money // e["price"])
            if e["signal"] != "AVOID" and qty >= 1:
                pick = {"type": "ETF", "ticker": e["ticker"], "qty": qty, "price": e["price"],
                        "amount": round(qty * e["price"], 2), "stop_loss": None, "target": None,
                        "why": "No AI stock in a buy zone/affordable — cheap IT ETF keeps you invested in the theme."}
        except Exception:
            pass
    spent = pick["amount"] if pick else 0
    return {"money": round(money, 2), "new_this_month": ai_amt, "carried_in": round(ai_cash, 2),
            "pick": pick, "carry": round(money - spent, 2),
            "scan": [{k: x.get(k) for k in ("ticker", "price", "signal", "trend", "rsi14", "error")} for x in scans]}


def _checklist(plan: dict, s: dict) -> list[str]:
    steps = []
    for it in plan["sips"]:
        if "name" in it:
            steps.append(f"Coin: SIP ₹{it['amount']:,} → {it['name']} (should already be auto-debited).")
    p = plan["ai"].get("pick")
    if p:
        steps.append(f"Kite: BUY {p['qty']} × {p['ticker'].replace('.NS','')} as CNC (Delivery), limit ≈ ₹{p['price']:,}.")
        if p.get("stop_loss") and s["ai_bucket"]["style"] == "swing":
            steps.append(f"Kite: after it fills, create GTT OCO → stop ₹{p['stop_loss']:,} / target ₹{p['target']:,}.")
    delta = round(plan["ai"].get("carry", 0) - plan["ai"].get("carried_in", 0), 2)
    if delta:
        steps.append(f"Agent: record carried AI cash {'+' if delta > 0 else '−'}₹{abs(delta):,.0f} "
                     f"(balance becomes ₹{plan['ai'].get('carry', 0):,.0f}).")
    steps.append("Agent: record what you actually bought (real NAV/price) so tracking stays accurate.")
    return steps


# ---------------------------- documentation -----------------------------
def plan_markdown(p: dict) -> str:
    L = [f"# Investment plan — {p['month']}", "",
         f"- Month #{p['month_number']} of the plan · {p['years_left']} years left",
         f"- This month's total: **₹{p['monthly_total']:,.0f}** · Portfolio value: ₹{p.get('portfolio_value', 0):,.0f}"]
    m = p.get("market", {})
    if "nifty" in m:
        L += ["", "## Market", f"Nifty 50 {m['nifty']:,} ({m['date']}), {m['below_52w_high_pct']}% from 52-week high, "
              f"1-year {m['return_1y_pct']}%.", f"> {m['mood']}"]
    L += ["", "## Mutual fund SIPs", "| Bucket | Amount | Fund | NAV | 3y CAGR | Worst fall (3y) |", "|---|---|---|---|---|---|"]
    for it in p["sips"]:
        L.append(f"| {it['bucket']} | ₹{it['amount']:,} | {it.get('name', it.get('error'))} | {it.get('nav', '')} | "
                 f"{it.get('cagr_3y_pct', '')}% | {it.get('max_drawdown_3y_pct', '')}% |")
    w = p["target_weights"]
    L.append(f"\nTarget split of MF money: index {w['index']:.0%}, flexi {w['flexi']:.0%}, debt {w['debt']:.0%}.")
    if p.get("drift_pts"):
        L.append("Drift vs target (pts): " + ", ".join(f"{k} {v:+}" for k, v in p["drift_pts"].items()))
    a = p["ai"]
    L += ["", "## AI / agentic bucket", f"Money available: ₹{a['money']:,.0f} (new ₹{a.get('new_this_month', 0):,} + carried ₹{a.get('carried_in', 0):,.0f})"]
    if a.get("pick"):
        k = a["pick"]
        L.append(f"**{k['type']}: buy {k['qty']} × {k['ticker']} @ ₹{k['price']:,} = ₹{k['amount']:,}**" +
                 (f" · stop ₹{k['stop_loss']:,} · target ₹{k['target']:,}" if k.get("stop_loss") else "") +
                 f"  \n_Why: {k['why']}_")
    else:
        L.append("No buy this month.")
    L.append(f"Carry forward: ₹{a.get('carry', 0):,.0f}")
    if a.get("scan"):
        L.append("Scan: " + ", ".join(f"{x['ticker'].replace('.NS','')} {x.get('signal') or 'n/a'}" for x in a["scan"]))
    if p["notes"]:
        L += ["", "## Notes"] + [f"- {n}" for n in p["notes"]]
    if p["warnings"]:
        L += ["", "## ⚠️ Warnings"] + [f"- {n}" for n in p["warnings"]]
    L += ["", "## Checklist"] + [f"- [ ] {c}" for c in p["checklist"]]
    L += ["", "_Educational tool, not SEBI-registered advice._"]
    return "\n".join(L)


def save_report(p: dict) -> str:
    path = REPORTS_DIR / f"{p['month_key']}.md"
    path.write_text(plan_markdown(p), encoding="utf-8")
    portfolio.save_plan(p)
    portfolio.journal_add("plan", f"Monthly plan {p['month']}", {
        "total": p["monthly_total"], "sips": [(i["bucket"], i["amount"]) for i in p["sips"]],
        "ai_pick": p["ai"].get("pick"), "warnings": p["warnings"]})
    return str(path)


# ----------------------------- projection -------------------------------
def projection(monthly: float, years: int, annual_return_pct: float, step_up_pct: float = 0) -> pd.DataFrame:
    r = (1 + annual_return_pct / 100) ** (1 / 12)
    value = invested = 0.0
    amt = monthly
    rows = []
    for y in range(1, years + 1):
        for _ in range(12):
            value = (value + amt) * r
            invested += amt
        rows.append({"year": y, "monthly_sip": round(amt), "invested": round(invested),
                     "value": round(value), "gain": round(value - invested)})
        amt *= 1 + step_up_pct / 100
    return pd.DataFrame(rows)
