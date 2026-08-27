"""Regression tests for the v1.4.0 agent exit-mechanics fixes.

Covers the review's issues #1 (holding-period), #2 (backfill breached stops),
#3 (minimum-hold guard), #5 (CAUTION size clamp), #6 (post-sell cooldown),
#7 (breakeven trigger), #8 (percent coercion + shadow defaults).

Run with: python3 -m pytest backend/tests/test_exit_mechanics_v140.py -v
"""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AgentTrade, Order
from app.services.agent.position_age import open_lot_opened_at, LOT_EPSILON


# ---------------------------------------------------------------------------
# Real in-memory DB fixture (the position-age walk runs live queries).
# ---------------------------------------------------------------------------
@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _buy(db, sym, qty, when, mode="paper", order_id=None):
    db.add(AgentTrade(
        run_id=1, symbol=sym, side="buy", qty=qty, est_price=10.0,
        notional=qty * 10.0, action="executed", mode=mode,
        created_at=when, order_id=order_id,
    ))


def _sell(db, sym, qty, when, mode="paper", order_id=None):
    db.add(AgentTrade(
        run_id=1, symbol=sym, side="sell", qty=qty, est_price=10.0,
        notional=qty * 10.0, action="executed", mode=mode,
        created_at=when, order_id=order_id,
    ))


# ===========================================================================
# #1 — holding period from the currently-open lot, not the oldest-ever buy
# ===========================================================================
class TestOpenLotOpenedAt:
    def test_buy_full_sell_rebuy_age_is_recent(self, db):
        """The exact bug: buy in June, fully sell, re-buy yesterday must read as
        ~1 day old — not ~60 days from the original buy."""
        june = datetime.utcnow() - timedelta(days=60)
        yesterday = datetime.utcnow() - timedelta(days=1)
        _buy(db, "XOM", 1.0, june)
        _sell(db, "XOM", 1.0, june + timedelta(days=2))
        _buy(db, "XOM", 1.0, yesterday)
        db.commit()

        opened = open_lot_opened_at(db, "XOM", "paper")
        assert opened is not None
        age_days = (datetime.utcnow() - opened).total_seconds() / 86400.0
        assert age_days < 1.5  # re-buy lot, not the 60-day-old original

    def test_flat_position_returns_none(self, db):
        t0 = datetime.utcnow() - timedelta(days=5)
        _buy(db, "AAPL", 2.0, t0)
        _sell(db, "AAPL", 2.0, t0 + timedelta(hours=1))
        db.commit()
        assert open_lot_opened_at(db, "AAPL", "paper") is None

    def test_no_lineage_returns_none(self, db):
        assert open_lot_opened_at(db, "NADA", "paper") is None

    def test_fractional_dust_below_epsilon_is_flat(self, db):
        """A partial sell leaving sub-epsilon dust must NOT keep the lot open —
        the old 1e-6 epsilon left 0.0004-share dust 'open' forever."""
        t0 = datetime.utcnow() - timedelta(days=5)
        _buy(db, "TNGX", 1.0, t0)
        _sell(db, "TNGX", 1.0 - (LOT_EPSILON / 2), t0 + timedelta(hours=1))
        db.commit()
        assert open_lot_opened_at(db, "TNGX", "paper") is None

    def test_case_insensitive_side(self, db):
        """Upper-case 'BUY' must count as a buy, not be miscounted as a sell."""
        t0 = datetime.utcnow() - timedelta(days=2)
        db.add(AgentTrade(
            run_id=1, symbol="BBW", side="BUY", qty=1.0, est_price=10.0,
            notional=10.0, action="executed", mode="paper", created_at=t0,
        ))
        db.commit()
        opened = open_lot_opened_at(db, "BBW", "paper")
        assert opened is not None

    def test_agenttrade_visible_without_trade_row(self, db):
        """auto-sell writes AgentTrade+Order but no Trade row; the walk must
        still see the fills (the merged ledger)."""
        t0 = datetime.utcnow() - timedelta(days=3)
        _buy(db, "INOD", 1.0, t0)
        db.commit()
        assert open_lot_opened_at(db, "INOD", "paper") is not None

    def test_dedup_on_broker_order_id(self, db):
        """A fill recorded as both a Trade and an AgentTrade (same broker order
        id) must be counted once. Here we only have AgentTrade+Order, but two
        AgentTrade rows sharing an order id should not double-count."""
        t0 = datetime.utcnow() - timedelta(days=4)
        order = Order(alpaca_id="abc123", symbol="AMD", qty=1.0, side="buy",
                      type="market", status="filled", mode="paper")
        db.add(order)
        db.flush()
        _buy(db, "AMD", 1.0, t0, order_id=order.id)
        db.commit()
        opened = open_lot_opened_at(db, "AMD", "paper")
        assert opened is not None


