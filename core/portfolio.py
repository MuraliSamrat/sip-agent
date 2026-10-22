"""SQLite storage: trades, carried cash, decision journal, monthly plans.

One file (data/portfolio.db) holds everything. Back it up — it is your
30-year history. app.py has a download/restore button.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import numpy as np
import pandas as pd

from . import data
from .settings import DATA_DIR

DB_PATH = DATA_DIR / "portfolio.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, asset_type TEXT, bucket TEXT,
  symbol TEXT, name TEXT, units REAL, price REAL, amount REAL,
  stop_loss REAL, target REAL, note TEXT);
CREATE TABLE IF NOT EXISTS cash(id INTEGER PRIMARY KEY, ts TEXT, bucket TEXT, amount REAL, note TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, title TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS plans(month TEXT PRIMARY KEY, ts TEXT, plan_json TEXT);
"""


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


# ------------------------------- trades ---------------------------------
def record_trade(kind, asset_type, bucket, symbol, units, price,
                 name="", stop_loss=None, target=None, note="") -> dict:
    kind, asset_type = kind.upper(), asset_type.upper()
    if kind not in ("BUY", "SELL") or asset_type not in ("MF", "STOCK"):
        raise ValueError("kind must be BUY/SELL and asset_type MF/STOCK")
    if units <= 0 or price <= 0:
        raise ValueError("units and price must be positive")
    if kind == "SELL":
        h = holdings()
        have = h.loc[h["symbol"] == str(symbol), "units"].sum() if not h.empty else 0
        if units > have + 1e-6:
            raise ValueError(f"You only hold {have} units of {symbol}")
    amount = round(units * price, 2)
    with db() as con:
        con.execute("INSERT INTO trades(ts,kind,asset_type,bucket,symbol,name,units,price,amount,"
                    "stop_loss,target,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (now(), kind, asset_type, bucket, str(symbol), name, units, price, amount,
                     stop_loss or None, target or None, note))
    return {"kind": kind, "symbol": str(symbol), "units": units, "price": price, "amount": amount}


def trades() -> pd.DataFrame:
    with db() as con:
        return pd.read_sql("SELECT * FROM trades ORDER BY ts", con)


def holdings() -> pd.DataFrame:
    t = trades()
    if t.empty:
        return t
    rows = []
    for (atype, bucket, sym), g in t.groupby(["asset_type", "bucket", "symbol"]):
        buys, sells = g[g.kind == "BUY"], g[g.kind == "SELL"]
        units = buys.units.sum() - sells.units.sum()
        if units <= 1e-6:
            continue
        avg = buys.amount.sum() / buys.units.sum()
        last_buy = buys.iloc[-1]
        rows.append({"asset_type": atype, "bucket": bucket, "symbol": sym, "name": last_buy["name"],
                     "units": round(units, 4), "avg_cost": round(avg, 4),
                     "invested": round(units * avg, 2),
                     "stop_loss": last_buy["stop_loss"], "target": last_buy["target"]})
    return pd.DataFrame(rows)


def valued_holdings(ai_style: str = "swing") -> pd.DataFrame:
    h = holdings()
    if h.empty:
        return h
    prices, alerts = [], []
    for _, r in h.iterrows():
        alert = None
        try:
            if r.asset_type == "MF":
                px = data.mf_latest_nav(int(r.symbol))[0]
            else:
                px = data.last_price(r.symbol)
                if ai_style == "swing":
                    if r.stop_loss and px <= r.stop_loss:
                        alert = "STOP-LOSS HIT → sell (GTT should have done it)"
                    elif r.target and px >= r.target:
                        alert = "TARGET HIT → book profit"
                else:
                    from .analytics import stock_report
                    if stock_report(r.symbol)["trend"] == "DOWN":
                        alert = "Trend broke DOWN → review this holding"
        except Exception as e:
            px, alert = np.nan, f"price error: {e}"
        prices.append(px)
        alerts.append(alert)
    h["live_price"] = prices
    h["value"] = (h["units"] * h["live_price"]).round(2)
    h["pnl"] = (h["value"] - h["invested"]).round(2)
    h["pnl_pct"] = (100 * h["pnl"] / h["invested"]).round(2)
    h["alert"] = alerts
    return h


# -------------------------------- cash ----------------------------------
def add_cash(bucket: str, amount: float, note: str = "") -> float:
    with db() as con:
        con.execute("INSERT INTO cash(ts,bucket,amount,note) VALUES(?,?,?,?)", (now(), bucket, amount, note))
    return cash_balance(bucket)


def cash_balance(bucket: str = "ai") -> float:
    with db() as con:
        return float(con.execute("SELECT COALESCE(SUM(amount),0) FROM cash WHERE bucket=?",
                                 (bucket,)).fetchone()[0])


# ------------------------------- journal --------------------------------
def journal_add(kind: str, title: str, detail="") -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    with db() as con:
        con.execute("INSERT INTO journal(ts,kind,title,detail) VALUES(?,?,?,?)",
                    (now(), kind, title[:200], detail[:20000]))


def journal(limit: int = 50, kind: str | None = None) -> pd.DataFrame:
    q = "SELECT ts,kind,title,detail FROM journal"
    args: tuple = ()
    if kind:
        q += " WHERE kind=?"
        args = (kind,)
    q += " ORDER BY id DESC LIMIT ?"
    with db() as con:
        return pd.read_sql(q, con, params=args + (limit,))


# -------------------------------- plans ---------------------------------
def save_plan(plan: dict) -> None:
    with db() as con:
        con.execute("INSERT OR REPLACE INTO plans(month,ts,plan_json) VALUES(?,?,?)",
                    (plan["month_key"], now(), json.dumps(plan, default=str)))


def get_plan(month_key: str) -> dict | None:
    with db() as con:
        r = con.execute("SELECT plan_json FROM plans WHERE month=?", (month_key,)).fetchone()
    return json.loads(r[0]) if r else None
