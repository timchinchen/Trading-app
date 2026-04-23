"""Lightweight technical-analysis primitives for the 1-2 week swing skill.

Everything here is pure-Python and operates on a list of daily OHLCV bars
(oldest first) as produced by AlpacaBroker.fetch_daily_bars. No numpy /
pandas dependency so the backend image stays slim.

Functions:
    sma(values, n)
    rsi(closes, n=14)
    swing_low(bars, window)  -> last N-bar low
    swing_high(bars, window) -> last N-bar high
    avg_volume(bars, n)
    trend_slope(values, n)   -> (last - n_ago) / n_ago
    relative_strength(sym_closes, spy_closes, n=20)
"""

from __future__ import annotations

from typing import Iterable, Sequence


def sma(values: Sequence[float], n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def rsi(closes: Sequence[float], n: int = 14) -> float | None:
    """Wilder's RSI. Returns None when there isn't enough data."""
    if n <= 0 or len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    # Seed with the first n deltas.
    for i in range(1, n + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / n
    avg_loss = losses / n
    # Wilder smoothing across the rest.
    for i in range(n + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def swing_low(bars: Sequence[dict], window: int) -> float | None:
    if not bars or window <= 0:
        return None
    slice_ = bars[-window:] if len(bars) >= window else bars
    return min(b["l"] for b in slice_ if b.get("l") is not None)


def swing_high(bars: Sequence[dict], window: int) -> float | None:
    if not bars or window <= 0:
        return None
    slice_ = bars[-window:] if len(bars) >= window else bars
    return max(b["h"] for b in slice_ if b.get("h") is not None)


def avg_volume(bars: Sequence[dict], n: int) -> float | None:
    if not bars or n <= 0:
        return None
    slice_ = bars[-n:] if len(bars) >= n else bars
    vols = [b.get("v") or 0 for b in slice_]
    if not vols:
        return None
    return sum(vols) / len(vols)


def trend_slope(values: Sequence[float], n: int) -> float | None:
    """Fractional change from `n` bars ago to the latest. >0 => rising."""
    if len(values) < n + 1 or n <= 0:
        return None
    old = values[-n - 1]
    new = values[-1]
    if old == 0:
        return None
    return (new - old) / old


def relative_strength(
    sym_closes: Sequence[float], spy_closes: Sequence[float], n: int = 20
) -> float | None:
    """Symbol's n-day return minus SPY's n-day return. >0 = outperforming."""
    if len(sym_closes) < n + 1 or len(spy_closes) < n + 1:
        return None
    s_ret = (sym_closes[-1] - sym_closes[-n - 1]) / sym_closes[-n - 1]
    m_ret = (spy_closes[-1] - spy_closes[-n - 1]) / spy_closes[-n - 1]
    return s_ret - m_ret


def closes(bars: Sequence[dict]) -> list[float]:
    return [b["c"] for b in bars if b.get("c") is not None]


def volumes(bars: Sequence[dict]) -> list[int]:
    return [int(b.get("v") or 0) for b in bars]


def range_pct(bars: Sequence[dict], window: int) -> float | None:
    """(high - low) / low over the last `window` bars. Lower = tighter."""
    hi = swing_high(bars, window)
    lo = swing_low(bars, window)
    if hi is None or lo is None or lo <= 0:
        return None
    return (hi - lo) / lo


def consecutive_down_days(bars: Sequence[dict]) -> int:
    """How many of the most recent bars closed lower than the previous close."""
    cs = closes(bars)
    if len(cs) < 2:
        return 0
    n = 0
    for i in range(len(cs) - 1, 0, -1):
        if cs[i] < cs[i - 1]:
            n += 1
        else:
            break
    return n


def gap_pct(bars: Sequence[dict]) -> float | None:
    """Today's open vs yesterday's close. >0.02 ~ meaningful gap up."""
    if len(bars) < 2:
        return None
    prev_close = bars[-2].get("c")
    today_open = bars[-1].get("o")
    if not prev_close or not today_open:
        return None
    return (today_open - prev_close) / prev_close


def volume_spike(bars: Sequence[dict], lookback: int = 20) -> float | None:
    """Today's volume / avg of last `lookback` bars. >1.5 == elevated."""
    if len(bars) < lookback + 1:
        return None
    today = bars[-1].get("v") or 0
    base = avg_volume(bars[:-1], lookback) or 0
    if base <= 0:
        return None
    return today / base


def snapshot(bars: Sequence[dict], spy_closes: Sequence[float] | None = None) -> dict:
    """Bundle commonly-used indicators into a single dict. Missing inputs
    produce None entries rather than raising."""
    cs = closes(bars)
    last = cs[-1] if cs else None
    snap = {
        "last": last,
        "sma20": sma(cs, 20),
        "sma50": sma(cs, 50),
        "rsi14": rsi(cs, 14),
        "swing_low_10": swing_low(bars, 10),
        "swing_low_20": swing_low(bars, 20),
        "swing_high_10": swing_high(bars, 10),
        "swing_high_20": swing_high(bars, 20),
        "range_pct_15": range_pct(bars, 15),
        "consec_down": consecutive_down_days(bars[-6:]) if len(bars) >= 2 else 0,
        "gap_pct": gap_pct(bars),
        "volume_spike": volume_spike(bars, 20),
        "avg_vol_20": avg_volume(bars, 20),
        "sma20_slope": trend_slope([sma(cs[: i + 1], 20) or 0 for i in range(max(0, len(cs) - 5), len(cs))], 4),
    }
    if spy_closes is not None:
        snap["rs_vs_spy_20"] = relative_strength(cs, spy_closes, 20)
    return snap