# ===========================================================================
# #8 — percent coercion + shadow-default alignment
# ===========================================================================
class TestSettingsCoercion:
    def test_coerce_whole_percent(self):
        from app.services.settings_store import _coerce_pct
        assert _coerce_pct(30) == pytest.approx(0.30)
        assert _coerce_pct(7) == pytest.approx(0.07)

    def test_coerce_fraction_passthrough(self):
        from app.services.settings_store import _coerce_pct
        assert _coerce_pct(0.30) == pytest.approx(0.30)

    def test_coerce_bad_input_zero(self):
        from app.services.settings_store import _coerce_pct
        assert _coerce_pct("nonsense") == 0.0

    def test_shadow_defaults_match_config(self):
        """RuntimeSettings dataclass defaults must not drift from config.py."""
        from app.config import settings as env
        from app.services.settings_store import RuntimeSettings
        rs = RuntimeSettings()
        assert rs.agent_trail_arm_pct == pytest.approx(env.AGENT_TRAIL_ARM_PCT)
        assert rs.agent_trail_retrace_pct == pytest.approx(env.AGENT_TRAIL_RETRACE_PCT)
        assert rs.agent_partial_take_pct == pytest.approx(env.AGENT_PARTIAL_TAKE_PCT)
        assert rs.auto_sell_max_hold_days == env.AUTO_SELL_MAX_HOLD_DAYS


# ===========================================================================
# #5 — CAUTION size_mult applied before the min/max clamp
# ===========================================================================
class TestSizeMultBeforeClamp:
    def _plan(self, entry=100.0, stop=95.0, target=110.0):
        from app.services.agent.swing_analyzer import SetupPlan
        return SetupPlan(symbol="X", setup="breakout", entry=entry, stop=stop,
                         target=target, rr=2.0, note="", indicators={})

    def test_half_size_lands_on_floor_not_discarded(self):
        from app.services.agent import swing_analyzer
        plan = self._plan()
        # risk_usd = 200 * 0.01 = $2; risk/share = $5 -> raw 0.4 sh = $40.
        # Half size => $20, exactly the floor. Old code clamped up to $20 THEN
        # halved to $10 and discarded; new code multiplies first -> $20 stands.
        sizing = swing_analyzer.size_plan(
            plan, total_capital_usd=200.0, risk_pct=0.01,
            min_position_usd=20.0, max_position_usd=40.0, min_rr=1.5,
            size_mult=0.5,
        )
        assert not sizing["rejected"]
        assert sizing["notional"] == pytest.approx(20.0)

    def test_full_size_unaffected(self):
        from app.services.agent import swing_analyzer
        plan = self._plan()
        sizing = swing_analyzer.size_plan(
            plan, total_capital_usd=200.0, risk_pct=0.01,
            min_position_usd=20.0, max_position_usd=40.0, min_rr=1.5,
            size_mult=1.0,
        )
        assert sizing["notional"] == pytest.approx(40.0)


# ===========================================================================
# #2 — backfill must not synthesise an already-breached stop
# ===========================================================================
class TestBackfillStopAnchor:
    class _Broker:
        def __init__(self, positions):
            self._positions = positions
            self.configured = True

        def positions(self):
            return self._positions

    def _db(self, existing_plans):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = existing_plans
        db.commit.return_value = None
        return db

    def test_breached_stop_anchored_below_current(self):
        from app.services.agent import swing_runner
        captured = {}

        def _capture(row):
            captured["row"] = row

        # entry 20, current 19 (5% down). Entry-based 5% stop = 19.00, which is
        # >= current -> would trip STOP HIT immediately. Must anchor below 19.
        broker = self._Broker([{"symbol": "RKLB", "qty": 3.0,
                                "avg_entry_price": 20.0, "current_price": 19.0}])
        db = self._db([])
        db.add.side_effect = _capture
        created = swing_runner.backfill_position_plans(
            broker, db, mode="paper", default_stop_pct=0.05,
            default_target_pct=0.10, current_run_id=7,
        )
        assert created == 1
        row = captured["row"]
        assert row.stop_price < 19.0            # anchored below current price
        assert row.created_run_id == 7          # tagged for same-run guard


# ===========================================================================
# #6 — re-entry cooldown covers sells (post-sell), not just buys
# ===========================================================================
class TestRecentlyTradedIncludesSells:
    def test_recent_sell_is_returned(self):
        from app.services.agent.runner import _recently_traded_symbols
        sell = MagicMock()
        sell.symbol = "NVDA"
        sell.side = "sell"
        sell.est_price = 100.0
        sell.created_at = datetime.utcnow() - timedelta(hours=1)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [sell]
        out = _recently_traded_symbols(db, "paper", 24)
        assert "NVDA" in out
        assert out["NVDA"]["side"] == "sell"


