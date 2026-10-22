"""Terminal entry points.

  python cli.py plan      # build + save this month's plan (no AI, no API cost)
  python cli.py chat      # chat with the agent in the terminal
  python cli.py backup    # copy portfolio.db into data/backups/
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import uuid

from core import planner, portfolio
from core.settings import DATA_DIR


def cmd_plan():
    p = planner.build_plan()
    path = planner.save_report(p)
    print(planner.plan_markdown(p))
    print(f"\nSaved report: {path}")


def cmd_backup():
    dest = DATA_DIR / "backups"
    dest.mkdir(exist_ok=True)
    out = dest / f"portfolio-{dt.date.today()}.db"
    shutil.copy(portfolio.DB_PATH, out)
    print(f"Backup saved: {out}")


def cmd_chat():
    from langgraph.types import Command
    from agent.build import final_text, make_agent, pending_actions
    if not any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")):
        sys.exit("Set OPENAI_API_KEY first (see README).")
    ag = make_agent()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("SIP agent ready. Type 'exit' to quit.\n")
    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if not q:
            continue
        try:
            r = ag.invoke({"messages": [{"role": "user", "content": q}]}, cfg)
            while (acts := pending_actions(r)):
                decisions = []
                for a in acts:
                    print(f"\n>>> {a['name']}: {json.dumps(a['args'])}")
                    ans = input("    [y] approve  [e] edit  [n] reject : ").strip().lower()
                    if ans == "y":
                        decisions.append({"type": "approve"})
                    elif ans == "e":
                        args = dict(a["args"])
                        for k in ("units", "price", "stop_loss", "target", "amount"):
                            if k in args and (v := input(f"    {k} [{args[k]}]: ").strip()):
                                args[k] = float(v)
                        decisions.append({"type": "edit", "edited_action": {"name": a["name"], "args": args}})
                    else:
                        decisions.append({"type": "reject", "message": "User rejected."})
                r = ag.invoke(Command(resume={"decisions": decisions}), cfg)
            print("\nAgent:", final_text(r), "\n")
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}")


if __name__ == "__main__":
    {"plan": cmd_plan, "chat": cmd_chat, "backup": cmd_backup}.get(
        sys.argv[1] if len(sys.argv) > 1 else "plan", cmd_plan)()
