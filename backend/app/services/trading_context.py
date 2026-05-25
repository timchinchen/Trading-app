"""Shared trading context assembly for Chat and compression pipelines."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import AgentRun, DailyDigest
from ..services.broker import AlpacaBroker
from ..services import company_names
from ..services.settings_store import get_runtime_settings


def build_trading_context_text(
    db: Session,
    broker: AlpacaBroker,
    *,
    digests_limit: int = 5,
    runs_limit: int = 20,
) -> str:
    """Same structure as the Chat UI 'TRADING APP CONTEXT' block."""
    lines: list[str] = []
    today = datetime.utcnow().strftime("%a, %d %b %Y")
    lines.append(f"=== TRADING APP CONTEXT ({today}) ===")

    try:
        acct = broker.account()
        lines.append("")
        lines.append("--- ACCOUNT ---")
        lines.append(f"Mode: {settings.APP_MODE.upper()}")
        lines.append(f"Cash: ${float(acct.get('cash', 0)):,.2f}")
        lines.append(f"Buying power: ${float(acct.get('buying_power', 0)):,.2f}")
        lines.append(f"Portfolio value: ${float(acct.get('portfolio_value', 0)):,.2f}")
    except Exception as e:
        lines.append("")
        lines.append(f"--- ACCOUNT --- (unavailable: {e})")

    rs = get_runtime_settings(db)
    sched_next = ""
    try:
        from .. import main as _m
        sched = getattr(_m, "agent_scheduler", None)
        if sched and hasattr(sched, "next_run_at"):
            nr = sched.next_run_at()
            if nr:
                sched_next = nr.strftime("%d/%m/%Y, %H:%M:%S")
    except Exception:
        pass

    lines.append("")
    lines.append("--- AGENT SETTINGS ---")
    lines.append(f"Agent enabled: {rs.agent_enabled}")
    lines.append(f"Budget: ${rs.agent_budget_usd:.0f}")
    lines.append(f"Max open positions: {rs.agent_max_open_positions}")
    lines.append(f"Auto-sell (max hold): {rs.auto_sell_max_hold_days} days")
    if sched_next:
        lines.append(f"Next run: {sched_next}")

    try:
        positions = broker.positions() or []
        lines.append("")
        lines.append("--- OPEN POSITIONS ---")
        if not positions:
            lines.append("No open positions.")
        else:
            for p in positions:
                sym = (p.get("symbol") or "").upper()
                qty = float(p.get("qty") or 0)
                avg = float(p.get("avg_entry_price") or 0)
                last = float(p.get("current_price") or p.get("last") or 0)
                upl = float(p.get("unrealized_pl") or 0)
                plpct = (
                    ((last - avg) / avg * 100) if avg > 0 else 0.0
                )
                nm = company_names.lookup(sym) or ""
                name = f" ({nm})" if nm else ""
                lines.append(
                    f"{sym}{name}: qty={qty} avg=${avg:.2f} last=${last:.2f} "
                    f"P/L=${upl:.2f} ({plpct:+.2f}%)"
                )
    except Exception as e:
        lines.append("")
        lines.append(f"--- OPEN POSITIONS --- (unavailable: {e})")

    digest_rows = (
        db.query(DailyDigest)
        .order_by(DailyDigest.generated_at.desc())
        .limit(max(1, digests_limit))
        .all()
    )
    if digest_rows:
        lines.append("")
        lines.append("--- TRADING DIGESTS (most recent first) ---")
        for d in digest_rows:
            lines.append(f"[{d.trade_date}] {d.text.strip()}")

    run_rows = (
        db.query(AgentRun)
        .order_by(AgentRun.started_at.desc())
        .limit(max(1, runs_limit))
        .all()
    )
    recent = [r for r in run_rows if r.summary or r.advice]
    if recent:
        lines.append("")
        lines.append("--- RECENT AGENT RUNS (latest first) ---")
        for r in recent:
            ts = r.started_at.strftime("%d/%m/%Y, %H:%M:%S")
            exec_line = f"{r.trades_executed or 0} executed / {r.trades_proposed or 0} proposed"
            if r.advice:
                lines.append(f"[{ts}] {exec_line} | Advice: {r.advice.strip()}")
            elif r.summary:
                lines.append(f"[{ts}] {exec_line} | {r.summary.strip()}")

    lines.append("")
    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)
