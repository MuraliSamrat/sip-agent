# CLAUDE.md — guide for Claude Code

Personal 30-year SIP + small AI-stock investing assistant for an Indian investor
(Zerodha: Kite for stocks, Coin for mutual funds). LangChain 1.x agent + Streamlit UI.
It NEVER places orders; the user trades manually and records trades here.

## Run
- Install: `pip install -r requirements.txt`
- App: `streamlit run app.py`
- Plan without AI: `python cli.py plan` · Terminal chat: `python cli.py chat` · Backup: `python cli.py backup`
- Tests (offline, no keys): `python -m pytest -q` or `python tests/test_offline.py` — run after every change.

## Layout
- `core/settings.py` — defaults + `data/settings.json` (merge-on-load, dotted `update()`)
- `core/data.py` — MFapi.in, AMFI NAVAll fallback, yfinance (`.NS`, `^NSEI`); disk cache in `data/cache`
- `core/analytics.py` — CAGR, drawdown, RSI, ATR, tick-rounded GTT prices, market mood
- `core/portfolio.py` — SQLite `data/portfolio.db`: trades, cash, journal, plans
- `core/planner.py` — monthly plan: step-up, glide path to debt, drift rebalancing, AI bucket pick, markdown report, projection
- `agent/tools.py` — LLM tools (READ_TOOLS, WRITE_TOOLS)
- `agent/middleware.py` — DecisionJournalMiddleware (documentation/audit), risk_guard, fact_check
- `agent/build.py` — create_agent + middleware stack (fallback, retries, summarization, call limit, dynamic prompt, HITL)
- `app.py` — Streamlit tabs; `cli.py` — terminal

## Rules for changes
- All numbers come from Python tools; the LLM must not compute or invent figures.
- Write tools (`record_trade`, `carry_cash`, `update_setting`) must stay behind HumanInTheLoopMiddleware.
- Never add automatic order placement or broker API trading.
- Keep the user's `data/` folder backward compatible (new settings go in DEFAULTS; DB changes via `ALTER TABLE ... ADD COLUMN`).
- Stocks: CNC delivery + GTT OCO. Never suggest Bracket/Cover orders for holdings.
- If a data source breaks, fix it inside `core/data.py` only.

## Yearly maintenance checklist (ask the user)
1. Update packages: `pip install -U -r requirements.txt`, run tests.
2. Check model names in Settings still work (OpenAI/Anthropic rename models often).
3. Check each fund's NAV is not stale (plan shows a warning); replace merged/closed funds.
4. Review AI watchlist tickers (delisted/renamed companies).
5. Back up `data/portfolio.db`.
