"""Turn per-ticker signals into sized trade proposals.

Sizing model (real-money variant):
- Signals with score < MIN_SCORE or confidence < MIN_CONF never make it.
- Remaining candidates are sorted by strength = score * confidence and the
  top N are considered.
- Each accepted signal gets a slot in [MIN_POSITION_USD, MAX_POSITION_USD]
  sized linearly by strength: strength>=1.0 -> MAX, strength==MIN threshold
  -> MIN, clamped to both the per-run daily budget and the rolling weekly
  budget.
- Sell proposals are emitted only to close currently-held positions that the
  signals now consider bearish; never short-sell.
"""

from typing import Any, Callable, Optional

MIN_SCORE = 0.30
MIN_CONF = 0.30
TOP_N = 5  # raised from 3 - we can now afford more positions at $20-$40 each


def _strength(s: dict) -> float:
    return max(0.0, min(1.0, s["score"])) * max(0.0, min(1.0, s["confidence"]))


def _slot_for(
    strength: float, min_usd: float, max_usd: float
) -> float:
    """Linear map strength in [MIN_SCORE*MIN_CONF, 1.0] -> [min_usd, max_usd]."""
    lo = MIN_SCORE * MIN_CONF  # ~0.09
    if strength <= lo:
        return min_usd
    # normalised 0..1 across the strength band
    t = (strength - lo) / (1.0 - lo)
    t = max(0.0, min(1.0, t))
    return round(min_usd + t * (max_usd - min_usd), 2)


def propose_trades(
    signals: dict[str, dict[str, Any]],
    open_symbols: set[str],
    budget_remaining: float,
    weekly_remaining: float,
    min_position_usd: float,
    max_position_usd: float,
    max_open_positions: int,
    get_price: Callable[[str], Optional[float]],
) -> list[dict[str, Any]]:
    candidates = [
        (sym, s)
        for sym, s in signals.items()
        if s["score"] >= MIN_SCORE and s["confidence"] >= MIN_CONF
    ]
    candidates.sort(key=lambda x: _strength(x[1]), reverse=True)

    proposals: list[dict[str, Any]] = []
    remaining_slots = max(0, max_open_positions - len(open_symbols))
    daily_budget = max(0.0, float(budget_remaining))
    week_budget = max(0.0, float(weekly_remaining))

    for sym, s in candidates[:TOP_N]:
        if sym in open_symbols:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped", "reason": f"already holding {sym}",
            })
            continue

        if remaining_slots <= 0:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped",
                "reason": f"max open positions reached ({max_open_positions})",
            })
            continue

        desired = _slot_for(_strength(s), min_position_usd, max_position_usd)
        slot = min(desired, daily_budget, week_budget, max_position_usd)

        if slot < min_position_usd:
            # Don't emit sub-minimum orders - skip cleanly.
            reason_bits = []
            if daily_budget < min_position_usd:
                reason_bits.append(f"daily budget ${daily_budget:.2f} < min ${min_position_usd:.0f}")
            if week_budget < min_position_usd:
                reason_bits.append(f"weekly budget ${week_budget:.2f} < min ${min_position_usd:.0f}")
            reason = "; ".join(reason_bits) or f"slot ${slot:.2f} below min ${min_position_usd:.0f}"
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped", "reason": reason,
            })
            continue

        price = get_price(sym)
        if not price or price <= 0:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped", "reason": "no price available",
            })
            continue

        qty = round(slot / price, 4)
        if qty <= 0:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": price, "notional": 0.0,
                "action": "skipped", "reason": "qty rounded to 0",
            })
            continue

        notional = round(qty * price, 2)
        proposals.append({
            "symbol": sym, "side": "buy", "qty": qty,
            "est_price": price, "notional": notional,
            "action": "proposed",
            "reason": (
                f"score={s['score']:.2f} conf={s['confidence']:.2f} "
                f"mentions={s['mentions']} slot=${slot:.0f}"
            ),
        })
        daily_budget -= notional
        week_budget -= notional
        remaining_slots -= 1

    # Emit SELL proposals for currently-held names whose signal has turned
    # sharply bearish this run.
    for sym in open_symbols:
        s = signals.get(sym)
        if not s:
            continue
        if s["score"] <= -MIN_SCORE and s["confidence"] >= MIN_CONF:
            proposals.append({
                "symbol": sym, "side": "sell", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "proposed",
                "reason": (
                    f"bearish reversal score={s['score']:.2f} "
                    f"conf={s['confidence']:.2f} mentions={s['mentions']} "
                    f"(close position)"
                ),
            })

    return proposals
