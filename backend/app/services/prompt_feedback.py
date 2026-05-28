"""Weekly trading feedback: stats, lesson compression, dynamic ROLE_PREAMBLE."""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import AgentRun, AgentTrade, DailyDigest, DigestEntry, Order, Trade, WeeklyPromptLesson


LESSONS_HEADER = (
    "LESSONS_FROM_RECENT_TRADING (append-only; do not override CORE rules above):"
)

WEEKLY_LESSON_SYSTEM = (
    "You distill one calendar week of swing-trading outcomes into short bullets "
    "for the agent's system prompt. You receive deterministic stats plus event "
    "log excerpts. Produce plain text (no markdown) with EXACTLY these headers:\n\n"
    "RECENT_OUTCOMES\n"
    "- 2-4 bullets: realized P/L, win rate, which setup types worked/failed\n\n"
    "CALIBRATION (next week)\n"
    "- 2-4 bullets: what to prefer, avoid, or watch (setup/regime/symbol themes)\n\n"
    "Stay under 320 words. Never invent trades or numbers not in the stats. "
    "Never tell the agent to ignore stops, risk caps, or the SPY market filter. "
    "If stats show persistent NO-GO regime, say so once — do not repeat generic filler."
)


def week_start_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def current_week_key(now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def parse_advisor_feedback(advice: str | None) -> str | None:
    if not advice:
        return None
    m = re.search(
        r"Feedback to operator\s*\n\s*[-•]?\s*(.+?)(?:\n\n|\Z)",
        advice,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    text = " ".join(m.group(1).strip().split())
    return text[:500] if text else None


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def compute_weekly_stats(db: Session, mode: str, *, since: datetime | None = None) -> dict[str, Any]:
    """Deterministic week metrics for lesson compression and diagnostics."""
    since = since or week_start_utc()
    by_setup: dict[str, dict[str, float]] = defaultdict(
        lambda: {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}
    )
    realized_total = 0.0
    wins = 0
    losses = 0

    filled_orders = (
        db.query(Order)
        .filter(
            Order.mode == mode,
            Order.filled_avg_price.isnot(None),
            Order.filled_at >= since,
        )
        .order_by(Order.filled_at.asc(), Order.submitted_at.asc(), Order.id.asc())
        .all()
    )
    lots: dict[str, deque] = defaultdict(deque)
    pl_by_order: dict[int, Optional[float]] = {}
    for r in filled_orders:
        sym = (r.symbol or "").upper()
        if not sym or r.filled_avg_price is None:
            continue
        qty = float(r.filled_qty if r.filled_qty is not None else r.qty or 0)
        px = float(r.filled_avg_price)
        if qty <= 0:
            continue
        side = (r.side or "").lower()
        if side == "buy":
            lots[sym].append([qty, px])
            continue
        if side != "sell":
            continue
        remaining = qty
        pnl = 0.0
        sym_lots = lots[sym]
        while remaining > 1e-12 and sym_lots:
            lot_qty, lot_px = sym_lots[0]
            matched = min(lot_qty, remaining)
            pnl += matched * (px - lot_px)
            lot_qty -= matched
            remaining -= matched
            if lot_qty <= 1e-12:
                sym_lots.popleft()
            else:
                sym_lots[0][0] = lot_qty
        pl_by_order[r.id] = None if remaining > 1e-12 else round(pnl, 4)
    for oid, pnl in pl_by_order.items():
        if pnl is None:
            continue
        realized_total += pnl
        if pnl >= 0:
            wins += 1
        else:
            losses += 1
        at = (
            db.query(AgentTrade)
            .filter(AgentTrade.order_id == oid)
            .order_by(AgentTrade.id.desc())
            .first()
        )
        setup = (at.setup_type if at else None) or "unknown"
        bucket = by_setup[setup]
        bucket["pnl"] += pnl
        bucket["trades"] += 1
        if pnl >= 0:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1

    agent_trades = (
        db.query(AgentTrade)
        .filter(AgentTrade.mode == mode, AgentTrade.created_at >= since)
        .all()
    )
    proposed = sum(1 for r in agent_trades if r.action == "proposed")
    executed = sum(1 for r in agent_trades if r.action == "executed")
    skipped = sum(1 for r in agent_trades if r.action == "skipped")

    runs = (
        db.query(AgentRun)
        .filter(AgentRun.mode == mode, AgentRun.started_at >= since)
        .count()
    )
    regime_entries = (
        db.query(DigestEntry)
        .filter(
            DigestEntry.created_at >= since,
            DigestEntry.kind == "regime_flip",
        )
        .count()
    )
    no_go_hints = (
        db.query(DigestEntry)
        .filter(DigestEntry.created_at >= since)
        .filter(DigestEntry.summary.ilike("%no-go%"))
        .count()
    )
    feedback_entries = (
        db.query(DigestEntry)
        .filter(
            DigestEntry.created_at >= since,
            DigestEntry.kind == "advisor_feedback",
        )
        .count()
    )

    return {
        "week_start_utc": since.isoformat(),
        "week_key": current_week_key(),
        "realized_pl": round(realized_total, 2),
        "closed_round_trips": wins + losses,
        "wins": wins,
        "losses": losses,
        "by_setup": dict(by_setup),
        "agent_trades_proposed": proposed,
        "agent_trades_executed": executed,
        "agent_trades_skipped": skipped,
        "agent_runs": runs,
        "regime_flip_entries": regime_entries,
        "no_go_digest_hints": no_go_hints,
        "advisor_feedback_entries": feedback_entries,
    }


def format_stats_brief(stats: dict[str, Any]) -> str:
    lines = [
        f"Week {stats.get('week_key')} (since {stats.get('week_start_utc')} UTC)",
        f"Realized P/L: ${stats.get('realized_pl', 0):+.2f} "
        f"({stats.get('wins', 0)}W / {stats.get('losses', 0)}L, "
        f"{stats.get('closed_round_trips', 0)} closed)",
        f"Agent runs: {stats.get('agent_runs', 0)} | "
        f"trades proposed/executed/skipped: "
        f"{stats.get('agent_trades_proposed', 0)}/"
        f"{stats.get('agent_trades_executed', 0)}/"
        f"{stats.get('agent_trades_skipped', 0)}",
        f"Regime/no-go signals in digest: {stats.get('regime_flip_entries', 0)} "
        f"flips, {stats.get('no_go_digest_hints', 0)} no-go mentions",
    ]
    by_setup = stats.get("by_setup") or {}
    if by_setup:
        lines.append("P/L by setup:")
        for setup, b in sorted(by_setup.items(), key=lambda kv: kv[1].get("pnl", 0), reverse=True):
            lines.append(
                f"  - {setup}: ${b.get('pnl', 0):+.2f} "
                f"({int(b.get('wins', 0))}W/{int(b.get('losses', 0))}L)"
            )
    return "\n".join(lines)


def load_latest_weekly_lessons(db: Session) -> WeeklyPromptLesson | None:
    return (
        db.query(WeeklyPromptLesson)
        .order_by(WeeklyPromptLesson.generated_at.desc())
        .first()
    )


def _fallback_weekly_lesson(stats: dict[str, Any]) -> str:
    return (
        "RECENT_OUTCOMES\n"
        f"- {format_stats_brief(stats).replace(chr(10), '; ')}\n\n"
        "CALIBRATION (next week)\n"
        "- Review weekly stats in Diagnostics; run weekly compression if lessons look stale."
    )


async def compress_weekly(
    week_key: str | None = None,
    *,
    db: Session | None = None,
    force: bool = False,
) -> WeeklyPromptLesson | None:
    from .agent import llm as llm_module
    from .digest_store import recent_entries, _render_entries_for_llm
    from .settings_store import get_runtime_settings

    own = db is None
    if own:
        db = SessionLocal()
    try:
        wk = week_key or current_week_key()
        if not force:
            existing = (
                db.query(WeeklyPromptLesson)
                .filter(WeeklyPromptLesson.week_key == wk)
                .first()
            )
            if existing:
                print(f"[prompt_feedback] weekly lesson already present for {wk}; skipping")
                return existing

        since = week_start_utc()
        stats = compute_weekly_stats(db, settings.APP_MODE, since=since)
        stats_text = format_stats_brief(stats)

        entries = recent_entries(db, days=7)
        prior = load_latest_weekly_lessons(db)
        prior_text = ""
        if prior and prior.week_key != wk:
            prior_text = f"Prior week lesson ({prior.week_key}):\n{prior.text.strip()}\n\n"

        feedback_lines = (
            db.query(DigestEntry)
            .filter(
                DigestEntry.created_at >= since,
                DigestEntry.kind == "advisor_feedback",
            )
            .order_by(DigestEntry.created_at.desc())
            .limit(15)
            .all()
        )
        fb_block = ""
        if feedback_lines:
            fb_block = "Advisor feedback themes this week:\n" + "\n".join(
                f"- {e.summary[:200]}" for e in feedback_lines
            ) + "\n\n"

        user_prompt = (
            f"Compress calendar week {wk} into the required lesson note.\n\n"
            f"DETERMINISTIC STATS:\n{stats_text}\n\n"
            + (prior_text if prior_text else "")
            + fb_block
            + (
                f"EVENT LOG ({len(entries)} entries, last 7 days):\n"
                + _render_entries_for_llm(entries)
                if entries
                else "EVENT LOG: (no entries)"
            )
        )

        rs = get_runtime_settings(db)
        model_used = f"{rs.advisor_provider}:{rs.advisor_model}"
        try:
            text = await llm_module._chat(
                provider=rs.advisor_provider,
                host=rs.advisor_host,
                model=rs.advisor_model,
                api_key=rs.advisor_api_key,
                system=WEEKLY_LESSON_SYSTEM,
                user=user_prompt[:12000],
                temperature=0.2,
                timeout=180,
            )
            text = (text or "").strip() or _fallback_weekly_lesson(stats)
        except Exception as e:
            print(f"[prompt_feedback] weekly LLM failed: {e}")
            text = _fallback_weekly_lesson(stats)
            model_used = "fallback:stats"

        existing = (
            db.query(WeeklyPromptLesson)
            .filter(WeeklyPromptLesson.week_key == wk)
            .first()
        )
        if existing:
            existing.text = text[:8000]
            existing.stats_json = json.dumps(stats, default=str)[:8000]
            existing.generated_at = datetime.utcnow()
            existing.model_used = model_used
            existing.entries_covered = len(entries)
            row = existing
        else:
            row = WeeklyPromptLesson(
                week_key=wk,
                text=text[:8000],
                stats_json=json.dumps(stats, default=str)[:8000],
                model_used=model_used,
                entries_covered=len(entries),
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        print(f"[prompt_feedback] weekly lesson saved for {wk} via {model_used}")
        return row
    except Exception as e:
        print(f"[prompt_feedback] compress_weekly crashed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        if own:
            db.close()