# ===========================================================================
# #7 — breakeven trigger scales with distance to target
# ===========================================================================
class TestBreakevenTargetFraction:
    class _Broker:
        def __init__(self, positions):
            self._positions = positions
            self.configured = True

        def positions(self):
            return self._positions

    def _plan_row(self, entry=100.0, stop=95.0, target=110.0):
        p = MagicMock()
        p.symbol = "X"
        p.setup_type = "breakout"
        p.entry_price = entry
        p.stop_price = stop
        p.target_price = target
        p.risk_reward = 2.0
        p.opened_at = datetime.utcnow() - timedelta(days=2)
        p.created_run_id = None
        p.breakeven_moved = 0
        p.partial_taken = 0
        p.status = "open"
        p.notes = ""
        return p

    def _db(self, plans):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = plans
        db.commit.return_value = None
        return db

    @patch("app.services.agent.position_age.open_lot_opened_at")
    def test_breakeven_fires_at_half_to_target_not_absolute_pct(self, age):
        from app.services.agent import swing_runner
        age.return_value = datetime.utcnow() - timedelta(days=2)
        # entry 100, target 110 -> halfway = +5%. At +6% price=106 breakeven
        # should move even though the legacy absolute pct default is 8%.
        plan = self._plan_row(entry=100.0, target=110.0)
        broker = self._Broker([{"symbol": "X", "qty": 1.0, "current_price": 106.0}])
        db = self._db([plan])
        swing_runner.trade_management_pass(
            broker, db, mode="paper", time_stop_days=10,
            move_stop_be_pct=0.08, partial_pct=0.05,
            move_stop_be_target_frac=0.5, min_hold_hours=0,
        )
        assert plan.breakeven_moved == 1
        assert plan.stop_price == pytest.approx(100.0)  # raised to entry


# ===========================================================================
# #3 — minimum-hold guard blocks non-hard-stop exits, hard stop still fires
# ===========================================================================
class TestMinHoldGuard:
    def _pos(self, sym, qty=1.0, current=105.0, plpc=0.05, entry=100.0):
        return {"symbol": sym, "qty": qty, "current_price": current,
                "unrealized_plpc": plpc, "avg_entry_price": entry}

    def _broker(self, positions):
        b = MagicMock()
        b.configured = True
        b.positions.return_value = positions
        return b

    def _plan(self, sym, stop=90.0, entry=100.0, target=120.0, peak=0.0):
        p = MagicMock()
        p.symbol = sym
        p.stop_price = stop
        p.entry_price = entry
        p.target_price = target
        p.opened_at = datetime.utcnow() - timedelta(hours=1)
        p.created_run_id = None
        p.partial_taken = 0
        p.peak_unrealized_plpc = peak
        p.status = "open"
        return p

    def _db(self, plans):
        db = MagicMock()
        chain = db.query.return_value.filter.return_value
        chain.all.return_value = plans
        chain.order_by.return_value.first.return_value = None
        db.commit.return_value = None
        return db

    BASE = dict(mode="paper", max_hold_days=8, trail_arm_pct=0.05,
                trail_retrace_pct=0.35, partial_take_pct=0.07,
                partial_take_fraction=0.5, existing_sell_symbols=set(),
                min_hold_hours=24)

    @patch("app.services.agent.position_age.open_lot_opened_at")
    def test_partial_tp_suppressed_within_min_hold(self, age):
        from app.services.agent.runner import _adaptive_exit_proposals
        age.return_value = datetime.utcnow() - timedelta(hours=1)  # < 24h
        broker = self._broker([self._pos("AMD", current=108.0, plpc=0.08)])
        db = self._db([self._plan("AMD", stop=80.0)])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE)
        assert props == []  # partial-TP would normally fire; suppressed

    @patch("app.services.agent.position_age.open_lot_opened_at")
    def test_hard_stop_still_fires_within_min_hold(self, age):
        from app.services.agent.runner import _adaptive_exit_proposals
        age.return_value = datetime.utcnow() - timedelta(hours=1)  # < 24h
        broker = self._broker([self._pos("AMD", current=79.0, plpc=-0.21)])
        db = self._db([self._plan("AMD", stop=80.0)])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE)
        assert len(props) == 1
        assert "hard-stop" in props[0]["reason"]

    @patch("app.services.agent.position_age.open_lot_opened_at")
    def test_same_run_plan_not_exited(self, age):
        from app.services.agent.runner import _adaptive_exit_proposals
        age.return_value = datetime.utcnow() - timedelta(days=2)
        plan = self._plan("AMD", stop=80.0)
        plan.created_run_id = 42
        broker = self._broker([self._pos("AMD", current=79.0, plpc=-0.21)])
        db = self._db([plan])
        kwargs = {**self.BASE, "min_hold_hours": 0, "current_run_id": 42}
        props = _adaptive_exit_proposals(broker, db=db, **kwargs)
        assert props == []  # plan created this run -> skip even a hard stop
