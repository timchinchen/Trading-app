"""Regression tests: the daily-loss circuit breaker must see realized P/L.

Previously _today_realized_pl read the `Trade` table, which no code path ever
writes, so realized P/L was always $0 and AGENT_DAILY_LOSS_CAP_USD never
engaged. It now sources fills from executed AgentTrade rows (preferring the
reconciled Order fill price). These tests use a real in-memory DB so the
join/query is exercised end to end.

Run with: python3 -m pytest backend/tests/test_daily_loss_cap_realized_pl.py -v
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AgentTrade, Order
from app.services.agent.runner import _today_realized_pl


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


def _at(db, sym, side, qty, est_price, minutes_ago, mode="paper", order_id=None):
    db.add(AgentTrade(
        run_id=1, order_id=order_id, symbol=sym, side=side, qty=qty,
        est_price=est_price, notional=qty * est_price, action="executed",
        mode=mode, created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    ))


def test_round_trip_profit_seen(db):
    """Buy 1@100, sell 1@120 today -> realized +20 (was $0 under the old code)."""
    _at(db, "AAPL", "buy", 1.0, 100.0, minutes_ago=60)
    _at(db, "AAPL", "sell", 1.0, 120.0, minutes_ago=30)
    db.commit()
    assert _today_realized_pl(db, "paper") == pytest.approx(20.0)


def test_round_trip_loss_seen(db):
    """A losing round-trip must produce a negative number so the cap can trip."""
    _at(db, "TSLA", "buy", 1.0, 100.0, minutes_ago=60)
    _at(db, "TSLA", "sell", 1.0, 82.0, minutes_ago=30)
    db.commit()
    assert _today_realized_pl(db, "paper") == pytest.approx(-18.0)


def test_no_fills_is_zero(db):
    assert _today_realized_pl(db, "paper") == pytest.approx(0.0)


def test_prefers_reconciled_order_fill_price(db):
    """When the Order has a reconciled fill price it wins over est_price."""
    buy_order = Order(alpaca_id="b1", symbol="MSFT", qty=1.0, side="buy",
                      type="market", status="filled", mode="paper",
                      filled_avg_price=100.0, filled_qty=1.0,
                      filled_at=datetime.utcnow() - timedelta(minutes=60))
    sell_order = Order(alpaca_id="s1", symbol="MSFT", qty=1.0, side="sell",
                       type="market", status="filled", mode="paper",
                       filled_avg_price=110.0, filled_qty=1.0,
                       filled_at=datetime.utcnow() - timedelta(minutes=30))
    db.add_all([buy_order, sell_order])
    db.flush()
    # est_price deliberately wrong (0) to prove the fill price is preferred.
    _at(db, "MSFT", "buy", 1.0, 0.0, minutes_ago=60, order_id=buy_order.id)
    _at(db, "MSFT", "sell", 1.0, 0.0, minutes_ago=30, order_id=sell_order.id)
    db.commit()
    assert _today_realized_pl(db, "paper") == pytest.approx(10.0)


def test_open_buy_not_counted(db):
    """An un-closed buy today contributes no realized P/L."""
    _at(db, "NVDA", "buy", 2.0, 100.0, minutes_ago=30)
    db.commit()
    assert _today_realized_pl(db, "paper") == pytest.approx(0.0)


def test_mode_isolation(db):
    """Paper fills must not leak into a live P/L calc."""
    _at(db, "AAPL", "buy", 1.0, 100.0, minutes_ago=60, mode="paper")
    _at(db, "AAPL", "sell", 1.0, 130.0, minutes_ago=30, mode="paper")
    db.commit()
    assert _today_realized_pl(db, "live") == pytest.approx(0.0)
    assert _today_realized_pl(db, "paper") == pytest.approx(30.0)
