"""Streamlit app:  streamlit run app.py"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import uuid

import pandas as pd
import streamlit as st

from core import planner, portfolio, settings

st.set_page_config(page_title="SIP Agent", page_icon="📈", layout="wide")

# API keys from .streamlit/secrets.toml (or Streamlit Cloud secrets)
try:
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        if k in st.secrets and not os.environ.get(k):
            os.environ[k] = st.secrets[k]
except Exception:
    pass

S = settings.load()
today = dt.date.today()

# ------------------------------ header ----------------------------------
st.title("📈 30-year SIP Agent")
c1, c2, c3, c4 = st.columns(4)
c1.metric("This month's SIP", f"₹{planner.monthly_amount(S, today):,.0f}")
c2.metric("Month of plan", f"{planner.months_elapsed(S, today) + 1} / {S['goal_years'] * 12}")
c3.metric("Years left", planner.years_left(S, today))
c4.metric("Carried AI cash", f"₹{portfolio.cash_balance('ai'):,.0f}")

tab_plan, tab_chat, tab_port, tab_proj, tab_journal, tab_set = st.tabs(
    ["📅 This month", "💬 Ask the agent", "📊 Portfolio", "🔮 Projection", "📝 Journal", "⚙️ Settings"])

# ---------------------------- this month --------------------------------
with tab_plan:
    st.caption("Builds the plan from live data with plain Python — no AI needed, no API cost.")
    if st.button("Build this month's plan", type="primary"):
        with st.spinner("Fetching NAVs, prices and scanning AI stocks…"):
            p = planner.build_plan(S, today)
            planner.save_report(p)
            st.session_state.plan = p
    p = st.session_state.get("plan") or portfolio.get_plan(today.strftime("%Y-%m"))
    if p:
        m = p.get("market", {})
        if "nifty" in m:
            st.info(f"**Nifty 50 {m['nifty']:,}** · {m['below_52w_high_pct']}% from 52-week high · "
                    f"1-year {m['return_1y_pct']}%  \n{m['mood']}")
        for w in p["warnings"]:
            st.warning(w)
        for n in p["notes"]:
            st.success(n)

        st.subheader(f"Mutual fund SIPs — ₹{sum(i['amount'] for i in p['sips']):,}")
        st.dataframe(pd.DataFrame(p["sips"]).drop(columns=["error"], errors="ignore"),
                     hide_index=True, width="stretch")
        w = p["target_weights"]
        st.caption(f"Target split: index {w['index']:.0%} · flexi {w['flexi']:.0%} · debt {w['debt']:.0%}"
                   + (f" · drift {p['drift_pts']}" if p.get("drift_pts") else ""))

        a = p["ai"]
        st.subheader(f"🤖 AI / agentic bucket — ₹{a['money']:,.0f} available")
        if a.get("pick"):
            k = a["pick"]
            st.markdown(f"**{k['type']}: buy {k['qty']} × {k['ticker']} @ ₹{k['price']:,} = ₹{k['amount']:,}**")
            if k.get("stop_loss"):
                st.markdown(f"GTT OCO → stop **₹{k['stop_loss']:,}** · target **₹{k['target']:,}** "
                            f"(risk {k.get('risk_pct')}%)")
            st.caption(k["why"])
        else:
            st.write("No buy this month.")
        st.write(f"Carry forward: ₹{a.get('carry', 0):,.0f}")
        if a.get("scan"):
            with st.expander("Watchlist scan"):
                st.dataframe(pd.DataFrame(a["scan"]), hide_index=True, width="stretch")

        st.subheader("✅ Checklist")
        for c in p["checklist"]:
            st.checkbox(c, key=f"chk_{hash(c)}")
        st.download_button("Download report (.md)", planner.plan_markdown(p),
                           file_name=f"plan-{p['month_key']}.md")

# ------------------------------- agent ----------------------------------
with tab_chat:
    has_key = any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"))
    if not has_key:
        st.warning("Add OPENAI_API_KEY to .streamlit/secrets.toml (see README) to chat with the agent.")
    else:
        from langgraph.types import Command
        from agent.build import final_text, make_agent, pending_actions

        if "agent" not in st.session_state:
            st.session_state.agent = make_agent()
            st.session_state.thread = {"configurable": {"thread_id": str(uuid.uuid4())}}
            st.session_state.chat = []
            st.session_state.pending = []
        ag, cfg = st.session_state.agent, st.session_state.thread

        for role, text in st.session_state.chat:
            st.chat_message(role).markdown(text)

        def _after(result):
            st.session_state.pending = pending_actions(result)
            if not st.session_state.pending:
                st.session_state.chat.append(("assistant", final_text(result)))

        if st.session_state.pending:
            st.warning("The agent wants to save something. Approve only if it matches what you actually did.")
            with st.form("approve"):
                decisions_ui = []
                for i, act in enumerate(st.session_state.pending):
                    st.markdown(f"**{act['name']}**")
                    args = dict(act["args"])
                    for key in ("units", "price", "stop_loss", "target", "amount"):
                        if key in args:
                            args[key] = st.number_input(key, value=float(args[key] or 0), key=f"{i}{key}")
                    st.json({k: v for k, v in act["args"].items()})
                    choice = st.radio("Decision", ["approve", "edit (use numbers above)", "reject"],
                                      key=f"dec{i}", horizontal=True)
                    decisions_ui.append((choice, act["name"], args))
                if st.form_submit_button("Submit"):
                    decisions = []
                    for choice, name, args in decisions_ui:
                        if choice == "approve":
                            decisions.append({"type": "approve"})
                        elif choice.startswith("edit"):
                            decisions.append({"type": "edit", "edited_action": {"name": name, "args": args}})
                        else:
                            decisions.append({"type": "reject", "message": "User rejected."})
                    with st.spinner("Working…"):
                        _after(ag.invoke(Command(resume={"decisions": decisions}), cfg))
                    st.rerun()

        q = st.chat_input("e.g. 'make my plan for this month', 'I bought 1 PERSISTENT.NS at 5200'")
        if q:
            st.session_state.chat.append(("user", q))
            with st.spinner("Thinking with live data…"):
                try:
                    _after(ag.invoke({"messages": [{"role": "user", "content": q}]}, cfg))
                except Exception as e:
                    st.session_state.chat.append(("assistant", f"Error: {type(e).__name__}: {e}"))
            st.rerun()

# ----------------------------- portfolio --------------------------------
with tab_port:
    if st.button("Refresh live prices"):
        st.session_state.vh = portfolio.valued_holdings(S["ai_bucket"]["style"])
    vh = st.session_state.get("vh")
    if vh is None:
        vh = portfolio.holdings()
    if vh.empty:
        st.info("No trades recorded yet. Use the form below or tell the agent what you bought.")
    else:
        if "value" in vh:
            inv, val = vh["invested"].sum(), vh["value"].fillna(0).sum()
            a, b, c = st.columns(3)
            a.metric("Invested", f"₹{inv:,.0f}")
            b.metric("Value", f"₹{val:,.0f}")
            c.metric("P&L", f"₹{val - inv:,.0f}", f"{100 * (val / inv - 1):.2f}%" if inv else None)
            st.bar_chart(vh.groupby("bucket")["value"].sum())
        st.dataframe(vh, hide_index=True, width="stretch")

    with st.expander("➕ Record a trade manually"):
        with st.form("trade"):
            c1, c2, c3 = st.columns(3)
            kind = c1.selectbox("Kind", ["BUY", "SELL"])
            asset = c2.selectbox("Type", ["MF", "STOCK"])
            bucket = c3.selectbox("Bucket", ["index", "flexi", "debt", "ai"])
            symbol = st.text_input("Scheme code (MF) or ticker (e.g. INFY.NS)")
            name = st.text_input("Name (optional)")
            c1, c2, c3, c4 = st.columns(4)
            units = c1.number_input("Units / shares", min_value=0.0, step=0.001, format="%.3f")
            price = c2.number_input("Price / NAV", min_value=0.0, step=0.01)
            sl = c3.number_input("Stop-loss (stocks)", min_value=0.0, step=0.1)
            tg = c4.number_input("Target (stocks)", min_value=0.0, step=0.1)
            if st.form_submit_button("Save trade"):
                try:
                    r = portfolio.record_trade(kind, asset, bucket, symbol.strip().upper() if asset == "STOCK"
                                               else symbol.strip(), units, price, name, sl or None, tg or None,
                                               "manual entry")
                    portfolio.journal_add("trade", f"{r['kind']} {r['units']} {r['symbol']} @ {r['price']}", r)
                    st.success(f"Saved: {r}")
                except Exception as e:
                    st.error(str(e))
    with st.expander("💰 Carried AI cash"):
        amt = st.number_input("Add (+) or use (−) ₹", step=100.0)
        if st.button("Save cash entry"):
            bal = portfolio.add_cash("ai", amt, "manual")
            portfolio.journal_add("cash", f"AI cash {amt:+,.2f}", {"balance": bal})
            st.success(f"Balance ₹{bal:,.2f}")

# ----------------------------- projection -------------------------------
with tab_proj:
    c1, c2, c3, c4 = st.columns(4)
    monthly = c1.number_input("Monthly SIP ₹", value=float(S["monthly_budget"]), step=500.0)
    years = c2.slider("Years", 1, 40, int(S["goal_years"]))
    ret = c3.slider("Yearly return %", 0.0, 18.0, 12.0, 0.5)
    step = c4.slider("Step-up % per year", 0, 20, int(S["step_up_pct"]))
    df = planner.projection(monthly, years, ret, step)
    last = df.iloc[-1]
    infl = (1.06) ** years
    a, b, c = st.columns(3)
    a.metric("You invest", f"₹{last.invested / 1e5:,.1f} lakh")
    b.metric("Could become", f"₹{last.value / 1e5:,.1f} lakh")
    c.metric("In today's money (6% inflation)", f"₹{last.value / infl / 1e5:,.1f} lakh")
    st.line_chart(df.set_index("year")[["invested", "value"]])
    st.caption("Assumes a steady return every year. Real markets will have crashes and booms; nothing is guaranteed.")
    st.dataframe(df, hide_index=True, width="stretch")

# ------------------------------ journal ---------------------------------
with tab_journal:
    kind = st.selectbox("Show", ["all", "plan", "trade", "tool", "answer", "setting", "cash"])
    jd = portfolio.journal(200, None if kind == "all" else kind)
    st.dataframe(jd, hide_index=True, width="stretch")
    reports = sorted(planner.REPORTS_DIR.glob("*.md"), reverse=True)
    if reports:
        pick = st.selectbox("Monthly reports", [r.name for r in reports])
        st.markdown((planner.REPORTS_DIR / pick).read_text(encoding="utf-8"))

# ------------------------------ settings --------------------------------
with tab_set:
    with st.form("settings"):
        c1, c2, c3, c4 = st.columns(4)
        budget = c1.number_input("Monthly budget (year 1) ₹", value=int(S["monthly_budget"]), step=500)
        stepup = c2.number_input("Step-up % / year", value=int(S["step_up_pct"]), step=1)
        start = c3.text_input("Start month (YYYY-MM)", S["start_month"])
        goal = c4.number_input("Goal years", value=int(S["goal_years"]), step=1)
        st.markdown("**Funds** (search name, or paste exact scheme code to lock it)")
        funds = {}
        for b in ("index", "flexi", "debt"):
            c1, c2 = st.columns([3, 1])
            fq = c1.text_input(f"{b} fund", S["funds"][b]["query"])
            fc = c2.text_input(f"{b} scheme code", str(S["funds"][b]["scheme_code"] or ""))
            funds[b] = (fq, fc)
        st.markdown("**AI / agentic bucket**")
        c1, c2, c3 = st.columns(3)
        ai_m = c1.number_input("₹ per month", value=int(S["ai_bucket"]["monthly"]), step=100)
        style = c2.selectbox("Style", ["swing", "hold"], index=["swing", "hold"].index(S["ai_bucket"]["style"]))
        etf = c3.text_input("Fallback ETF", S["ai_bucket"]["fallback_etf"])
        wl = st.text_area("Watchlist (comma separated, .NS)", ", ".join(S["ai_bucket"]["watchlist"]))
        model = st.text_input("LLM model", S["model"])
        if st.form_submit_button("Save settings"):
            S.update(monthly_budget=int(budget), step_up_pct=int(stepup), start_month=start.strip(),
                     goal_years=int(goal), model=model.strip())
            for b, (fq, fc) in funds.items():
                S["funds"][b]["query"] = fq
                S["funds"][b]["scheme_code"] = int(fc) if fc.strip().isdigit() else None
            S["ai_bucket"].update(monthly=int(ai_m), style=style, fallback_etf=etf.strip().upper(),
                                  watchlist=[x.strip().upper() for x in wl.split(",") if x.strip()])
            settings.save(S)
            portfolio.journal_add("setting", "Settings saved from app", S)
            st.session_state.pop("agent", None)
            st.success("Saved.")

    st.markdown("### 💾 Backup (do this monthly — it's 30 years of history)")
    if portfolio.DB_PATH.exists():
        st.download_button("Download portfolio.db", portfolio.DB_PATH.read_bytes(),
                           file_name=f"portfolio-{today}.db")
    up = st.file_uploader("Restore from a backup .db", type=["db"])
    if up and st.button("Restore (replaces current data)"):
        shutil.copy(portfolio.DB_PATH, portfolio.DB_PATH.with_suffix(".before-restore.db")) \
            if portfolio.DB_PATH.exists() else None
        portfolio.DB_PATH.write_bytes(up.getvalue())
        st.success("Restored. Reload the page.")

st.caption("Educational tool, not SEBI-registered investment advice. It never places orders — you do, on Kite/Coin.")
