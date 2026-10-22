"""All user-editable settings live in data/settings.json.

Defaults below are merged with the file, so new settings added in future
versions appear automatically without breaking old files.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SIP_AGENT_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS: dict = {
    "monthly_budget": 10000,          # ₹ per month in year 1
    "step_up_pct": 10,                # raise the monthly amount this % every year (0 = off)
    "start_month": dt.date.today().strftime("%Y-%m"),
    "goal_years": 30,

    # Mutual fund buckets. Weights are of the MF money (budget minus AI bucket).
    # Debt weight is decided automatically by the glide path (see planner.py).
    "equity_split": {"index": 0.65, "flexi": 0.35},
    "glide_path": {"start_years_left": 7, "max_debt": 0.60},
    "drift_band_pct": 5,              # only change SIP split if a bucket is >5 pts off target
    "funds": {
        "index": {"query": "Navi Nifty 50 Index Fund", "scheme_code": None, "min_sip": 100},
        "flexi": {"query": "Parag Parikh Flexi Cap Fund", "scheme_code": None, "min_sip": 1000},
        "debt":  {"query": "HDFC Corporate Bond Fund", "scheme_code": None, "min_sip": 100},
    },

    # Small satellite bucket: Indian companies building AI / agents
    "ai_bucket": {
        "monthly": 1000,              # ₹ per month (grows with step-up)
        "max_pct_of_portfolio": 0.15, # if bigger than this, money goes to index fund instead
        "max_single_stock_pct": 0.05, # one stock ≤ 5% of total portfolio
        "style": "swing",             # "swing" = GTT stop-loss/target, "hold" = long-term, review on trend break
        "fallback_etf": "ITBEES.NS",  # cheap Nifty IT ETF if no stock is in a buy zone
        "watchlist": [
            "INFY.NS", "HCLTECH.NS", "TCS.NS", "WIPRO.NS", "TECHM.NS", "LTIM.NS",
            "PERSISTENT.NS", "TATAELXSI.NS", "LTTS.NS", "HAPPSTMNDS.NS",
            "AFFLE.NS", "RATEGAIN.NS", "SAKSOFT.NS",
        ],
    },
    "stop_atr_mult": 2.0,
    "reward_risk": 2.0,

    # LLM. Fallbacks are used only if the first model fails AND its API key exists.
    "model": "openai:gpt-5-mini",
    "fallback_models": ["anthropic:claude-sonnet-5-5"],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except json.JSONDecodeError:
            data = {}
    s = _merge(DEFAULTS, data)
    if not SETTINGS_FILE.exists():
        save(s)
    return s


def save(s: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


def update(key: str, value) -> dict:
    """Update a dotted key, e.g. update('ai_bucket.monthly', 1500)."""
    s = load()
    node = s
    parts = key.split(".")
    for p in parts[:-1]:
        if p not in node or not isinstance(node[p], dict):
            raise KeyError(f"Unknown setting: {key}")
        node = node[p]
    if parts[-1] not in node:
        raise KeyError(f"Unknown setting: {key}")
    old = node[parts[-1]]
    if isinstance(old, list) and isinstance(value, str):
        value = [x.strip().upper() for x in value.split(",") if x.strip()]
    elif isinstance(old, bool):
        value = str(value).lower() in ("1", "true", "yes", "on")
    elif isinstance(old, int) and not isinstance(value, bool):
        value = int(float(value))
    elif isinstance(old, float):
        value = float(value)
    node[parts[-1]] = value
    save(s)
    return s
