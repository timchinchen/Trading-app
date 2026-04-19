"""Aggregate per-tweet LLM outputs into per-ticker signals."""

from collections import defaultdict
from typing import Any, Iterable


def aggregate(per_tweet: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    per_tweet is a list of dicts:
      { "tweet": {handle, url, text, tweet_id, created_at},
        "analysis": {"tickers":[...], "meta": {...}} }

    Returns: { "AAPL": {"score": 0.42, "confidence": 0.6, "mentions": 3,
                        "rationales": [...], "sources": [...]} }
    """
    bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"score_sum": 0.0, "conf_sum": 0.0, "mentions": 0,
                 "rationales": [], "sources": []}
    )
    for item in per_tweet:
        tw = item["tweet"]
        analysis = item.get("analysis") or {}
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
            b["score_sum"] += sent * (0.5 + conf)
            b["conf_sum"] += conf
            b["mentions"] += 1
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
        norm = 1.5 * b["mentions"]
        score = max(-1.0, min(1.0, b["score_sum"] / norm)) if norm else 0.0
        confidence = b["conf_sum"] / b["mentions"]
        out[sym] = {
            "score": round(score, 3),
            "confidence": round(confidence, 3),
            "mentions": b["mentions"],
            "rationale": " | ".join(b["rationales"][:5]),
            "sources": b["sources"][:10],
            "corroborated_by": [],
        }
    return out


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
