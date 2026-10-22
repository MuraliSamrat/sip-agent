"""Market data with caching, retries and fallbacks.

Sources (all free, no API key):
  - MFapi.in        : mutual fund search + NAV history
  - AMFI NAVAll.txt : official latest NAVs (fallback if MFapi is down)
  - yfinance        : NSE stock / ETF / index prices (tickers end in .NS, index ^NSEI)

If a source ever shuts down, only this file needs changing.
"""
from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache

import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry

from .settings import DATA_DIR

MFAPI = "https://api.mfapi.in/mf"
AMFI_NAV_ALL = "https://www.amfiindia.com/spages/NAVAll.txt"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])))
_session.headers["User-Agent"] = "sip-agent/1.0"


def _cache_path(key: str):
    return CACHE_DIR / (hashlib.md5(key.encode()).hexdigest() + ".json")


def _get(url: str, params: dict | None = None, ttl: int = 6 * 3600, as_json: bool = True):
    key = url + json.dumps(params or {}, sort_keys=True)
    p = _cache_path(key)
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        return json.loads(p.read_text())
    try:
        r = _session.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json() if as_json else r.text
        p.write_text(json.dumps(data))
        return data
    except Exception:
        if p.exists():                       # stale cache beats no data
            return json.loads(p.read_text())
        raise


# ----------------------------- mutual funds -----------------------------
def mf_search(query: str) -> list[dict]:
    return _get(f"{MFAPI}/search", {"q": query}, ttl=7 * 86400)


def mf_pick_direct_growth(query: str) -> dict:
    res = mf_search(query)
    good = [x for x in res if "direct" in x["schemeName"].lower()
            and "growth" in x["schemeName"].lower()
            and "idcw" not in x["schemeName"].lower()]
    if not (good or res):
        raise ValueError(f"No fund found for '{query}'. It may have been renamed or closed.")
    return (good or res)[0]


def resolve_fund(cfg: dict) -> int:
    """Scheme code from settings: explicit code wins, else search by name."""
    if cfg.get("scheme_code"):
        return int(cfg["scheme_code"])
    return int(mf_pick_direct_growth(cfg["query"])["schemeCode"])


def mf_history(code: int) -> tuple[dict, pd.Series]:
    j = _get(f"{MFAPI}/{code}", ttl=12 * 3600)
    df = pd.DataFrame(j.get("data", []))
    if df.empty:
        raise ValueError(f"No NAV history for scheme {code}")
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    s = df.dropna().set_index("date")["nav"].sort_index()
    return j.get("meta", {}), s


def _amfi_latest(code: int):
    text = _get(AMFI_NAV_ALL, ttl=12 * 3600, as_json=False)
    for line in text.splitlines():
        parts = line.split(";")
        if len(parts) >= 6 and parts[0].strip() == str(code):
            return float(parts[4]), parts[5].strip()
    raise ValueError(f"Scheme {code} not in AMFI list")


def mf_latest_nav(code: int) -> tuple[float, str]:
    try:
        _, s = mf_history(code)
        return float(s.iloc[-1]), s.index[-1].strftime("%d-%b-%Y")
    except Exception:
        return _amfi_latest(code)


# ------------------------------- stocks ---------------------------------
@lru_cache(maxsize=256)
def _yf(ticker: str, period: str, hour_bucket: int) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data for {ticker}. NSE tickers need .NS (e.g. INFY.NS).")
    return df


def stock_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    return _yf(ticker.upper(), period, int(time.time() // 3600))


def last_price(ticker: str) -> float:
    return float(stock_history(ticker, "5d")["Close"].iloc[-1])
