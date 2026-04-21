"""Trading Digest - long-term memory for the agent.

Emits short "what happened" breadcrumbs (DigestEntry rows) from every
meaningful surface (runner, advisor, orders, swing setups, intel, watchlist
deltas, settings changes). Once per trading day at 09:30 ET, compress_daily()
rolls up the last 7 days of entries via the Deep Analysis LLM into a single
DailyDigest paragraph which is:

  - Displayed on the Dashboard as the "Trading Memory" panel
  - Prepended (last 3 days) to every advisor LLM prompt for continuity
  - Kept forever (raw entries older than RAW_RETENTION_DAYS are pruned)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import DailyDigest, DigestEntry


RAW_RETENTION_DAYS = 7
COMPRESS_WINDOW_DAYS = 7
ADVISOR_CONTEXT_DIGESTS = 3
# Budget for the memory prefix injected into every advisor prompt. Caps the
# total size so we don't silently spend ~8k tokens per run on old memories
# (each DailyDigest can be up to 8kB). ~2kB ≈ 500 tokens.
ADVISOR_MEMORY_MAX_CHARS = 2000
# Per-digest cap inside the prefix. Older digests get stricter truncation.
ADVISOR_MEMORY_PER_DIGEST_CHARS = 800

# Permitted "kind" values - keep the enum tight so the downstream LLM can
# reason about them without surprises.
KNOWN_KINDS = {
    "agent_run",
    "advisor",
    "trade_exec",
    "swing_setup",
    "regime_flip",
    "intel_highlight",
    "watchlist_delta",
    "settings_change",
    "error",
}


def _safe_json(payload: Any) -> Optional[str]:
    if payload is None:
        return None
    try:
        return json.dumps(payload, default=str)[:4000]
    except Exception:
        return None


def append_entry(
    *,
    kind: str,
    summary: str,
    symbol: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> None:
    """Fire-and-forget append. Never raises (digest must not break callers)."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        row = DigestEntry(
            kind=(kind or "agent_run") if kind in KNOWN_KINDS else "agent_run",
            symbol=(symbol or None),
            summary=(summary or "")[:600],
            data_json=_safe_json(data),
        )
        db.add(row)
        db.commit()
    except Exception as e:
        print(f"[digest] append failed ({kind}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if own:
            db.close()


def recent_entries(db: Session, days: int = COMPRESS_WINDOW_DAYS) -> list[DigestEntry]:
    since = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(DigestEntry)
        .filter(DigestEntry.created_at >= since)
        .order_by(DigestEntry.created_at.asc())
        .all()
    )


