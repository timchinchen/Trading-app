"""Turn per-ticker signals into sized trade proposals.

Rules:
- Only consider signals with score >= MIN_SCORE and confidence >= MIN_CONF.
- Top N by (score * confidence). Default N = 3.
- Each trade capped at max_position_usd.
- Total new notional per run capped to remaining budget.
- Skip if ticker already has an open position (simple guard).
- BUY-only for the MVP (long signals). SELL proposals only to close existing positions.
"""

from typing import Any

MIN_SCORE = 0.30
MIN_CONF = 0.30
TOP_N = 3


def propose_trades(
    signals: dict[str, dict[str, Any]],
    open_symbols: set[str],
    budget_remaining: float,
    max_position_usd: float,
    get_price,
) -> list[dict[str, Any]]:
    candidates = [
        (sym, s) for sym, s in signals.items()
        if s["score"] >= MIN_SCORE and s["confidence"] >= MIN_CONF
    ]
    candidates.sort(key=lambda x: x[1]["score"] * x[1]["confidence"], reverse=True)
    proposals: list[dict[str, Any]] = []
    budget = budget_remaining

    for sym, s in candidates[:TOP_N]:
        if sym in open_symbols:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped",
                "reason": f"already holding {sym}",
            })
            continue
        if budget <= 1.0:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped",
                "reason": "budget exhausted",
            })
            continue
        price = get_price(sym)
        if not price or price <= 0:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": None, "notional": 0.0,
                "action": "skipped",
                "reason": "no price available",
            })
            continue
        slot = min(max_position_usd, budget)
        notional = slot
        qty = round(notional / price, 4)
        if qty <= 0:
            proposals.append({
                "symbol": sym, "side": "buy", "qty": 0.0,
                "est_price": price, "notional": 0.0,
                "action": "skipped", "reason": "qty rounded to 0",
            })
            continue
        proposals.append({
            "symbol": sym, "side": "buy", "qty": qty,
            "est_price": price, "notional": round(qty * price, 2),
            "action": "proposed",
            "reason": f"score={s['score']} conf={s['confidence']} mentions={s['mentions']}",
        })
        budget -= qty * price
    return proposals
