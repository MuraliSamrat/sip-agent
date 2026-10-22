"""All number-crunching is done here in Python, never by the LLM."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import data


def pct(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(100 * float(x), 2)


def cagr(series: pd.Series, years: float):
    end = series.index[-1]
    past = series[series.index <= end - pd.DateOffset(days=int(365.25 * years))]
    if past.empty:
        return None
    return (series.iloc[-1] / past.iloc[-1]) ** (1 / years) - 1


def max_drawdown(series: pd.Series) -> float:
    return float((series / series.cummax() - 1).min())


def ann_vol(series: pd.Series) -> float:
    return float(series.pct_change().dropna().std() * np.sqrt(252))


def rsi(close: pd.Series, n: int = 14) -> float:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    v = (100 - 100 / (1 + rs)).iloc[-1]
    return 100.0 if np.isnan(v) else float(v)


def atr(df: pd.DataFrame, n: int = 14) -> float:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def tick_round(price: float) -> float:
    """Round to NSE tick size so Kite/brokers accept the GTT price."""
    tick = 0.01 if price < 250 else (0.05 if price < 1000 else 0.10)
    return round(round(price / tick) * tick, 2)


# ------------------------------- funds ----------------------------------
def fund_report(code: int) -> dict:
    meta, s = data.mf_history(code)
    last3y = s[s.index >= s.index[-1] - pd.DateOffset(years=3)]
    days_old = (pd.Timestamp(dt.date.today()) - s.index[-1]).days
    return {
        "scheme_code": int(code),
        "name": meta.get("scheme_name"),
        "category": meta.get("scheme_category"),
        "fund_house": meta.get("fund_house"),
        "nav": round(float(s.iloc[-1]), 4),
        "nav_date": s.index[-1].strftime("%d-%b-%Y"),
        "stale": days_old > 10,      # fund may be merged/closed if NAV stops updating
        "return_1y_pct": pct(cagr(s, 1)),
        "cagr_3y_pct": pct(cagr(s, 3)),
        "cagr_5y_pct": pct(cagr(s, 5)),
        "cagr_10y_pct": pct(cagr(s, 10)),
        "volatility_3y_pct": pct(ann_vol(last3y)),
        "max_drawdown_3y_pct": pct(max_drawdown(last3y)),
    }


# ------------------------------- stocks ---------------------------------
def stock_report(ticker: str, stop_mult: float = 2.0, reward_risk: float = 2.0) -> dict:
    df = data.stock_history(ticker)
    c = df["Close"]
    price = float(c.iloc[-1])
    sma50 = float(c.rolling(50).mean().iloc[-1])
    sma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else float(c.mean())
    a = atr(df)
    stop = max(price - stop_mult * a, price * 0.85)          # never risk more than 15%
    target = price + reward_risk * (price - stop)
    last1y = c[c.index >= c.index[-1] - pd.DateOffset(years=1)]
    hi52, lo52 = float(last1y.max()), float(last1y.min())
    r = rsi(c)

    trend_up = price > sma200 and sma50 > sma200
    trend = "UP" if trend_up else ("DOWN" if price < sma200 else "SIDEWAYS")
    score = (2 if trend_up else (-2 if trend == "DOWN" else 0))
    score += 1 if 40 <= r <= 65 else (-1 if r > 72 else 0)
    score += 1 if price >= 0.85 * hi52 else 0
    signal = "BUY ZONE" if score >= 3 else ("WAIT" if score >= 1 else "AVOID")

    return {
        "ticker": ticker.upper(), "price": round(price, 2),
        "date": c.index[-1].strftime("%d-%b-%Y"),
        "sma50": round(sma50, 2), "sma200": round(sma200, 2),
        "rsi14": round(r, 1), "atr14": round(a, 2),
        "high_52w": round(hi52, 2), "low_52w": round(lo52, 2),
        "return_1y_pct": pct(price / float(last1y.iloc[0]) - 1),
        "stop_loss": tick_round(stop), "target": tick_round(target),
        "risk_pct": round(100 * (price - stop) / price, 2),
        "trend": trend, "score": score, "signal": signal,
    }


def market_overview() -> dict:
    """Nifty 50 health check. Used to explain the month, NOT to stop SIPs."""
    df = data.stock_history("^NSEI", "2y")
    c = df["Close"]
    price = float(c.iloc[-1])
    sma200 = float(c.rolling(200).mean().iloc[-1])
    hi = float(c[c.index >= c.index[-1] - pd.DateOffset(years=1)].max())
    dd = price / hi - 1
    if dd <= -0.20:
        mood = "Big fall (bear market). SIPs are buying cheap — keep going; top up only with spare cash."
    elif dd <= -0.10:
        mood = "Correction. Normal and healthy for long-term SIPs."
    elif price > sma200:
        mood = "Uptrend. Stay disciplined; don't increase risk because markets feel good."
    else:
        mood = "Sideways / weak. Nothing to change for a 30-year plan."
    return {"nifty": round(price, 2), "date": c.index[-1].strftime("%d-%b-%Y"),
            "sma200": round(sma200, 2), "below_52w_high_pct": pct(dd),
            "return_1y_pct": pct(price / float(c[c.index >= c.index[-1] - pd.DateOffset(years=1)].iloc[0]) - 1),
            "mood": mood}
