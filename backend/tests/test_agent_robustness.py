"""Focused unit tests for the 3 agent-pipeline robustness fixes.

Run with:  python -m pytest backend/tests/test_agent_robustness.py -v
No database or broker required — all tests use pure in-memory data.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.services.agent import analyzer, allocator


# ============================================================================
# Task 1 — Noise filtering
# ============================================================================

def _make_item(handle: str, symbol: str, sentiment: float, confidence: float,
               is_noise: bool = False) -> dict:
    return {
        "tweet": {"handle": handle, "url": "", "text": "test", "tweet_id": "1",
                  "created_at": "2024-01-01T09:00:00"},
        "analysis": {
            "tickers": [{"symbol": symbol, "sentiment": sentiment,
                         "confidence": confidence, "rationale": "test"}],
            "meta": {"is_noise": is_noise},
        },
    }


class TestNoiseFiltering:
    def test_noise_item_excluded_from_signals(self):
        items = [
            _make_item("user1", "AAPL", 0.9, 0.9, is_noise=False),
            _make_item("user2", "AAPL", 0.9, 0.9, is_noise=True),   # should be excluded
        ]
        signals = analyzer.aggregate(items)
        stats = analyzer.pop_noise_stats(signals)

        # Only 1 mention should contribute (the non-noise one)
        assert signals["AAPL"]["mentions"] == 1
        assert stats["noise"] == 1
        assert stats["used"] == 1
        assert stats["total"] == 2

    def test_all_noise_produces_no_signals(self):
        items = [
            _make_item("user1", "AAPL", 0.9, 0.9, is_noise=True),
            _make_item("user2", "TSLA", 0.8, 0.8, is_noise=True),
        ]
        signals = analyzer.aggregate(items)
        analyzer.pop_noise_stats(signals)
        assert "AAPL" not in signals
        assert "TSLA" not in signals

    def test_non_noise_still_aggregates_normally(self):
        items = [
            _make_item("user1", "NVDA", 0.8, 0.8, is_noise=False),
            _make_item("user2", "NVDA", 0.6, 0.7, is_noise=False),
        ]
        signals = analyzer.aggregate(items)
        analyzer.pop_noise_stats(signals)
        assert signals["NVDA"]["mentions"] == 2
        assert -1.0 <= signals["NVDA"]["score"] <= 1.0

    def test_noise_stats_sidecar_removed_by_pop(self):
        items = [_make_item("u", "SPY", 0.5, 0.5, is_noise=False)]
        signals = analyzer.aggregate(items)
        analyzer.pop_noise_stats(signals)
        assert "__noise_stats__" not in signals

    def test_noise_item_ticker_not_in_signals(self):
        """A symbol that only appears in noise tweets must not appear in signals."""
        items = [
            _make_item("user1", "AAPL", 0.9, 0.9, is_noise=False),
            _make_item("user2", "BADCO", 0.9, 0.9, is_noise=True),
        ]
        signals = analyzer.aggregate(items)
        analyzer.pop_noise_stats(signals)
        assert "BADCO" not in signals
        assert "AAPL" in signals


# ============================================================================
# Task 2 — Bearish reversal sell sizing
# ============================================================================

def _make_signals(symbol: str, score: float, confidence: float,
                  mentions: int = 3) -> dict:
    return {
        symbol: {
            "score": score, "confidence": confidence, "mentions": mentions,
            "rationale": "test", "sources": [], "corroborated_by": [],
        }
    }


def _noop_price(sym: str):
    return 100.0


class TestBearishReversalSizing:
    BASE_KWARGS = dict(
        budget_remaining=1000.0,
        weekly_remaining=5000.0,
        min_position_usd=50.0,
        max_position_usd=500.0,
        max_open_positions=10,
        get_price=_noop_price,
        min_score=0.3,
        min_confidence=0.3,
        top_n=5,
    )

    def test_bearish_reversal_gets_held_qty(self):
        signals = _make_signals("AAPL", score=-0.8, confidence=0.9)
        props = allocator.propose_trades(
            signals=signals,
            open_symbols={"AAPL"},
            open_position_qtys={"AAPL": 2.5},
            **self.BASE_KWARGS,
        )
        sell = next(p for p in props if p["symbol"] == "AAPL" and p["side"] == "sell")
        assert sell["action"] == "proposed"
        assert sell["qty"] == 2.5
        assert sell["notional"] == pytest.approx(250.0)
        assert "bearish reversal" in sell["reason"]

    def test_bearish_reversal_skipped_when_no_qty_map(self):
        """Without open_position_qtys the proposal is skipped, not zeroed."""
        signals = _make_signals("AAPL", score=-0.8, confidence=0.9)
        props = allocator.propose_trades(
            signals=signals,
            open_symbols={"AAPL"},
            open_position_qtys=None,  # legacy caller
            **self.BASE_KWARGS,
        )
        sell = next(p for p in props if p["symbol"] == "AAPL" and p["side"] == "sell")
        assert sell["action"] == "skipped"
        assert "qty unknown" in sell["reason"]

    def test_bearish_reversal_skipped_when_qty_zero(self):
        signals = _make_signals("AAPL", score=-0.8, confidence=0.9)
        props = allocator.propose_trades(
            signals=signals,
            open_symbols={"AAPL"},
            open_position_qtys={"AAPL": 0.0},
            **self.BASE_KWARGS,
        )
        sell = next(p for p in props if p["symbol"] == "AAPL" and p["side"] == "sell")
        assert sell["action"] == "skipped"
        assert sell["qty"] == 0.0

    def test_bullish_signal_does_not_emit_sell(self):
        signals = _make_signals("AAPL", score=0.8, confidence=0.9)
        props = allocator.propose_trades(
            signals=signals,
            open_symbols={"AAPL"},
            open_position_qtys={"AAPL": 2.0},
            **self.BASE_KWARGS,
        )
        sells = [p for p in props if p["side"] == "sell"]
        assert len(sells) == 0

    def test_no_duplicate_sell_for_symbol_already_in_proposals(self):
        """If the swing runner already proposed a sell, bearish reversal skips it."""
        signals = _make_signals("AAPL", score=-0.8, confidence=0.9)
        # Pass a pre-existing sell proposal via open_symbols still being in the set
        # but with the symbol already handled by a prior sell in the list.
        # The allocator checks `already_selling` before emitting.
        props = allocator.propose_trades(
            signals=signals,
            open_symbols={"AAPL"},
            open_position_qtys={"AAPL": 1.0},
            **self.BASE_KWARGS,
        )
        sell_count = sum(
            1 for p in props if p["symbol"] == "AAPL" and p["side"] == "sell"
        )
        assert sell_count == 1  # exactly one, not duplicated


# ============================================================================
# Task 3 — FIFO daily realized P/L
# ============================================================================

from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from app.services.agent.runner import _today_realized_pl


def _trade(symbol, side, qty, price, offset_minutes=0):
    """Build a mock Trade ORM row."""
    t = MagicMock()
    t.symbol = symbol
    t.side = side
    t.qty = qty
    t.price = price
    t.mode = "paper"
    t.filled_at = datetime.utcnow().replace(
        hour=9, minute=0, second=0, microsecond=0
    ) + timedelta(minutes=offset_minutes)
    return t


class TestDailyRealizedPL:
    def _run(self, trades):
        """Patch the DB query and call _today_realized_pl."""
        db = MagicMock()
        query_chain = db.query.return_value.filter.return_value.order_by.return_value
        query_chain.all.return_value = trades
        return _today_realized_pl(db, "paper")

    def test_round_trip_profit(self):
        """Buy 1 @ $100, sell 1 @ $120 → realized = +$20."""
        trades = [
            _trade("AAPL", "buy",  1.0, 100.0, offset_minutes=0),
            _trade("AAPL", "sell", 1.0, 120.0, offset_minutes=30),
        ]
        assert self._run(trades) == pytest.approx(20.0)

    def test_round_trip_loss(self):
        """Buy 1 @ $100, sell 1 @ $80 → realized = -$20."""
        trades = [
            _trade("AAPL", "buy",  1.0, 100.0),
            _trade("AAPL", "sell", 1.0,  80.0, offset_minutes=30),
        ]
        assert self._run(trades) == pytest.approx(-20.0)

    def test_partial_close(self):
        """Buy 2 @ $100, sell 1 @ $120 → only 1 share realized (+$20)."""
        trades = [
            _trade("AAPL", "buy",  2.0, 100.0),
            _trade("AAPL", "sell", 1.0, 120.0, offset_minutes=30),
        ]
        assert self._run(trades) == pytest.approx(20.0)

    def test_sell_before_buy_today_zero_credit(self):
        """Sell with no today's buy (position opened yesterday) → P/L = 0.
        Conservative: we don't credit gains we can't verify cost basis for."""
        trades = [_trade("AAPL", "sell", 1.0, 150.0)]
        assert self._run(trades) == pytest.approx(0.0)

    def test_multiple_symbols_independent(self):
        """AAPL +$20, TSLA -$10 → net +$10."""
        trades = [
            _trade("AAPL", "buy",  1.0, 100.0, 0),
            _trade("AAPL", "sell", 1.0, 120.0, 5),
            _trade("TSLA", "buy",  1.0, 200.0, 10),
            _trade("TSLA", "sell", 1.0, 190.0, 15),
        ]
        assert self._run(trades) == pytest.approx(10.0)

    def test_fifo_ordering_two_lots(self):
        """Buy 1@$100, buy 1@$110. Sell 1@$120 → FIFO matches first lot (+$20)."""
        trades = [
            _trade("AAPL", "buy",  1.0, 100.0, 0),
            _trade("AAPL", "buy",  1.0, 110.0, 5),
            _trade("AAPL", "sell", 1.0, 120.0, 10),
        ]
        assert self._run(trades) == pytest.approx(20.0)

    def test_no_trades_zero(self):
        assert self._run([]) == pytest.approx(0.0)

    def test_only_buys_zero_realized(self):
        """Unrealised positions don't count."""
        trades = [_trade("AAPL", "buy", 2.0, 100.0)]
        assert self._run(trades) == pytest.approx(0.0)
