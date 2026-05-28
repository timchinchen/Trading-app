import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.agent.scoring_engine import (
    ScoringWeights,
    apply_pre_llm_scoring,
    composite_score,
    derive_factor_vector,
)


def test_derive_factor_vector_prefers_explicit_factors():
    signal = {
        "score": 0.4,
        "confidence": 0.7,
        "mentions": 2,
        "rationale": "earnings breakout",
        "rs_score_20d": 0.9,
        "rs_score_50d": 0.8,
        "trend_quality": 0.65,
        "volume_expansion": 0.55,
        "catalyst_strength": 0.75,
    }
    factors = derive_factor_vector(signal)
    assert factors["relative_strength"] == 0.86
    assert factors["trend_quality"] == 0.65
    assert factors["volume_expansion"] == 0.55
    assert factors["catalyst_strength"] == 0.75


def test_composite_score_with_default_weights_is_bounded():
    signal = {"score": 0.3, "confidence": 0.6, "mentions": 4, "rationale": "guidance raise"}
    score, factors = composite_score(signal, weights=ScoringWeights())
    assert 0.0 <= score <= 1.0
    assert set(factors.keys()) == {
        "relative_strength",
        "trend_quality",
        "volume_expansion",
        "sentiment",
        "catalyst_strength",
    }


def test_apply_pre_llm_scoring_override_updates_legacy_score():
    signals = {
        "NVDA": {"score": 0.5, "confidence": 0.9, "mentions": 5, "rationale": "ai demand"},
        "AAPL": {"score": -0.2, "confidence": 0.4, "mentions": 1, "rationale": ""},
    }
    stats = apply_pre_llm_scoring(
        signals,
        enabled=True,
        weights=ScoringWeights(),
        override_score=True,
    )
    assert stats == {"scored": 2, "overridden": 2}
    assert "deterministic_score" in signals["NVDA"]
    assert "deterministic_factors" in signals["NVDA"]
    assert -1.0 <= signals["NVDA"]["score"] <= 1.0
    assert -1.0 <= signals["AAPL"]["score"] <= 1.0
