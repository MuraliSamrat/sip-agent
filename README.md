# 📈 30-year SIP Agent

Your personal investing assistant for ₹10,000/month (rising 10% every year):

- **Mutual fund SIPs** — Nifty 50 index fund + flexi-cap fund, automatically shifting to a
  safer debt fund in the last 7 years (glide path).
- **Monthly adjustment** — if one fund drifts more than 5 points off target, that month's
  money is steered to the underweight fund. No selling, so no tax.
- **AI / agentic bucket** — ₹1,000/month into Indian companies building AI and agents
  (Infosys, HCLTech, Persistent, Tata Elxsi, Happiest Minds, RateGain…). Buys only stocks in a
  "buy zone", gives you the GTT stop-loss and target, or uses a cheap IT ETF, or carries the cash forward.
- **AI agent with guardrails (LangChain 1.x middleware)**
  - Human-in-the-loop: asks you before saving any trade, cash entry or setting
  - Risk guard: blocks oversized or over-concentrated trades
  - Fact check: flags any number the AI didn't get from live data
  - Decision journal: documents every plan, trade and answer, so you have a full history
  - Model fallback, retries, conversation summarization, call limits
- **Monthly reports** saved as markdown in `data/reports/`.

It never places orders. You buy on Kite/Coin, then record it here.

---

## Setup (Windows, one time)

1. Install **Python 3.11+** from python.org (tick "Add Python to PATH").
2. Unzip this folder, e.g. to `C:\sip_agent`.
3. Open a terminal in that folder and run:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Copy `.streamlit\secrets.toml.example` to `.streamlit\secrets.toml` and paste your OpenAI key.
5. Start the app:
   ```
   streamlit run app.py
   ```
   It opens in your browser at http://localhost:8501.

Mac/Linux: use `source .venv/bin/activate` instead of the Windows activate line.

### Using it inside Claude Code
Open this folder in Claude Code. `CLAUDE.md` tells Claude how the project works, so you can ask
things like "run the tests", "add Fractal Analytics to my watchlist", or "the fund data is failing, fix it".

---

## Every month (about 15 minutes, on SIP day)

1. **📅 This month** tab → *Build this month's plan*.
2. SIPs run automatically in Coin. Only change amounts if the plan says "Rebalancing" or "Step-up month".
3. If there's an AI pick: buy it on Kite as **CNC (Delivery)**. Once it fills, create a **GTT OCO**
   with the stop-loss and target shown.
4. Record what you actually bought (Portfolio tab form, or tell the agent, e.g.
   "I bought 2 RATEGAIN.NS at 419").
5. Record carried AI cash if the checklist says so.
6. **⚙️ Settings → Download portfolio.db** (your backup).

## Every year (step-up month)
- Raise your Coin SIP amounts to the new total shown in the plan.
- Follow the yearly checklist in `CLAUDE.md`: update packages, check model names, replace closed funds,
  review the watchlist.

---

## Your data
Everything is in the `data/` folder: `settings.json`, `portfolio.db` (trades + journal) and `reports/`.
**Back it up.** It's your 30-year history.

> Hosting on Streamlit Community Cloud works, but its disk resets on every redeploy.
> Download the backup monthly and restore it after a reset, or simply run the app on your own PC.

## Change things
Use the **Settings** tab: budget, step-up %, start month, funds (name or exact scheme code),
AI amount, watchlist, swing vs hold style, LLM model.

## Tests
```
python -m pytest -q
```
Runs fully offline with fake data and a fake AI.

---
_Educational tool, not SEBI-registered investment advice. Markets can fall a lot; past returns
don't guarantee future ones._
