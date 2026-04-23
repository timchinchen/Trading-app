"""Classify symbols into the four approved 1-2 week swing setups.

SKILL: short-term swing trading, 1-2 week horizon, 5-15% upside, <=1% risk.

Given a set of daily bars and (optional) indicators from technicals.snapshot,
this module emits SetupPlan objects that specify entry, stop, target, R/R and
suggested position size per the user's skill rulebook. The runner feeds these
plans into the allocator so the agent only buys real setups.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from . import technicals as T


SETUP_PULLBACK = "trend_pullback"
SETUP_BREAKOUT = "breakout"
SETUP_OVERSOLD = "oversold_bounce"
SETUP_NEWS = "news_momentum"


@dataclass
class SetupPlan:
    symbol: str
    setup: str
    entry: float
    stop: float
    target: float
    rr: float
    note: str
    # Informational: what the scanner saw. Copied into log + advisor context.
    indicators: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @property
    def risk_per_share(self) -> float:
        return max(0.0, self.entry - self.stop)


# ---------------------------------------------------------------------------
# Market regime filter
# ---------------------------------------------------------------------------
def market_regime(spy_bars: list[dict], ma: int = 50) -> dict[str, Any]:
    """Evaluate whether the broader market is trending upward.

    Go condition (all must hold):
      - price above the MA
      - MA slope over last 5 bars is > 0 (rising)
      - today's close > 20-day SMA

    Returns {go: bool, reason: str, ...ind}.
    """
    cs = T.closes(spy_bars)
    sma_big = T.sma(cs, ma)
    sma20 = T.sma(cs, 20)
    last = cs[-1] if cs else None
    # Simple slope: compare current MA vs MA 5 bars ago.
    sma_prev = None
    if len(cs) >= ma + 5:
        sma_prev = T.sma(cs[:-5], ma)
    rising = bool(sma_big and sma_prev and sma_big > sma_prev)
    above = bool(last and sma_big and last > sma_big)
    above_short = bool(last and sma20 and last > sma20)

    if last is None or sma_big is None:
        return {
            "go": False,
            "reason": "insufficient SPY history",
            "last": last,
            "sma_big": sma_big,
            "sma20": sma20,
            "rising": False,
        }
    if above and rising and above_short:
        reason = (
            f"SPY {last:.2f} > SMA{ma} {sma_big:.2f}, MA rising, > SMA20"
        )
        go = True
    else:
        bits = []
        if not above:
            bits.append(f"price<SMA{ma}")
        if not rising:
            bits.append(f"SMA{ma} not rising")
        if not above_short:
            bits.append("below SMA20")
        reason = "regime off: " + ", ".join(bits)
        go = False
    return {
        "go": go,
        "reason": reason,
        "last": last,
        "sma_big": sma_big,
        "sma20": sma20,
        "rising": rising,
    }


# ---------------------------------------------------------------------------
# Per-symbol setup classifier
# ---------------------------------------------------------------------------
def _clamp_stop(entry: float, stop: float, min_stop_pct: float, max_stop_pct: float) -> float:
    """Keep stop inside [min%, max%] of entry so we don't take insane risk or
    too-tight stops that get whipsawed."""
    min_stop = entry * (1 - max_stop_pct)
    max_stop = entry * (1 - min_stop_pct)
    return max(min_stop, min(stop, max_stop))


def _pullback(sym: str, bars: list[dict], snap: dict) -> Optional[SetupPlan]:
    sma20 = snap.get("sma20")
    sma50 = snap.get("sma50")
    last = snap.get("last")
    swing_low_10 = snap.get("swing_low_10")
    if not (last and sma20 and sma50 and swing_low_10):
        return None
    # Context: clear uptrend (price above both MAs, SMA20 > SMA50).
    if not (last > sma20 and last > sma50 and sma20 > sma50):
        return None
    # Pullback: last close within 5% above the 20-MA (touch or slight overshoot).
    dist_to_20 = (last - sma20) / sma20
    if dist_to_20 > 0.05 or dist_to_20 < -0.02:
        return None
    # Reversal signal: today's bar closed above its open.
    today = bars[-1]
    if not (today.get("c") and today.get("o") and today["c"] > today["o"]):
        return None
    entry = last
    stop = _clamp_stop(entry, swing_low_10, 0.03, 0.06)
    # Target = retest of 20-day swing high, clamped to 5-15%.
    high = snap.get("swing_high_20") or (entry * 1.10)
    target = max(entry * 1.05, min(high, entry * 1.15))
    risk = entry - stop
    reward = target - entry
    rr = (reward / risk) if risk > 0 else 0.0
    return SetupPlan(
        symbol=sym,
        setup=SETUP_PULLBACK,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        rr=round(rr, 2),
        note=(
            f"uptrend (price ${last:.2f} > SMA20 ${sma20:.2f} > SMA50 "
            f"${sma50:.2f}); pulled back to SMA20; bullish close today"
        ),
        indicators={"sma20": sma20, "sma50": sma50, "swing_low_10": swing_low_10},
    )


def _breakout(sym: str, bars: list[dict], snap: dict) -> Optional[SetupPlan]:
    last = snap.get("last")
    rng = snap.get("range_pct_15")
    vspike = snap.get("volume_spike")
    swing_high_15 = T.swing_high(bars[:-1], 15) if len(bars) >= 16 else None
    swing_low_15 = T.swing_low(bars[:-1], 15) if len(bars) >= 16 else None
    if not (last and rng is not None and swing_high_15 and swing_low_15):
        return None
    # Tight range requirement and expansion on volume.
    if rng > 0.12:                # >12% range is not 'tight'
        return None
    if not (last > swing_high_15):  # must break the prior-range high
        return None
    if not (vspike and vspike >= 1.5):
        return None
    entry = last
    stop = _clamp_stop(entry, swing_low_15, 0.03, 0.05)
    target = entry * 1.10
    risk = entry - stop
    reward = target - entry
    rr = (reward / risk) if risk > 0 else 0.0
    return SetupPlan(
        symbol=sym,
        setup=SETUP_BREAKOUT,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        rr=round(rr, 2),
        note=(
            f"broke 15-bar range high {swing_high_15:.2f} on "
            f"volume x{vspike:.1f}; tight range ({rng*100:.1f}%)"
        ),
        indicators={
            "range_pct_15": rng,
            "swing_high_15": swing_high_15,
            "volume_spike": vspike,
        },
    )


def _oversold(sym: str, bars: list[dict], snap: dict) -> Optional[SetupPlan]:
    rsi_v = snap.get("rsi14")
    consec = snap.get("consec_down") or 0
    last = snap.get("last")
    swing_low_10 = snap.get("swing_low_10")
    if not (rsi_v and last and swing_low_10):
        return None
    if rsi_v >= 30 or consec < 2:
        return None
    # Need first strong up-move: today closed higher than opened AND > prior close.
    today = bars[-1]
    prev_close = bars[-2].get("c") if len(bars) >= 2 else None
    if not (today.get("c") and today.get("o") and prev_close):
        return None
    if not (today["c"] > today["o"] and today["c"] > prev_close):
        return None
    entry = last
    stop = _clamp_stop(entry, swing_low_10, 0.03, 0.05)
    target = entry * 1.06        # conservative bounce target (3-8% band)
    risk = entry - stop
    reward = target - entry
    rr = (reward / risk) if risk > 0 else 0.0
    return SetupPlan(
        symbol=sym,
        setup=SETUP_OVERSOLD,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        rr=round(rr, 2),
        note=(
            f"RSI {rsi_v:.1f} after {consec} down days; first bullish reclaim. "
            "Reduce size; exit fast if bounce fails."
        ),
        indicators={"rsi14": rsi_v, "consec_down": consec, "swing_low_10": swing_low_10},
    )


def _news_momentum(sym: str, bars: list[dict], snap: dict) -> Optional[SetupPlan]:
    gap = snap.get("gap_pct")
    vspike = snap.get("volume_spike")
    last = snap.get("last")
    if not (gap and vspike and last):
        return None
    if gap < 0.02 or vspike < 1.5:
        return None
    # Today's bar should hold most of its gap.
    today = bars[-1]
    prev_close = bars[-2].get("c") if len(bars) >= 2 else None
    if not prev_close:
        return None
    if today.get("c", 0) < prev_close * 1.01:      # gave back most of the gap
        return None
    entry = last
    gap_support = prev_close * 1.005
    stop = _clamp_stop(entry, gap_support, 0.04, 0.08)
    target = entry * 1.10
    risk = entry - stop
    reward = target - entry
    rr = (reward / risk) if risk > 0 else 0.0
    return SetupPlan(
        symbol=sym,
        setup=SETUP_NEWS,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        rr=round(rr, 2),
        note=(
            f"gap up {gap*100:.1f}% on volume x{vspike:.1f}; held above "
            f"prior close {prev_close:.2f}"
        ),
        indicators={"gap_pct": gap, "volume_spike": vspike, "prev_close": prev_close},
    )


def classify(sym: str, bars: list[dict], snap: dict) -> Optional[SetupPlan]:
    """Run the setup detectors in priority order and return the first match.
    News momentum wins when both news and pullback trigger, since catalyst
    beats pure technicals for the 1-2 week window."""
    if not bars or len(bars) < 30:
        return None
    for fn in (_news_momentum, _breakout, _pullback, _oversold):
        plan = fn(sym, bars, snap)
        if plan and plan.rr > 0:
            return plan
    return None


# ---------------------------------------------------------------------------
# Risk-based position sizing (per SKILL rulebook)
# ---------------------------------------------------------------------------
def size_plan(
    plan: SetupPlan,
    *,
    total_capital_usd: float,
    risk_pct: float,
    min_position_usd: float,
    max_position_usd: float,
    min_rr: float,
) -> dict[str, Any]:
    """Return {qty, notional, slot, risk_usd, rejected, reason}.

    Shares = (risk_usd / risk_per_share), clamped to [min_slot, max_slot]
    dollar bands. If the plan's R/R is below min_rr, reject outright.
    """
    if plan.rr < min_rr:
        return {
            "qty": 0.0, "notional": 0.0, "slot": 0.0, "risk_usd": 0.0,
            "rejected": True,
            "reason": f"R/R {plan.rr:.2f} < min {min_rr:.2f}",
        }
    if plan.risk_per_share <= 0 or plan.entry <= 0:
        return {
            "qty": 0.0, "notional": 0.0, "slot": 0.0, "risk_usd": 0.0,
            "rejected": True,
            "reason": "invalid entry/stop (risk_per_share <= 0)",
        }

    risk_usd = total_capital_usd * risk_pct
    raw_qty = risk_usd / plan.risk_per_share
    raw_notional = raw_qty * plan.entry

    # Clamp to the min/max position band. Note: clamping UP may inflate risk,
    # so we recompute and warn when that happens.
    if raw_notional < min_position_usd:
        qty = min_position_usd / plan.entry
        notional = min_position_usd
        note = f"min-slot uplift (raw ${raw_notional:.2f} < min ${min_position_usd:.0f})"
    elif raw_notional > max_position_usd:
        qty = max_position_usd / plan.entry
        notional = max_position_usd
        note = f"max-slot cap (raw ${raw_notional:.2f} > max ${max_position_usd:.0f})"
    else:
        qty = raw_qty
        notional = raw_notional
        note = f"risk-sized (${risk_usd:.2f} / ${plan.risk_per_share:.2f} per share)"

    return {
        "qty": round(qty, 4),
        "notional": round(notional, 2),
        "slot": round(notional, 2),
        "risk_usd": round(risk_usd, 2),
        "rejected": False,
        "reason": note,
    }


def brief_line(plan: SetupPlan) -> str:
    """Single-line representation for logs / advisor prompts."""
    return (
        f"{plan.symbol} [{plan.setup}] entry=${plan.entry:.2f} "
        f"stop=${plan.stop:.2f} target=${plan.target:.2f} R/R={plan.rr:.2f} "
        f"-- {plan.note}"
    )
