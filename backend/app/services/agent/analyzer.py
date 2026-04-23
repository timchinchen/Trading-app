"""Aggregate per-tweet LLM outputs into per-ticker signals."""

import json
from collections import defaultdict
from typing import Any, Iterable

_WEIGHT_MIN = 0.5
_WEIGHT_MAX = 2.0


def normalize_handle_weights(
    raw: "str | dict[str, Any] | None",
) -> "tuple[dict[str, float], str | None]":
    """Parse and validate handle weight config.

    Accepts a JSON string or already-parsed dict. Returns (weights, warning).
    On any parse error returns ({}, warning) — never crashes the run.
    Handles are stored lower-cased for case-insensitive lookup.
    Weights are clamped to [_WEIGHT_MIN, _WEIGHT_MAX].
    """
    if raw is None or raw == "" or raw == "{}":
        return {}, None
    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = dict(raw)
        if not isinstance(parsed, dict):
            return {}, f"AGENT_HANDLE_WEIGHTS must be a JSON object, got {type(parsed).__name__}"
        out: dict[str, float] = {}
        for handle, w in parsed.items():
            try:
                clamped = max(_WEIGHT_MIN, min(_WEIGHT_MAX, float(w)))
                out[str(handle).lower()] = clamped
            except (TypeError, ValueError):
                pass  # skip bad individual entries
        return out, None
    except Exception as exc:
        return {}, f"AGENT_HANDLE_WEIGHTS parse error: {exc}"


def aggregate(
    per_tweet: list[dict[str, Any]],
    *,
    handle_weights: "dict[str, float] | None" = None,
) -> dict[str, dict[str, Any]]:
    """
    per_tweet is a list of dicts:
      { "tweet": {handle, url, text, tweet_id, created_at},
        "analysis": {"tickers":[...], "meta": {...}} }

    Returns: { "AAPL": {"score": 0.42, "confidence": 0.6, "mentions": 3,
                        "rationales": [...], "sources": [...]} }

    Noise filtering: items where analysis.meta.is_noise is True are skipped
    entirely before aggregation. Tweet rows are still persisted by the caller
    (runner) for debugging — we just don't count them toward signals.
    Returns a 3-tuple (out, total, noise_count) when called internally but
    the public signature stays backward-compatible by returning only `out`.
    """
    bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"score_sum": 0.0, "conf_sum": 0.0, "mentions": 0,
                 "rationales": [], "sources": []}
    )
    weights = handle_weights or {}
    noise_count = 0
    for item in per_tweet:
        tw = item["tweet"]
        analysis = item.get("analysis") or {}
        meta = analysis.get("meta") or {}
        if meta.get("is_noise"):
            noise_count += 1
            continue
        handle_key = (tw.get("handle") or "").lower()
        w = weights.get(handle_key, 1.0)
        for t in analysis.get("tickers", []) or []:
            sym = (t.get("symbol") or "").upper().strip()
            if not sym or not sym.isalpha() or len(sym) > 5:
                continue
            try:
                sent = float(t.get("sentiment", 0.0))
                conf = float(t.get("confidence", 0.0))
            except Exception:
                continue
            sent = max(-1.0, min(1.0, sent))
            conf = max(0.0, min(1.0, conf))
            b = bucket[sym]
            # Apply handle reliability weight to both score and confidence
            # contributions so a high-quality source has proportionally more
            # influence on the final signal.
            b["score_sum"] += sent * (0.5 + conf) * w
            b["conf_sum"] += conf * w
            b["mentions"] += 1
            b.setdefault("weighted_mention_sum", 0.0)
            b["weighted_mention_sum"] += w
            rat = t.get("rationale")
            if rat:
                b["rationales"].append(f"@{tw['handle']}: {rat}")
            b["sources"].append({
                "handle": tw["handle"],
                "tweet_id": tw.get("tweet_id"),
                "url": tw.get("url"),
                "excerpt": (tw.get("text") or "")[:240],
            })

    out: dict[str, dict[str, Any]] = {}
    for sym, b in bucket.items():
        if b["mentions"] == 0:
            continue
        # Use weighted_mention_sum for normalisation so high-weight handles
        # shift the score more than a crowd of low-weight ones.
        wsum = b.get("weighted_mention_sum") or float(b["mentions"])
        norm = 1.5 * wsum
        score = max(-1.0, min(1.0, b["score_sum"] / norm)) if norm else 0.0
        confidence = b["conf_sum"] / wsum
        out[sym] = {
            "score": round(score, 3),
            "confidence": round(confidence, 3),
            "mentions": b["mentions"],
            "rationale": " | ".join(b["rationales"][:5]),
            "sources": b["sources"][:10],
            "corroborated_by": [],
        }
    # Attach noise stats as a sidecar on the dict (doesn't affect iteration).
    # Runner reads these via aggregate_stats() so callers that just iterate
    # the dict are unaffected.
    out["__noise_stats__"] = {  # type: ignore[assignment]
        "total": len(per_tweet),
        "noise": noise_count,
        "used": len(per_tweet) - noise_count,
    }
    return out


def pop_noise_stats(signals: dict[str, Any]) -> dict[str, int]:
    """Remove and return the noise stats sidecar injected by aggregate().
    Safe to call even if the key is absent (returns zeros)."""
    return signals.pop("__noise_stats__", {"total": 0, "noise": 0, "used": 0})


def apply_intel_boost(
    signals: dict[str, dict[str, Any]],
    corroborating_symbols: Iterable[str],
    avoid_symbols: Iterable[str] = (),
    boost: float = 0.15,
) -> dict[str, dict[str, Any]]:
    """Nudge confidences up when a ticker is independently flagged by the
    market-intel sources, and nudge score slightly down for symbols appearing
    in the top-losers list (contextual drag). Returns the same dict mutated
    in place for convenience.
    """
    corr = {s.upper() for s in corroborating_symbols}
    avoid = {s.upper() for s in avoid_symbols}

    for sym, s in signals.items():
        if sym in corr:
            new_conf = min(1.0, s["confidence"] + boost)
            s["corroborated_by"].append("market-intel")
            s["confidence"] = round(new_conf, 3)
        if sym in avoid:
            # Don't invert; just dampen a bullish score.
            if s["score"] > 0:
                s["score"] = round(max(0.0, s["score"] - boost), 3)
                s["corroborated_by"].append("top-loser-drag")
    return signals
