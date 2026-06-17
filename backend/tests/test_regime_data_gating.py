"""Unit tests for the regime data-gating / "confirm first, then execute" upgrade.

Covers:
  - swing_analyzer.market_regime three-state classification + data completeness
  - 20/50 DMA cross detection
  - swing_runner.evaluate_market_regime staleness handling
  - runner.resolve_buy_policy buy gate + position focus

Run with: python -m pytest tests/test_regime_data_gating.py -v
No database or broker required.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.agent import swing_analyzer, swing_runner
from app.services.agent.runner import resolve_buy_policy


def _bars(start: float, step: float, n: int, vol: int = 1000) -> list[dict]:
    """Synthetic daily bars trending by `step` each bar."""
    bars = []
    price = start
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        o = price
        c = price + step
        bars.append({
            "t": (base + timedelta(days=i)).isoformat(),
            "o": o, "h": max(o, c) + 0.5, "l": min(o, c) - 0.5,
            "c": c, "v": vol,
        })
        price = c
    return bars


# ---------------------------------------------------------------------------
# market_regime — three-state classification
# ---------------------------------------------------------------------------
class TestMarketRegimeStates:
    def test_uptrend_is_go(self):
        r = swing_analyzer.market_regime(_bars(100, 1.0, 80), ma=50)
        assert r["state"] == "go"
        assert r["go"] is True
        assert r["data_complete"] is True

    def test_downtrend_is_no_go(self):
        r = swing_analyzer.market_regime(_bars(200, -1.0, 80), ma=50)
        assert r["state"] == "no_go"
        assert r["go"] is False
        assert r["data_complete"] is True

    def test_mixed_is_caution(self):
        # Long rising base (so SMA50 is rising / price above it) then a sharp
        # pullback below SMA20 — price still above SMA50 but below SMA20 → mixed.
        bars = _bars(100, 1.0, 70)
        # Tack on a few down bars that dip below the short MA but not the long.
        last_c = bars[-1]["c"]
        base = datetime(2024, 6, 1, tzinfo=timezone.utc)
        for i in range(4):
            o = last_c
            c = last_c - 6.0
            bars.append({
                "t": (base + timedelta(days=i)).isoformat(),
                "o": o, "h": o + 0.5, "l": c - 0.5, "c": c, "v": 1000,
            })
            last_c = c
        r = swing_analyzer.market_regime(bars, ma=50)
        assert r["state"] == "caution"
        assert r["go"] is False
        assert r["data_complete"] is True

    def test_insufficient_history_marks_incomplete(self):
        r = swing_analyzer.market_regime(_bars(100, 1.0, 10), ma=50)
        assert r["data_complete"] is False
        assert any("history" in i for i in r["data_issues"])

    def test_zero_volume_tail_marks_incomplete(self):
        bars = _bars(100, 1.0, 80)
        for b in bars[-3:]:
            b["v"] = 0
        r = swing_analyzer.market_regime(bars, ma=50)
        assert r["data_complete"] is False
        assert any("volume" in i for i in r["data_issues"])
        # Trend state is still computed; gating is the caller's job.
        assert r["state"] in ("go", "caution", "no_go")

    def test_data_complete_with_volume_present(self):
        r = swing_analyzer.market_regime(_bars(100, 1.0, 80), ma=50)
        assert r["data_complete"] is True
        assert r["data_issues"] == []


# ---------------------------------------------------------------------------
# market_regime — 20/50 DMA cross
# ---------------------------------------------------------------------------
class TestMaCross:
    def test_bullish_cross_label_when_uptrend(self):
        r = swing_analyzer.market_regime(_bars(100, 1.0, 80), ma=50)
        assert r["ma_cross"] == "bullish"

    def test_bearish_cross_label_when_downtrend(self):
        r = swing_analyzer.market_regime(_bars(200, -1.0, 80), ma=50)
        assert r["ma_cross"] == "bearish"

    def test_golden_cross_event_detected(self):
        # Down for a long stretch (20DMA below 50DMA), then a sharp rally that
        # eventually pulls the 20DMA back above the 50DMA. The event only fires
        # on the *fresh* cross (within ~3 bars), so truncate the series right at
        # the crossover bar to assert detection.
        bars = _bars(200, -1.0, 60)
        last_c = bars[-1]["c"]
        base = datetime(2024, 5, 1, tzinfo=timezone.utc)
        for i in range(40):
            o = last_c
            c = last_c + 6.0
            bars.append({
                "t": (base + timedelta(days=i)).isoformat(),
                "o": o, "h": c + 0.5, "l": o - 0.5, "c": c, "v": 1000,
            })
            last_c = c
        # Scan truncations; at least one must report the golden-cross event.
        events = [
            swing_analyzer.market_regime(bars[: 60 + k], ma=50)["ma_cross_event"]
            for k in range(1, 40)
        ]
        assert "golden_cross" in events
        # And the final state is a bullish 20/50 alignment.
        assert swing_analyzer.market_regime(bars, ma=50)["ma_cross"] == "bullish"


# ---------------------------------------------------------------------------
# evaluate_market_regime — staleness + missing bars
# ---------------------------------------------------------------------------
class _Broker:
    def __init__(self, bars):
        self._bars = bars

    def fetch_daily_bars(self, syms, lookback_days=120):
        if self._bars is None:
            return {}
        return {syms[0].upper(): self._bars}


def _fresh_bars(n=80):
    """Bars whose most recent timestamp is today (not stale)."""
    bars = _bars(100, 1.0, n)
    base = datetime.now(timezone.utc) - timedelta(days=n - 1)
    for i, b in enumerate(bars):
        b["t"] = (base + timedelta(days=i)).isoformat()
    return bars


class TestEvaluateMarketRegime:
    def test_missing_bars_is_no_go_data_incomplete(self):
        r = swing_runner.evaluate_market_regime(
            _Broker(None), filter_symbol="SPY", ma=50, lookback_days=120,
        )
        assert r["state"] == "no_go"
        assert r["data_complete"] is False

    def test_fresh_uptrend_is_go_data_complete(self):
        r = swing_runner.evaluate_market_regime(
            _Broker(_fresh_bars()), filter_symbol="SPY", ma=50, lookback_days=120,
        )
        assert r["state"] == "go"
        assert r["data_complete"] is True

    def test_stale_bars_marked_incomplete(self):
        # Most recent bar is 30 days old → stale beyond the 4d default.
        r = swing_runner.evaluate_market_regime(
            _Broker(_bars(100, 1.0, 80)), filter_symbol="SPY", ma=50,
            lookback_days=120, stale_bars_days=4,
        )
        assert r["data_complete"] is False
        assert any("stale" in i.lower() or "old" in i.lower() for i in r["data_issues"])


# ---------------------------------------------------------------------------
# resolve_buy_policy — the hard buy gate
# ---------------------------------------------------------------------------
BASE = dict(
    require_regime_confirmation=True,
    require_complete_data_for_buys=True,
    legacy_go=True,
    max_open_positions=6,
    caution_max_open_positions=3,
)


class TestResolveBuyPolicy:
    def test_go_complete_allows_buys(self):
        p = resolve_buy_policy(regime_state="go", data_complete=True, **BASE)
        assert p["buys_allowed"] is True
        assert p["effective_max_open_positions"] == 6

    def test_caution_allows_buys_but_focuses_book(self):
        p = resolve_buy_policy(regime_state="caution", data_complete=True, **BASE)
        assert p["buys_allowed"] is True
        assert p["effective_max_open_positions"] == 3

    def test_no_go_blocks_buys(self):
        p = resolve_buy_policy(regime_state="no_go", data_complete=True, **BASE)
        assert p["buys_allowed"] is False
        assert "not GO/CAUTION" in p["block_reason"]

    def test_incomplete_data_blocks_buys_even_in_go(self):
        p = resolve_buy_policy(regime_state="go", data_complete=False, **BASE)
        assert p["buys_allowed"] is False
        assert p["data_ok"] is False
        assert "data incomplete" in p["block_reason"].lower()

    def test_data_gate_can_be_disabled(self):
        kw = {**BASE, "require_complete_data_for_buys": False}
        p = resolve_buy_policy(regime_state="go", data_complete=False, **kw)
        assert p["buys_allowed"] is True
        assert p["data_ok"] is True

    def test_legacy_gate_when_confirmation_disabled(self):
        # With confirmation off, CAUTION (legacy_go=False) blocks buys.
        kw = {**BASE, "require_regime_confirmation": False, "legacy_go": False}
        p = resolve_buy_policy(regime_state="caution", data_complete=True, **kw)
        assert p["buys_allowed"] is False

    def test_caution_zero_cap_falls_back_to_max(self):
        kw = {**BASE, "caution_max_open_positions": 0}
        p = resolve_buy_policy(regime_state="caution", data_complete=True, **kw)
        assert p["effective_max_open_positions"] == 6
