"""Auto-sell: close any position held longer than AUTO_SELL_MAX_HOLD_DAYS.

This is a risk-hygiene control, not a trading strategy. The idea is simple:
if we've been in a name for N days and nothing has pushed it to stop, take
profit, or sell signal, cut it and redeploy the cash. It runs once per
trading day at 09:45 US/Eastern (15 min after market open) and writes the
same Order + Trade + AgentTrade + DigestEntry rows the agent runner does,
so the Orders page, Agent runs, and Trading Digest all show the exits.

Design notes:
- We only sell what the broker currently reports as open. If Alpaca says
  the position is flat, the local Trade history is ignored - the broker is
  the source of truth for "is this position open?".
- Holding duration is the timestamp of the *oldest* local BUY row for the
  symbol (Trade table first, falling back to AgentTrade with side='buy' and
  action='executed' if no Trade row exists). This avoids selling a position
  that was bought 3 days ago just because a Trade from 31 days ago on the
  same symbol has since been closed and reopened.
- Paper mode auto-executes. Live mode proposes unless
  AGENT_AUTO_EXECUTE_LIVE is true (matches the agent runner's policy).
- Idempotent inside a single trading day: if we've already filed a SELL
  order (or skipped) for this symbol in the last 6 hours we don't do it
  again, even if the scheduler is retriggered manually.

Callable from:
- The APScheduler cron (`AgentScheduler._auto_sell`) once per weekday.
- The `/agent/auto-sell/run-now` endpoint for manual triggers.
- The `/agent/auto-sell/preview` endpoint for a dry-run.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from ...config import settings
from ...db import SessionLocal
from ...models import AgentTrade, Order, Trade
from ..broker import AlpacaBroker
from ..digest_store import append_entry as digest_append
from ..settings_store import get_runtime_settings


@dataclass
class AutoSellCandidate:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    opened_at: datetime
    held_days: float
    over_cap: bool
    cap_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_entry_price": self.avg_entry_price,
            "current_price": self.current_price,
            "opened_at": self.opened_at.isoformat(),
            "held_days": round(self.held_days, 2),
            "over_cap": self.over_cap,
            "cap_days": self.cap_days,
        }


def _oldest_open_buy_timestamp(db: Session, symbol: str, mode: str) -> Optional[datetime]:
    """Timestamp of the earliest BUY that is still holding this symbol open.

    We walk the local trade ledger chronologically and keep a running qty
    balance. The 'opened_at' we return is the timestamp of the first BUY
    that contributed to the currently-open position (i.e. once the running
    balance last went from 0 -> positive).
    """
    # Prefer the Trade table (records actual fills). Fall back to AgentTrade
    # executed rows if we somehow have no Trade row (older paper rows that
    # pre-dated the Trade insert).
    rows = (
        db.query(Trade)
        .filter(Trade.symbol == symbol, Trade.mode == mode)
        .order_by(Trade.filled_at.asc())
        .all()
    )
    if not rows:
        # AgentTrade fallback. executed rows only.
        ag = (
            db.query(AgentTrade)
            .filter(
                AgentTrade.symbol == symbol,
                AgentTrade.mode == mode,
                AgentTrade.action == "executed",
            )
            .order_by(AgentTrade.created_at.asc())
            .all()
        )
        ts_rows: list[tuple[datetime, str, float]] = [
            (r.created_at, r.side, float(r.qty or 0)) for r in ag
        ]
    else:
        ts_rows = [(r.filled_at, r.side, float(r.qty or 0)) for r in rows]

    balance = 0.0
    lot_start: Optional[datetime] = None
    for ts, side, qty in ts_rows:
        if side == "buy":
            if balance <= 0.000001:
                lot_start = ts
            balance += qty
        else:  # sell
            balance -= qty
            if balance <= 0.000001:
                lot_start = None
                balance = 0.0
    return lot_start if balance > 0.000001 else None


def _recent_sell_for(db: Session, symbol: str, mode: str, within_hours: int = 6) -> bool:
    """Did we already file a SELL (order or proposal) for this symbol very
    recently? Used to dedupe if the auto-sell job is triggered twice in a
    day (manual run-now after the cron, or double-fire on the scheduler)."""
    cutoff = datetime.utcnow() - timedelta(hours=within_hours)
    hit = (
        db.query(Order)
        .filter(
            Order.symbol == symbol,
            Order.side == "sell",
            Order.mode == mode,
            Order.submitted_at >= cutoff,
        )
        .first()
    )
    if hit:
        return True
    # Also dedupe against skipped/proposed auto-sell AgentTrades so we don't
    # spam the log on every retrigger while live-mode proposals sit waiting.
    hit2 = (
        db.query(AgentTrade)
        .filter(
            AgentTrade.symbol == symbol,
            AgentTrade.side == "sell",
            AgentTrade.mode == mode,
            AgentTrade.created_at >= cutoff,
            AgentTrade.reason.like("auto-sell:%"),  # only dedupe our own
        )
        .first()
    )
    return bool(hit2)


def _collect_candidates(
    broker: AlpacaBroker, db: Session, *, cap_days: int
) -> list[AutoSellCandidate]:
    if not broker.configured:
        return []
    mode = settings.APP_MODE
    positions = broker.positions()
    now = datetime.utcnow()
    out: list[AutoSellCandidate] = []
    for p in positions:
        try:
            qty = float(p.get("qty") or 0)
        except Exception:
            qty = 0.0
        if qty <= 0:
            # Only long positions. Shorts handled manually.
            continue
        symbol = (p.get("symbol") or "").upper()
        if not symbol:
            continue
        opened = _oldest_open_buy_timestamp(db, symbol, mode)
        if opened is None:
            # No local lineage - position probably predates this app. We
            # refuse to auto-close it because we don't know when it opened;
            # the user can still manually close it from the UI.
            continue
        held = (now - opened).total_seconds() / 86400.0
        out.append(
            AutoSellCandidate(
                symbol=symbol,
                qty=qty,
                avg_entry_price=float(p.get("avg_entry_price") or 0),
                current_price=float(p.get("current_price") or 0),
                opened_at=opened,
                held_days=held,
                over_cap=held >= cap_days,
                cap_days=cap_days,
            )
        )
    return out


def preview(broker: AlpacaBroker, db: Optional[Session] = None) -> dict[str, Any]:
    """Non-destructive scan. Returns the list of open positions with their
    held_days, flagged `over_cap=true` where we would auto-sell."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        rs = get_runtime_settings(db)
        cap = int(rs.auto_sell_max_hold_days)
        cand = _collect_candidates(broker, db, cap_days=cap)
        return {
            "enabled": bool(rs.auto_sell_enabled),
            "max_hold_days": cap,
            "mode": settings.APP_MODE,
            "auto_execute": (
                settings.APP_MODE == "paper"
                or (settings.APP_MODE == "live" and rs.agent_auto_execute_live)
            ),
            "candidates": [c.to_dict() for c in cand],
            "would_sell_count": sum(1 for c in cand if c.over_cap),
        }
    finally:
        if own:
            db.close()


