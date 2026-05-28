"""Deterministic pre-LLM signal scoring.

This module adds a transparent, weighted composite score on top of the
tweet-aggregation output. It is designed to be staged in safely:
  - disabled by default
  - optionally enabled for diagnostics/ranking
  - optional score override for allocator compatibility experiments
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScoringWeights:
    relative_strength: float = 0.30
    trend_quality: float = 0.25
    volume_expansion: float = 0.20
    sentiment: float = 0.15
    catalyst_strength: float = 0.10


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except Exception:
        v = default
    return max(0.0, min(1.0, v))


def _score_to_01(score: Any) -> float:
    """Map legacy sentiment score [-1..1] into [0..1]."""
    try:
        s = float(score)
    except Exception:
        s = 0.0
    s = max(-1.0, min(1.0, s))
    return (s + 1.0) / 2.0


def derive_factor_vector(signal: dict[str, Any]) -> dict[str, float]:
    """Build normalized factors with fallback heuristics.

    Existing pipelines can pass richer fields over time:
      - rs_score_20d / rs_score_50d
      - trend_quality
      - volume_expansion
      - catalyst_strength
    Until then we derive conservative approximations from existing signal fields.
    """
    mentions = max(0.0, float(signal.get("mentions", 0) or 0.0))
    confidence = _clamp01(signal.get("confidence", 0.0))
    score_01 = _score_to_01(signal.get("score", 0.0))
    rationale = (signal.get("rationale") or "").strip()

    rs_20 = _clamp01(signal.get("rs_score_20d", score_01))
    rs_50 = _clamp01(signal.get("rs_score_50d", score_01))
    relative_strength = round((0.6 * rs_20) + (0.4 * rs_50), 4)

    trend_quality = _clamp01(signal.get("trend_quality", confidence))
    volume_expansion = _clamp01(signal.get("volume_expansion", min(1.0, mentions / 5.0)))
    sentiment = score_01
    catalyst_strength = _clamp01(
        signal.get("catalyst_strength", 1.0 if rationale else 0.2)
    )

    return {
        "relative_strength": relative_strength,
        "trend_quality": trend_quality,
        "volume_expansion": volume_expansion,
        "sentiment": sentiment,
        "catalyst_strength": catalyst_strength,
    }


def composite_score(signal: dict[str, Any], *, weights: ScoringWeights) -> tuple[float, dict[str, float]]:
    factors = derive_factor_vector(signal)
    composite = (
        weights.relative_strength * factors["relative_strength"]
        + weights.trend_quality * factors["trend_quality"]
        + weights.volume_expansion * factors["volume_expansion"]
        + weights.sentiment * factors["sentiment"]
        + weights.catalyst_strength * factors["catalyst_strength"]
    )
    return round(_clamp01(composite), 4), factors


def apply_pre_llm_scoring(
    signals: dict[str, dict[str, Any]],
    *,
    enabled: bool,
    weights: ScoringWeights,
    override_score: bool,
) -> dict[str, int]:
    """Attach deterministic factors to each signal.

    When override_score=True, map deterministic [0..1] -> legacy [-1..1] score
    and replace `signal["score"]` so downstream allocator gating can use it.
    """
    if not enabled:
        return {"scored": 0, "overridden": 0}

    scored = 0
    overridden = 0
    for _, signal in signals.items():
        scored += 1
        det_score, factors = composite_score(signal, weights=weights)
        signal["deterministic_score"] = det_score
        signal["deterministic_factors"] = factors
        if override_score:
            signal["score"] = round((det_score * 2.0) - 1.0, 3)
            overridden += 1

    return {"scored": scored, "overridden": overridden}
