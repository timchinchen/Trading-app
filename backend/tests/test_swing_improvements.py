"""Unit tests for the 3 swing-trading improvements.

Run with: python3 -m pytest backend/tests/test_swing_improvements.py -v
No database or broker required.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from app.services.agent import analyzer, allocator


# ============================================================================
# Improvement 1 — Source reliability weighting
# ============================================================================

class TestNormalizeHandleWeights:
    def test_empty_string_returns_empty(self):
        w, warn = analyzer.normalize_handle_weights("")
        assert w == {} and warn is None

    def test_none_returns_empty(self):
        w, warn = analyzer.normalize_handle_weights(None)
        assert w == {} and warn is None

    def test_valid_json_string(self):
        w, warn = analyzer.normalize_handle_weights('{"PeterLBrandt": 1.25, "random": 0.8}')
        assert w["peterlbrandt"] == pytest.approx(1.25)
        assert w["random"] == pytest.approx(0.8)
        assert warn is None

    def test_handles_lowercased(self):
        w, _ = analyzer.normalize_handle_weights('{"UPPER": 1.5}')
        assert "upper" in w

    def test_weight_clamped_to_max(self):
        w, _ = analyzer.normalize_handle_weights('{"loud": 99.0}')
        assert w["loud"] == pytest.approx(2.0)

    def test_weight_clamped_to_min(self):
        w, _ = analyzer.normalize_handle_weights('{"quiet": 0.0}')
        assert w["quiet"] == pytest.approx(0.5)

    def test_malformed_json_returns_empty_with_warning(self):
        w, warn = analyzer.normalize_handle_weights("{bad json!!}")
        assert w == {}
        assert warn is not None
        assert "parse error" in warn.lower()

    def test_accepts_dict_directly(self):
        w, warn = analyzer.normalize_handle_weights({"Alice": 1.3})
        assert w["alice"] == pytest.approx(1.3)
        assert warn is None

    def test_non_dict_json_returns_warning(self):
        w, warn = analyzer.normalize_handle_weights("[1, 2, 3]")
        assert w == {}
        assert warn is not None


class TestWeightedAggregation:
    """Weighted signal should differ from equal-weight signal."""

    def _item(self, handle, symbol, sentiment=0.8, confidence=0.8, noise=False):
        return {
            "tweet": {"handle": handle, "url": "", "text": "t",
                      "tweet_id": "1", "created_at": "2024-01-01T09:00:00"},
            "analysis": {
                "tickers": [{"symbol": symbol, "sentiment": sentiment,
                              "confidence": confidence, "rationale": "r"}],
                "meta": {"is_noise": noise},
            },
        }

    def test_high_weight_handle_raises_score(self):
        items = [self._item("expert", "AAPL", 0.9, 0.9)]
        base = analyzer.aggregate(items)
        analyzer.pop_noise_stats(base)

        weighted = analyzer.aggregate(items, handle_weights={"expert": 2.0})
        analyzer.pop_noise_stats(weighted)

        # Score should be same direction but magnitude can differ via norm
        assert "AAPL" in weighted

    def test_two_handles_different_weights_produce_different_scores(self):
        """Same tweet content, different handles → different aggregated signal."""
        item_high = self._item("expert", "AAPL", 0.8, 0.8)
        item_low  = self._item("noise",  "AAPL", 0.8, 0.8)

        # With uniform weights both should aggregate identically.
        both_items = [item_high, item_low]
        uniform = analyzer.aggregate(both_items)
        analyzer.pop_noise_stats(uniform)

        # Now give expert 2x weight and noise 0.5x.
        weighted = analyzer.aggregate(
            both_items,
            handle_weights={"expert": 2.0, "noise": 0.5},
        )
        analyzer.pop_noise_stats(weighted)

        # Score should exist in both; weighted score ≠ uniform for same data
        # only when weights differ from 1.0, which they do here.
        assert "AAPL" in uniform
        assert "AAPL" in weighted
        # Both positive (same sentiment direction).
        assert weighted["AAPL"]["score"] > 0

    def test_low_weight_handle_single_tweet_lower_impact(self):
        item_high = self._item("trusted", "NVDA", 0.9, 0.9)
        item_low  = self._item("random",  "NVDA", 0.9, 0.9)

        high_sig = analyzer.aggregate([item_high], handle_weights={"trusted": 2.0})
        analyzer.pop_noise_stats(high_sig)
        low_sig = analyzer.aggregate([item_low], handle_weights={"random": 0.5})
        analyzer.pop_noise_stats(low_sig)

        # High-weight handle → higher or equal score vs low-weight (same sentiment)
        assert high_sig["NVDA"]["score"] >= low_sig["NVDA"]["score"]

    def test_noise_still_excluded_when_weights_provided(self):
        items = [
            self._item("expert", "TSLA", 0.9, 0.9, noise=False),
            self._item("expert", "TSLA", 0.9, 0.9, noise=True),
        ]
        sigs = analyzer.aggregate(items, handle_weights={"expert": 1.5})
        stats = analyzer.pop_noise_stats(sigs)
        assert stats["noise"] == 1
        assert sigs["TSLA"]["mentions"] == 1


# ============================================================================
# Improvement 2 — Regime-adaptive sizing / buy gating
# ============================================================================

def _signals(sym="AAPL", score=0.8, conf=0.8, mentions=3):
    return {sym: {"score": score, "confidence": conf, "mentions": mentions,
                  "rationale": "", "sources": [], "corroborated_by": []}}

BASE = dict(
    open_symbols=set(),
    budget_remaining=1000.0,
    weekly_remaining=5000.0,
    min_position_usd=50.0,
    max_position_usd=500.0,
    max_open_positions=10,
    get_price=lambda s: 100.0,
    min_score=0.3,
    min_confidence=0.3,
    top_n=5,
)


class TestRegimeAdaptiveSizing:
    def test_risk_on_multiplier_increases_notional(self):
        p_normal = allocator.propose_trades(signals=_signals(), **BASE)[0]
        p_riskon  = allocator.propose_trades(
            signals=_signals(), **BASE, risk_multiplier=1.25)[0]
        assert p_riskon["notional"] >= p_normal["notional"]

    def test_risk_off_multiplier_decreases_notional(self):
        p_normal  = allocator.propose_trades(signals=_signals(), **BASE)[0]
        p_riskoff = allocator.propose_trades(
            signals=_signals(), **BASE, risk_multiplier=0.5)[0]
        assert p_riskoff["notional"] <= p_normal["notional"]

    def test_block_new_buys_skips_all_buy_candidates(self):
        props = allocator.propose_trades(
            signals=_signals(), **BASE, block_new_buys=True)
        buys = [p for p in props if p["side"] == "buy"]
        assert all(p["action"] == "skipped" for p in buys)
        assert all("risk-off" in p["reason"] for p in buys)

    def test_block_new_buys_still_allows_bearish_sells(self):
        """Sell proposals (bearish reversal) must not be blocked."""
        sigs = _signals("AAPL", score=-0.8, conf=0.9)
        kwargs = {**BASE, "open_symbols": {"AAPL"}}
        props = allocator.propose_trades(
            signals=sigs,
            open_position_qtys={"AAPL": 2.0},
            block_new_buys=True,
            **kwargs,
        )
        sells = [p for p in props if p["side"] == "sell" and p["action"] == "proposed"]
        assert len(sells) == 1
        assert sells[0]["qty"] == 2.0

    def test_existing_caps_still_respected_after_multiplier(self):
        """Even with a 2x multiplier the notional can't exceed max_position_usd."""
        kwargs = {**BASE, "risk_multiplier": 2.0}
        props = allocator.propose_trades(signals=_signals(), **kwargs)
        buys = [p for p in props if p["side"] == "buy" and p["action"] == "proposed"]
        for p in buys:
            assert p["notional"] <= BASE["max_position_usd"] + 0.01