def recent_daily_digests(db: Session, limit: int = ADVISOR_CONTEXT_DIGESTS) -> list[DailyDigest]:
    return (
        db.query(DailyDigest)
        .order_by(DailyDigest.generated_at.desc())
        .limit(limit)
        .all()
    )


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def advisor_memory_prefix(db: Session, limit: int = ADVISOR_CONTEXT_DIGESTS) -> str:
    """Short text block to prepend to every advisor prompt so the LLM has
    continuity across runs. Returns '' if no digests yet.

    The block is capped at ADVISOR_MEMORY_MAX_CHARS total so we don't silently
    pay for thousands of memory tokens on every advisor call. The most recent
    digest keeps the largest slice; older ones are truncated more aggressively."""
    digests = recent_daily_digests(db, limit=limit)
    if not digests:
        return ""
    # newest first, so the most recent gets the largest individual budget.
    header = "Long-term trading memory (most recent daily digests):"
    chunks: list[str] = []
    running = len(header) + 1
    for i, d in enumerate(digests):
        # First (newest) digest gets the full per-digest cap; each older one
        # gets ~half of the previous.
        per_cap = max(200, ADVISOR_MEMORY_PER_DIGEST_CHARS // (2 ** i))
        body = _truncate(d.text, per_cap)
        chunk = f"[{d.trade_date}]\n{body}"
        # If adding this chunk would blow the total budget, stop here.
        if running + len(chunk) + 2 > ADVISOR_MEMORY_MAX_CHARS:
            break
        chunks.append(chunk)
        running += len(chunk) + 2
    if not chunks:
        return ""
    # Oldest-first reads more naturally for the LLM.
    chunks.reverse()
    return header + "\n" + "\n\n".join(chunks) + "\n"


def _render_entries_for_llm(entries: list[DigestEntry]) -> str:
    if not entries:
        return "(no entries recorded)"
    lines: list[str] = []
    for e in entries:
        ts = e.created_at.strftime("%Y-%m-%d %H:%M")
        sym = f" {e.symbol}" if e.symbol else ""
        lines.append(f"- [{ts} UTC] ({e.kind}){sym}: {e.summary}")
    return "\n".join(lines)


DAILY_DIGEST_SYSTEM = (
    "You are the trading-memory compressor for a personal swing-trading agent. "
    "You receive a chronological log of events from the last 7 days: agent "
    "runs, advisor recommendations, executed trades, swing setups, regime "
    "flips, intel highlights, watchlist deltas, and errors. Produce a concise "
    "memory note in plain text (no markdown, no disclaimers) with these "
    "sections separated by blank lines:\n\n"
    "THIS WEEK\n"
    "- 2-4 bullet lines: what the agent did (trades executed, themes, losses "
    "taken, setups worked/failed)\n\n"
    "OPEN THREADS\n"
    "- 1-3 bullet lines: positions still open, setups still pending, symbols "
    "we keep circling back to\n\n"
    "PATTERNS & LESSONS\n"
    "- 1-3 bullet lines: what pattern or lesson has emerged across runs (was "
    "the market filter too strict? did TSLA keep failing the same way? did "
    "earnings-momentum setups win? etc.)\n\n"
    "FOCUS FOR TODAY\n"
    "- one short line: what the agent should prioritise or avoid today given "
    "the last 7 days of memory\n\n"
    "Stay under 220 words. Refer to tickers in ALLCAPS. Never invent events "
    "that are not in the log. If the log is sparse, say so."
)


async def compress_daily(
    trade_date: str | None = None,
    *,
    db: Session | None = None,
    force: bool = False,
) -> DailyDigest | None:
    """Compress the last 7 days of entries into a DailyDigest row. Returns
    the saved row, or None if we had nothing to compress / couldn't run."""
    own = db is None
    if own:
        db = SessionLocal()

    # Lazy-imported to avoid circular: digest_store is loaded by llm/runner.
    from .agent import llm as llm_module
    from .settings_store import get_runtime_settings

    try:
        ny = ZoneInfo("America/New_York")
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_ny = now_utc.astimezone(ny)
        date_key = trade_date or now_ny.strftime("%Y-%m-%d")

        if not force:
            existing = (
                db.query(DailyDigest)
                .filter(DailyDigest.trade_date == date_key)
                .first()
            )
            if existing:
                print(f"[digest] daily digest already present for {date_key}; skipping")
                return existing

        entries = recent_entries(db, days=COMPRESS_WINDOW_DAYS)
        if not entries:
            print(f"[digest] no entries in last {COMPRESS_WINDOW_DAYS}d; writing empty placeholder")
            text = "(no agent activity recorded in the last 7 days)"
            model_used = "(skipped)"
        else:
            rs = get_runtime_settings(db)
            prior = recent_daily_digests(db, limit=ADVISOR_CONTEXT_DIGESTS)
            prior_text = ""
            if prior:
                prior_text = "Prior compressed digests (for continuity):\n"
                for p in reversed(prior):
                    prior_text += f"[{p.trade_date}] {p.text.strip()}\n\n"
            user_prompt = (
                (prior_text + "\n" if prior_text else "")
                + f"Today is {date_key} (US/Eastern). "
                + f"Compress the following {len(entries)} events from the last "
                + f"{COMPRESS_WINDOW_DAYS} days into the required memory note.\n\n"
                + _render_entries_for_llm(entries)
            )
            model_used = f"{rs.advisor_provider}:{rs.advisor_model}"
            try:
                text = await llm_module._chat(
                    provider=rs.advisor_provider,
                    host=rs.advisor_host,
                    model=rs.advisor_model,
                    api_key=rs.advisor_api_key,
                    system=DAILY_DIGEST_SYSTEM,
                    user=user_prompt,
                    temperature=0.2,
                    timeout=180,
                )
                text = (text or "").strip()
                if not text:
                    text = "(digest LLM returned empty response)"
            except Exception as e:
                print(f"[digest] LLM compression failed: {e}")
                # Fallback: rule-based digest so dashboard still updates.
                text = _fallback_summary(entries)
                model_used = "fallback:rule-based"

        window_start = entries[0].created_at if entries else None
        window_end = entries[-1].created_at if entries else None

        # Upsert (force=True comes in here too).
        existing = (
            db.query(DailyDigest)
            .filter(DailyDigest.trade_date == date_key)
            .first()
        )
        if existing:
            existing.text = text[:8000]
            existing.generated_at = datetime.utcnow()
            existing.entries_covered = len(entries)
            existing.window_start = window_start
            existing.window_end = window_end
            existing.model_used = model_used
            row = existing
        else:
            row = DailyDigest(
                trade_date=date_key,
                generated_at=datetime.utcnow(),
                entries_covered=len(entries),
                window_start=window_start,
                window_end=window_end,
                model_used=model_used,
                text=text[:8000],
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        print(f"[digest] daily digest saved for {date_key} ({len(entries)} entries) via {model_used}")

        # Prune raw entries older than retention.
        cutoff = datetime.utcnow() - timedelta(days=RAW_RETENTION_DAYS)
        pruned = (
            db.query(DigestEntry)
            .filter(DigestEntry.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        if pruned:
            print(f"[digest] pruned {pruned} raw entries older than {RAW_RETENTION_DAYS}d")

        return row
    except Exception as e:
        print(f"[digest] compress_daily crashed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        if own:
            db.close()


def _fallback_summary(entries: list[DigestEntry]) -> str:
    by_kind: dict[str, int] = {}
    symbols: dict[str, int] = {}
    for e in entries:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        if e.symbol:
            symbols[e.symbol] = symbols.get(e.symbol, 0) + 1
    top_syms = sorted(symbols.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_sym_txt = ", ".join(f"{s}x{n}" for s, n in top_syms) or "(none)"
    kind_txt = ", ".join(f"{k}={n}" for k, n in sorted(by_kind.items()))
    return (
        "THIS WEEK\n"
        f"- {len(entries)} events recorded ({kind_txt}).\n"
        f"- Most-mentioned tickers: {top_sym_txt}.\n\n"
        "OPEN THREADS\n"
        "- (LLM unavailable; see raw entries for detail.)\n\n"
        "PATTERNS & LESSONS\n"
        "- (LLM unavailable for lesson extraction.)\n\n"
        "FOCUS FOR TODAY\n"
        "- Review the raw digest entries; reconfigure Deep Analysis LLM if this keeps failing."
    )
