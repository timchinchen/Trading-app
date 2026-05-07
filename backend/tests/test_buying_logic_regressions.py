"""Regression tests for key buy-logic fixes."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings
from app.services.agent import swing_analyzer
from app.services.agent.runner import _classify_regime


class _BrokerStub:
    def __init__(self, bars):
        self._bars = bars

    def fetch_daily_bars(self, syms, lookback_days=120):
        return {syms[0].upper(): self._bars}


def _bars_with_trend(start: float, step: float, n: int) -> list[dict]:
    bars = []
    price = start
    for _ in range(n):
        o = price
        c = price + step
        bars.append({"o": o, "h": max(o, c) + 0.5, "l": min(o, c) - 0.5, "c": c, "v": 1000})
        price = c
    return bars


def test_classify_regime_executes_with_technicals_module_import():
    bars = _bars_with_trend(100, 1.0, 60)
    broker = _BrokerStub(bars)
    regime, mult = _classify_regime(
        broker,
        symbol="SPY",
        ma_period=50,
        lookback_days=120,
        risk_on_mult=1.25,
        neutral_mult=1.0,
        risk_off_mult=0.5,
    )
    assert regime == "risk_on"
    assert mult == 1.25


def test_oversold_setup_can_meet_default_min_rr():
    bars = [
        {"o": 101.0, "h": 101.2, "l": 98.8, "c": 99.0, "v": 1000},
        {"o": 99.2, "h": 100.6, "l": 99.1, "c": 100.0, "v": 1200},
    ]
    snap = {
        "rsi14": 25.0,
        "consec_down": 3,
        "last": 100.0,
        "swing_low_10": 96.5,
    }
    plan = swing_analyzer._oversold("AAPL", bars, snap)
    assert plan is not None
    assert plan.rr >= 2.5


def test_default_hold_horizon_targets_two_to_three_weeks():
    assert Settings.model_fields["AGENT_MAX_HOLD_DAYS"].default == 14
    assert Settings.model_fields["SWING_TIME_STOP_DAYS"].default == 10
