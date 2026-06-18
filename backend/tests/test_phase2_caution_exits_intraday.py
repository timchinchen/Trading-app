"""Unit tests for the follow-up upgrade phases:
  - CAUTION-tier execution (half-size, stricter R/R, corroboration)
  - Plan backfill for un-planned positions
  - Thesis-invalidation exits (2-close soft, confirmed first-close)
  - Optional intraday confirmation (disabled no-op, weakness downgrade, unavailable safe)

Run with: python -m pytest tests/test_phase2_caution_exits_intraday.py -v
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.agent import swing_runner
from app.services.agent.swing_analyzer import SetupPlan


# ---------------------------------------------------------------------------
# CAUTION-tier execution in build_swing_proposals
# ---------------------------------------------------------------------------
def _plan(sym="AAPL", entry=100.0, stop=95.0, target=115.0):
    rr = round((target - entry) / (entry - stop), 2)
    return SetupPlan(symbol=sym, setup="breakout", entry=entry, stop=stop,
                     target=target, rr=rr, note="test setup", indicators={})


BUILD_BASE = dict(
    signals={},
    open_symbols=set(),
    recently_bought={},
    budget_remaining=1000.0,
    weekly_remaining=5000.0,
    total_capital_usd=1000.0,
    risk_pct=0.01,
    min_rr=2.5,
    min_position_usd=20.0,
    max_position_usd=500.0,
    max_open_positions=6,
    regime_go=True,
)


def _buy(props):
    return next(p for p in props if p["side"] == "buy" and p["action"] == "proposed")


class TestCautionSizing:
    def test_caution_halves_notional_vs_go(self):
        plans = {"AAPL": _plan()}
        go = _buy(swing_runner.build_swing_proposals(plans, regime_tier="go", **BUILD_BASE))
        caution = _buy(swing_runner.build_swing_proposals(
            plans, regime_tier="caution", caution_size_mult=0.5, caution_min_rr=2.5, **BUILD_BASE,
        ))
        assert caution["notional"] == pytest.approx(go["notional"] * 0.5, rel=0.02)
        assert "CAUTION" in caution["reason"]

    def test_caution_stricter_rr_rejects_marginal_setup(self):
        # R/R = 3.0 exactly; caution floor 3.5 should reject it.
        plans = {"AAPL": _plan(entry=100, stop=95, target=115)}  # rr=3.0
        props = swing_runner.build_swing_proposals(
            plans, regime_tier="caution", caution_min_rr=3.5, **BUILD_BASE,
        )
        buys_proposed = [p for p in props if p["side"] == "buy" and p["action"] == "proposed"]
        assert buys_proposed == []
        skipped = [p for p in props if p["action"] == "skipped"]
        assert skipped and "CAUTION R/R floor" in skipped[0]["reason"]

    def test_caution_requires_corroboration_when_enabled(self):
        plans = {"AAPL": _plan()}
        # No tweet signal for AAPL → should be skipped when corroboration required.
        props = swing_runner.build_swing_proposals(
            plans, regime_tier="caution", caution_min_rr=2.5,
            caution_require_corroboration=True, **BUILD_BASE,
        )
        assert [p for p in props if p["action"] == "proposed"] == []
        assert any("corroboration" in p["reason"] for p in props if p["action"] == "skipped")

    def test_caution_corroboration_satisfied_by_positive_signal(self):
        plans = {"AAPL": _plan()}
        base = {**BUILD_BASE, "signals": {"AAPL": {"score": 0.6, "confidence": 0.7,
                                                    "mentions": 2, "corroborated_by": []}}}
        props = swing_runner.build_swing_proposals(
            plans, regime_tier="caution", caution_min_rr=2.5,
            caution_require_corroboration=True, **base,
        )
        assert _buy(props)["symbol"] == "AAPL"

    def test_go_unaffected_by_caution_params(self):
        plans = {"AAPL": _plan()}
        props = swing_runner.build_swing_proposals(
            plans, regime_tier="go", caution_size_mult=0.5, caution_min_rr=9.0,
            caution_require_corroboration=True, **BUILD_BASE,
        )
        assert _buy(props)["symbol"] == "AAPL"  # GO ignores all caution gating


# ---------------------------------------------------------------------------
# Plan backfill
# ---------------------------------------------------------------------------
class _Broker:
    def __init__(self, positions=None, daily=None, intraday=None):
        self._positions = positions or []
        self._daily = daily or {}
        self._intraday = intraday or []
        self.configured = True

    def positions(self):
        return self._positions

    def fetch_daily_bars(self, syms, lookback_days=120):
        return {s.upper(): self._daily.get(s.upper(), []) for s in syms}

    def fetch_intraday_bars(self, symbol, timeframe="1Min", lookback_minutes=390):
        return self._intraday


def _db_with_plans(plans):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = plans
    db.commit.return_value = None
    return db


class TestPlanBackfill:
    def test_creates_plan_for_unplanned_position(self):
        broker = _Broker(positions=[{"symbol": "RKLB", "qty": 3.0, "avg_entry_price": 20.0,
                                     "current_price": 19.0}])
        db = _db_with_plans([])  # no existing open plans
        created = swing_runner.backfill_position_plans(
            broker, db, mode="paper", default_stop_pct=0.05, default_target_pct=0.10,
        )
        assert created == 1
        db.add.assert_called_once()

    def test_skips_position_that_already_has_plan(self):
        existing = MagicMock(); existing.symbol = "RKLB"; existing.status = "open"
        broker = _Broker(positions=[{"symbol": "RKLB", "qty": 3.0, "avg_entry_price": 20.0}])
        db = _db_with_plans([existing])
        created = swing_runner.backfill_position_plans(
            broker, db, mode="paper", default_stop_pct=0.05, default_target_pct=0.10,
        )
        assert created == 0


# ---------------------------------------------------------------------------
# Thesis-invalidation exits
# ---------------------------------------------------------------------------
def _daily(closes, lows=None, vols=None):
    out = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i, c in enumerate(closes):
        low = (lows[i] if lows else c - 1.0)
        out.append({"t": (base + timedelta(days=i)).isoformat(),
                    "o": c, "h": c + 1.0, "l": low, "c": c,
                    "v": (vols[i] if vols else 1000)})
    return out


def _plan_row(sym="X", setup="trend_pullback", entry=100.0, stop=90.0, target=120.0):
    p = MagicMock()
    p.symbol = sym; p.setup_type = setup; p.entry_price = entry
    p.stop_price = stop; p.target_price = target; p.risk_reward = 3.0
    p.status = "open"; p.notes = ""
    return p


def _inval_db(plans):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = plans
    db.commit.return_value = None
    return db


class TestInvalidationExits:
    def test_two_closes_below_sma_triggers_soft_exit(self):
        # 20 closes ~110 then 2 closes well below the SMA20.
        closes = [110.0] * 20 + [95.0, 94.0]
        broker = _Broker(positions=[{"symbol": "X", "qty": 2.0, "current_price": 94.0}],
                         daily={"X": _daily(closes)})
        db = _inval_db([_plan_row("X")])
        props = swing_runner.invalidation_exit_proposals(
            broker, db, lookback_days=120, sma_period=20, consec_closes=2,
            first_close_on_confirmed=False,
        )
        assert len(props) == 1
        assert props[0]["exit_type"] == "invalidation"
        assert "consecutive" in props[0]["reason"]

    def test_single_close_below_sma_no_exit_without_confirmation(self):
        # Only the last close dips below SMA; prior close still above; not confirmed.
        closes = [110.0] * 21 + [95.0]
        broker = _Broker(positions=[{"symbol": "X", "qty": 2.0, "current_price": 95.0}],
                         daily={"X": _daily(closes)})
        db = _inval_db([_plan_row("X")])
        props = swing_runner.invalidation_exit_proposals(
            broker, db, lookback_days=120, sma_period=20, consec_closes=2,
            first_close_on_confirmed=False,
        )
        assert props == []

    def test_confirmed_failed_breakout_first_close_exit(self):
        # Breakout entry 100; price now below SMA and below entry on a single close,
        # closing below the prior bar's low → confirmed weakness.
        closes = [110.0] * 21 + [98.0]
        lows = [109.0] * 21 + [97.0]  # last close 98 < prior low 109
        broker = _Broker(positions=[{"symbol": "X", "qty": 2.0, "current_price": 98.0}],
                         daily={"X": _daily(closes, lows=lows)})
        db = _inval_db([_plan_row("X", setup="breakout", entry=100.0)])
        props = swing_runner.invalidation_exit_proposals(
            broker, db, lookback_days=120, sma_period=20, consec_closes=2,
            first_close_on_confirmed=True,
        )
        assert len(props) == 1
        assert "failed breakout" in props[0]["reason"] or "decisive break" in props[0]["reason"]

    def test_healthy_position_above_sma_no_exit(self):
        closes = [100.0 + i for i in range(25)]  # steady uptrend, last well above SMA20
        broker = _Broker(positions=[{"symbol": "X", "qty": 2.0, "current_price": closes[-1]}],
                         daily={"X": _daily(closes)})
        db = _inval_db([_plan_row("X")])
        props = swing_runner.invalidation_exit_proposals(
            broker, db, lookback_days=120, sma_period=20, consec_closes=2,
        )
        assert props == []

    def test_already_selling_symbol_skipped(self):
        closes = [110.0] * 20 + [95.0, 94.0]
        broker = _Broker(positions=[{"symbol": "X", "qty": 2.0, "current_price": 94.0}],
                         daily={"X": _daily(closes)})
        db = _inval_db([_plan_row("X")])
        props = swing_runner.invalidation_exit_proposals(
            broker, db, lookback_days=120, sma_period=20, consec_closes=2,
            existing_sell_symbols={"X"},
        )
        assert props == []


# ---------------------------------------------------------------------------
# Intraday confirmation
# ---------------------------------------------------------------------------
def _fresh_daily_uptrend(n=80):
    out = []
    base = datetime.now(timezone.utc) - timedelta(days=n - 1)
    price = 100.0
    for i in range(n):
        c = price + 1.0
        out.append({"t": (base + timedelta(days=i)).isoformat(),
                    "o": price, "h": c + 0.5, "l": price - 0.5, "c": c, "v": 1_000_000})
        price = c
    return out


def _intraday_weak(n=120):
    # Downward-sloping 1-min closes so price < MA20 and MA20 < MA50 (weak).
    out = []
    base = datetime.now(timezone.utc) - timedelta(minutes=n)
    price = 200.0
    for i in range(n):
        c = price - 0.1
        out.append({"t": (base + timedelta(minutes=i)).isoformat(),
                    "o": price, "h": price + 0.05, "l": c - 0.05, "c": c, "v": 5000})
        price = c
    return out


class _DailyBroker:
    def __init__(self, daily, intraday=None):
        self._daily = daily
        self._intraday = intraday if intraday is not None else []
        self.configured = True

    def fetch_daily_bars(self, syms, lookback_days=120):
        return {syms[0].upper(): self._daily}

    def fetch_intraday_bars(self, symbol, timeframe="1Min", lookback_minutes=390):
        return self._intraday


class TestIntradayConfirmation:
    def test_disabled_is_noop(self):
        b = _DailyBroker(_fresh_daily_uptrend())
        r = swing_runner.evaluate_market_regime(
            b, filter_symbol="SPY", ma=50, lookback_days=120, use_intraday=False,
        )
        assert r["state"] == "go"
        assert "intraday" not in r

    def test_weak_intraday_downgrades_go_to_caution(self):
        b = _DailyBroker(_fresh_daily_uptrend(), intraday=_intraday_weak())
        r = swing_runner.evaluate_market_regime(
            b, filter_symbol="SPY", ma=50, lookback_days=120, use_intraday=True,
        )
        assert r["state"] == "caution"
        assert r["intraday"]["available"] is True
        assert r["intraday"]["weak"] is True

    def test_unavailable_intraday_does_not_block_or_downgrade(self):
        # Empty intraday → not available → daily GO preserved, data still complete.
        b = _DailyBroker(_fresh_daily_uptrend(), intraday=[])
        r = swing_runner.evaluate_market_regime(
            b, filter_symbol="SPY", ma=50, lookback_days=120, use_intraday=True,
        )
        assert r["state"] == "go"
        assert r["data_complete"] is True
        assert r["intraday"]["available"] is False

    def test_intraday_ma_cross_reported(self):
        b = _DailyBroker(_fresh_daily_uptrend(), intraday=_intraday_weak())
        r = swing_runner.evaluate_market_regime(
            b, filter_symbol="SPY", ma=50, lookback_days=120, use_intraday=True,
        )
        assert r["intraday"]["cross"] in ("bullish", "bearish", "flat")
        assert r["intraday"]["ma20"] is not None and r["intraday"]["ma50"] is not None


def test_fetch_intraday_bars_unconfigured_returns_empty():
    from app.services.broker import AlpacaBroker
    b = AlpacaBroker.__new__(AlpacaBroker)
    b.mode = "paper"
    b._client = None
    assert b.fetch_intraday_bars("SPY") == []
