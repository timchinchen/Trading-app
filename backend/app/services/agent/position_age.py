"""Single source of truth for "when did the currently-held lot open?".

Historically three different call sites answered this three different ways and
two of them were wrong:

  A. runner._adaptive_exit_proposals used ``AgentPositionPlan.opened_at`` — which
     backfill_position_plans stamps with ``utcnow()``, so a six-month-old
     position that gets backfilled today reads as age 0 (too lenient).
  B. runner._adaptive_exit_proposals' no-plan fallback took the *oldest ever*
     executed BUY for the symbol (``.asc().first()``) with no lookback window
     and no accounting for intervening sells that flattened the position. Buy in
     June, sell, re-buy yesterday → "held 67.9d" → closed immediately.
  C. auto_sell._oldest_open_buy_timestamp walked a running balance (the right
     idea) but used a 1e-6 share epsilon — far too tight for a fractional-share
     account, so leftover dust (e.g. 0.0004 shares) left the lot permanently
     "open" and merged every future buy into the original lot.

This module replaces all three with one corrected walk:

  * A generous ``LOT_EPSILON`` (1e-4 shares) so fractional-share dust can't keep
    a flat position looking open.
  * A *merged* ledger (Trade UNION executed AgentTrade, deduped on the broker
    order id) so auto-sell exits — which write AgentTrade+Order but no Trade
    row — are visible to the balance walk.
  * Case-insensitive side matching so "BUY"/"Buy" aren't miscounted as sells.
  * Returns ``None`` when we have no local lineage. Callers MUST treat None as
    "unknown — do not time-stop" rather than guessing. Guessing is what broke it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...models import AgentTrade, Order, Trade

# Fractional-share dust tolerance. Alpaca fills quantities like 0.0592 or
# 1.3997; a 50% partial take on an odd quantity can leave ~0.0004 shares behind.
# 1e-6 (the old value) treated that as an open lot forever; 1e-4 is small enough
# to round-trip real fills to flat while ignoring genuine dust.
LOT_EPSILON = 1e-4


def _merged_fills(db: Session, symbol: str, mode: str) -> list[tuple[datetime, str, float]]:
    """Chronological ``(timestamp, side, qty)`` fills for one symbol.

    Merges the Trade ledger with executed AgentTrade rows and dedupes on the
    broker order id so a fill recorded in both tables is only counted once.
    Rows without a usable timestamp are dropped.
    """
    symbol = (symbol or "").upper()
    rows: list[tuple[datetime, str, float]] = []
    seen_broker_ids: set[str] = set()

    # Trade rows record actual fills. No code path writes them today, but we
    # read them so the helper stays correct if fill-recording is added later.
    for t in db.query(Trade).filter(Trade.symbol == symbol, Trade.mode == mode).all():
        bid = getattr(t, "alpaca_id", None)
        if bid:
            seen_broker_ids.add(str(bid))
        if t.filled_at is not None:
            rows.append((t.filled_at, str(t.side or "").lower(), float(t.qty or 0.0)))

    # Executed AgentTrade rows, joined to their Order for the broker id so we
    # can skip anything a Trade row already accounts for.
    q = (
        db.query(AgentTrade, Order)
        .outerjoin(Order, AgentTrade.order_id == Order.id)
        .filter(
            AgentTrade.symbol == symbol,
            AgentTrade.mode == mode,
            AgentTrade.action == "executed",
        )
        .all()
    )
    for at, order in q:
        bid = getattr(order, "alpaca_id", None) if order is not None else None
        if bid and str(bid) in seen_broker_ids:
            continue  # already counted via a Trade row
        if bid:
            seen_broker_ids.add(str(bid))
        if at.created_at is not None:
            rows.append((at.created_at, str(at.side or "").lower(), float(at.qty or 0.0)))

    rows.sort(key=lambda r: r[0])
    return rows


def open_lot_opened_at(db: Session, symbol: str, mode: str) -> Optional[datetime]:
    """Timestamp of the BUY that opened the CURRENTLY held lot, or None.

    Walks the merged local ledger chronologically, tracking a running share
    balance. ``lot_start`` is set whenever the balance rises off flat (<=
    LOT_EPSILON) and cleared whenever it returns to flat. Returns None when the
    net balance is flat (nothing open) or when we have no local lineage — in
    which case the caller must NOT time-stop the position.
    """
    balance = 0.0
    lot_start: Optional[datetime] = None
    for ts, side, qty in _merged_fills(db, symbol, mode):
        if side == "buy":
            if balance <= LOT_EPSILON:
                lot_start = ts
            balance += qty
        else:  # any non-buy fill reduces the position
            balance -= qty
            if balance <= LOT_EPSILON:
                lot_start = None
                balance = 0.0
    return lot_start if balance > LOT_EPSILON else None