def run_auto_sell_sync(
    broker: AlpacaBroker, db: Optional[Session] = None, *, forced: bool = False
) -> dict[str, Any]:
    """The worker body. Returns a summary dict for the API + log.

    If `forced=True`, runs even if AUTO_SELL_ENABLED is false (used by the
    explicit POST /agent/auto-sell/run-now endpoint so an operator can
    trigger a one-off scan without flipping the toggle).
    """
    own = db is None
    if own:
        db = SessionLocal()
    try:
        rs = get_runtime_settings(db)
        if not rs.auto_sell_enabled and not forced:
            return {
                "status": "disabled",
                "detail": "AUTO_SELL_ENABLED=false",
                "executed": 0,
                "proposed": 0,
                "skipped": 0,
                "candidates": [],
            }
        if not broker.configured:
            return {
                "status": "no_broker",
                "detail": "Alpaca broker not configured",
                "executed": 0,
                "proposed": 0,
                "skipped": 0,
                "candidates": [],
            }

        cap = int(rs.auto_sell_max_hold_days)
        mode = settings.APP_MODE
        auto_execute = (
            mode == "paper" or (mode == "live" and rs.agent_auto_execute_live)
        )

        cand = _collect_candidates(broker, db, cap_days=cap)
        sells = [c for c in cand if c.over_cap]

        executed = 0
        proposed = 0
        skipped = 0
        actions: list[dict[str, Any]] = []

        for c in sells:
            if _recent_sell_for(db, c.symbol, mode):
                skipped += 1
                actions.append({
                    "symbol": c.symbol,
                    "action": "skipped",
                    "reason": "recent sell/proposal already on file",
                    "held_days": round(c.held_days, 2),
                })
                continue

            reason = (
                f"auto-sell: held {c.held_days:.1f}d (cap={cap}d) "
                f"entry=${c.avg_entry_price:.2f} last=${c.current_price:.2f}"
            )
            est_notional = float(c.qty) * float(c.current_price or 0)

            at = AgentTrade(
                run_id=None,  # not attached to any agent run
                symbol=c.symbol,
                side="sell",
                qty=c.qty,
                est_price=c.current_price,
                notional=est_notional,
                action="proposed",
                reason=reason,
                mode=mode,
            )
            db.add(at)
            db.flush()

            if not auto_execute:
                proposed += 1
                actions.append({
                    "symbol": c.symbol,
                    "action": "proposed",
                    "qty": c.qty,
                    "est_notional": est_notional,
                    "held_days": round(c.held_days, 2),
                })
                try:
                    digest_append(
                        kind="auto_sell_propose",
                        symbol=c.symbol,
                        summary=(
                            f"Auto-sell proposed for {c.symbol}: "
                            f"held {c.held_days:.1f}d >= {cap}d cap"
                        ),
                        data={
                            "qty": c.qty,
                            "cap_days": cap,
                            "held_days": round(c.held_days, 2),
                        },
                        db=db,
                    )
                except Exception:
                    pass
                continue

            # Execute.
            try:
                result = broker.place_order(
                    symbol=c.symbol, qty=c.qty, side="sell", type_="market",
                )
                order = Order(
                    alpaca_id=result.get("alpaca_id"),
                    symbol=result["symbol"],
                    qty=result["qty"],
                    side=result["side"],
                    type=result["type"],
                    limit_price=result.get("limit_price"),
                    status=result.get("status", "new"),
                    mode=mode,
                )
                db.add(order)
                db.flush()
                at.order_id = order.id
                at.action = "executed"
                executed += 1
                actions.append({
                    "symbol": c.symbol,
                    "action": "executed",
                    "qty": c.qty,
                    "alpaca_id": order.alpaca_id,
                    "held_days": round(c.held_days, 2),
                })
                try:
                    digest_append(
                        kind="auto_sell_exec",
                        symbol=c.symbol,
                        summary=(
                            f"Auto-sold {c.symbol}: held {c.held_days:.1f}d "
                            f"(cap={cap}d), qty={c.qty} @ ~${c.current_price:.2f}"
                        ),
                        data={
                            "qty": c.qty,
                            "cap_days": cap,
                            "held_days": round(c.held_days, 2),
                            "entry": c.avg_entry_price,
                            "last": c.current_price,
                            "alpaca_id": order.alpaca_id,
                        },
                        db=db,
                    )
                except Exception:
                    pass
            except Exception as e:
                skipped += 1
                at.action = "skipped"
                at.reason = f"{reason} | exec failed: {e}"
                actions.append({
                    "symbol": c.symbol,
                    "action": "skipped",
                    "reason": f"exec failed: {e}",
                    "held_days": round(c.held_days, 2),
                })
        db.commit()

        return {
            "status": "ok",
            "mode": mode,
            "auto_execute": auto_execute,
            "max_hold_days": cap,
            "considered": len(cand),
            "executed": executed,
            "proposed": proposed,
            "skipped": skipped,
            "actions": actions,
            "candidates": [c.to_dict() for c in cand],
        }
    finally:
        if own:
            db.close()


async def run_auto_sell(broker: AlpacaBroker, *, forced: bool = False) -> dict[str, Any]:
    """Async wrapper that runs the sync body in a worker thread so the
    APScheduler event loop isn't blocked by broker HTTP calls."""
    return await asyncio.to_thread(run_auto_sell_sync, broker, None, forced=forced)


# Re-export JSON encoder helpers used by the API preview (kept here so the
# router module doesn't need to know about dataclass internals).
def dumps_preview(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)