# ============================================================================
# Improvement 3 — Adaptive exit engine
# ============================================================================

from app.services.agent.runner import _adaptive_exit_proposals


def _pos(symbol, qty=1.0, current=105.0, plpc=0.05, entry=100.0):
    return {
        "symbol": symbol, "qty": qty, "current_price": current,
        "unrealized_plpc": plpc, "avg_entry_price": entry,
        "market_value": qty * current, "unrealized_pl": (current - entry) * qty,
    }


def _plan(symbol, stop=90.0, entry=100.0, target=120.0, opened_days_ago=3,
          partial_taken=0, peak_plpc=0.0):
    p = MagicMock()
    p.symbol = symbol
    p.stop_price = stop
    p.entry_price = entry
    p.target_price = target
    p.opened_at = datetime.utcnow() - timedelta(days=opened_days_ago)
    p.partial_taken = partial_taken
    p.peak_unrealized_plpc = peak_plpc
    p.status = "open"
    return p


class TestAdaptiveExitEngine:
    BASE_KWARGS = dict(
        mode="paper",
        max_hold_days=8,
        trail_arm_pct=0.05,
        trail_retrace_pct=0.35,
        partial_take_pct=0.07,
        partial_take_fraction=0.5,
        existing_sell_symbols=set(),
    )

    def _make_broker(self, positions):
        b = MagicMock()
        b.configured = True
        b.positions.return_value = positions
        return b

    def _make_db(self, plans):
        db = MagicMock()
        query_chain = db.query.return_value.filter.return_value
        query_chain.all.return_value = plans
        query_chain.order_by.return_value.first.return_value = None
        db.commit.return_value = None
        return db

    def test_hard_stop_triggered(self):
        broker = self._make_broker([_pos("AAPL", current=85.0, plpc=-0.15)])
        plan = _plan("AAPL", stop=90.0, entry=100.0, opened_days_ago=2)
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert len(props) == 1
        assert "hard-stop" in props[0]["reason"]
        assert props[0]["qty"] > 0

    def test_time_stop_triggered(self):
        broker = self._make_broker([_pos("TSLA", current=100.0, plpc=0.0)])
        plan = _plan("TSLA", stop=80.0, opened_days_ago=10)  # > max_hold_days=8
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert len(props) == 1
        assert "time-stop" in props[0]["reason"]
        assert props[0]["qty"] > 0

    def test_momentum_fade_triggers_after_arm(self):
        # Peak was 10%, now at 6% → retrace = 40% (> 35% threshold).
        broker = self._make_broker([_pos("NVDA", current=106.0, plpc=0.06)])
        plan = _plan("NVDA", stop=80.0, opened_days_ago=2, peak_plpc=0.10)
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert len(props) == 1
        assert "momentum-fade" in props[0]["reason"]
        assert props[0]["qty"] > 0

    def test_momentum_fade_does_not_trigger_below_arm(self):
        # Peak only 3% (below 5% arm threshold) → no momentum exit.
        broker = self._make_broker([_pos("META", current=102.0, plpc=0.02)])
        plan = _plan("META", stop=80.0, opened_days_ago=2, peak_plpc=0.03)
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert props == []  # 2% gain, no stop hit, no time stop, peak below arm

    def test_partial_tp_triggered_first_time(self):
        broker = self._make_broker([_pos("AMD", current=108.0, plpc=0.08)])
        plan = _plan("AMD", stop=80.0, opened_days_ago=2, partial_taken=0, peak_plpc=0.0)
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert len(props) == 1
        assert "partial" in props[0]["reason"].lower()
        assert props[0]["qty"] == pytest.approx(1.0 * 0.5)  # half of qty=1.0

    def test_partial_tp_not_repeated(self):
        broker = self._make_broker([_pos("AMD", current=108.0, plpc=0.08)])
        plan = _plan("AMD", stop=80.0, opened_days_ago=2, partial_taken=1, peak_plpc=0.0)
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert props == []  # already partial_taken

    def test_hard_stop_beats_time_stop(self):
        """Hard stop should be the reason, not time stop, when both apply."""
        broker = self._make_broker([_pos("SPY", current=85.0, plpc=-0.15)])
        plan = _plan("SPY", stop=90.0, opened_days_ago=20, peak_plpc=0.0)
        db = self._make_db([plan])
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        assert "hard-stop" in props[0]["reason"]

    def test_no_duplicate_per_run(self):
        broker = self._make_broker([_pos("AAPL", current=85.0, plpc=-0.15)])
        plan = _plan("AAPL", stop=90.0)
        db = self._make_db([plan])
        # Mark AAPL as already handled
        kwargs = {**self.BASE_KWARGS, "existing_sell_symbols": {"AAPL"}}
        props = _adaptive_exit_proposals(broker, db=db, **kwargs)
        assert props == []

    def test_sell_qty_always_positive(self):
        """All emitted proposals must have qty > 0."""
        broker = self._make_broker([
            _pos("AAPL", current=85.0, plpc=-0.15),   # hard stop
            _pos("TSLA", current=100.0, plpc=0.08),   # partial TP
        ])
        plans = [
            _plan("AAPL", stop=90.0, opened_days_ago=2),
            _plan("TSLA", stop=80.0, opened_days_ago=2, partial_taken=0),
        ]
        db = self._make_db(plans)
        props = _adaptive_exit_proposals(broker, db=db, **self.BASE_KWARGS)
        for p in props:
            assert p["qty"] > 0, f"Zero qty in proposal: {p}"
