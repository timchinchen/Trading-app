"""One-shot agent execution: fetch -> analyze -> aggregate -> allocate -> execute."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from ...config import settings
from ...db import SessionLocal
from ...models import (
    AgentPositionPlan,
    AgentRun,
    AgentSignal,
    AgentTrade,
    AgentTweetAnalysis,
    Order,
    Trade,
    User,
    WatchlistItem,
)
from ..broker import AlpacaBroker
from ..digest_store import advisor_memory_prefix, append_entry as digest_append
from ..settings_store import get_runtime_settings
from . import analyzer, allocator, llm, playwright_client, swing_runner, twitter_client
from .intel import collect_intel


# Global single-flight guard. The cron scheduler AND the manual
# POST /agent/run-now endpoint both call `run_once`. Without this lock an
# operator mashing "Run now" while the cron fires (or two cron ticks
# overlapping because an earlier run went over the cron interval) would
# each compute budget independently and potentially double-execute the
# same BUY plan. The lock serialises runs; a second caller exits early
# with run_id=-1 and a skip line in the agent log instead of queueing up.
_RUN_LOCK = asyncio.Lock()


def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


class RunLog:
    def __init__(self):
        self.lines: list[str] = []

    def add(self, msg: str):
        line = f"[{_ts()}] {msg}"
        self.lines.append(line)
        print(f"[agent] {line}")

    def render(self) -> str:
        return "\n".join(self.lines)


def _today_realized_pl(db: Session, mode: str) -> float:
    """Realized P/L for today using FIFO cost-basis matching on Trade rows.

    Algorithm (per symbol, chronological):
      - BUYs push cost lots onto a FIFO queue (price, qty).
      - SELLs consume lots from the front; realized_pl += (sell_price - lot_price) * matched_qty.
      - Sells that exceed available lots (position opened before today) are
        matched against a synthetic lot at price=0 — this is conservative:
        it understates profits rather than overstating them.
      - Fees are ignored (not stored); the cap is intentionally conservative.
      - Only 'filled' orders matter; Trade rows are written on confirmed fills.

    Why this beats the old approach: the old code treated every SELL as pure
    revenue and every BUY as pure cost, producing wildly wrong P/L figures
    when both sides of a round-trip land in the same day.
    """
    from collections import deque
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Trade)
        .filter(Trade.mode == mode, Trade.filled_at >= start)
        .order_by(Trade.filled_at.asc())
        .all()
    )

    # Per-symbol FIFO lot queues: deque of [price, qty_remaining]
    lots: dict[str, deque] = {}
    realized = 0.0

    for t in rows:
        sym = (t.symbol or "").upper()
        price = float(t.price or 0.0)
        qty = float(t.qty or 0.0)
        if qty <= 0:
            continue

        if t.side == "buy":
            if sym not in lots:
                lots[sym] = deque()
            lots[sym].append([price, qty])
        elif t.side == "sell":
            q = lots.get(sym, deque())
            remaining = qty
            while remaining > 1e-9 and q:
                lot_price, lot_qty = q[0]
                matched = min(remaining, lot_qty)
                realized += (price - lot_price) * matched
                q[0][1] -= matched
                if q[0][1] <= 1e-9:
                    q.popleft()
                remaining -= matched
            if remaining > 1e-9:
                # Sold more than we bought today → position opened before today.
                # Use cost=0 (conservative: don't credit gains we can't verify).
                realized += price * remaining * 0  # explicit zero; no credit

    return round(realized, 4)


def _remaining_budget(db: Session, mode: str, budget_usd: float) -> float:
    """Budget remaining = `budget_usd` minus gross notional of today's
    agent BUY trades. `budget_usd` is sourced from runtime settings so
    Settings UI edits take effect on the next run."""
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used = 0.0
    rows = (
        db.query(AgentTrade)
        .filter(
            AgentTrade.mode == mode,
            AgentTrade.action == "executed",
            AgentTrade.side == "buy",
            AgentTrade.created_at >= start,
        )
        .all()
    )
    for r in rows:
        used += (r.notional or 0.0)
    return max(0.0, float(budget_usd) - used)


def _week_start_utc(now: datetime | None = None) -> datetime:
    """Monday 00:00 UTC of the current week."""
    now = now or datetime.utcnow()
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _weekly_deployed(db: Session, mode: str) -> float:
    """Gross notional of agent BUY trades executed since Monday 00:00 UTC."""
    start = _week_start_utc()
    used = 0.0
    rows = (
        db.query(AgentTrade)
        .filter(
            AgentTrade.mode == mode,
            AgentTrade.action == "executed",
            AgentTrade.side == "buy",
            AgentTrade.created_at >= start,
        )
        .all()
    )
    for r in rows:
        used += (r.notional or 0.0)
    return used


def _portfolio_brief(broker: AlpacaBroker) -> tuple[str, list[dict[str, Any]]]:
    """Return (human-readable brief, raw positions) for advisor prompts."""
    positions: list[dict[str, Any]] = []
    if not broker.configured:
        return "Positions: broker not configured", positions
    try:
        positions = broker.positions()
    except Exception as e:
        return f"Positions: error ({e})", positions
    if not positions:
        return "Positions: flat (no open positions)", positions
    lines = ["Positions:"]
    for p in positions:
        mv = p.get("market_value")
        pl = p.get("unrealized_pl")
        plp = p.get("unrealized_plpc")
        lines.append(
            f"  - {p.get('symbol')}: qty={p.get('qty')} "
            f"mv=${float(mv) if mv is not None else 0.0:.2f} "
            f"pl=${float(pl) if pl is not None else 0.0:+.2f} "
            f"({float(plp) * 100 if plp is not None else 0.0:+.2f}%)"
        )
    return "\n".join(lines), positions


def _build_advisor_context(
    *,
    signals: dict[str, dict[str, Any]],
    proposals: list[dict[str, Any]],
    portfolio_brief: str,
    intel_brief: str,
    swing_brief: str,
    daily_budget_remaining: float,
    weekly_remaining: float,
    open_positions: set[str],
    max_positions: int,
    memory_prefix: str = "",
) -> str:
    parts: list[str] = []
    if memory_prefix:
        parts.append(memory_prefix)
    parts.append(swing_brief)
    parts.append(portfolio_brief)
    parts.append(
        f"Budget: daily_remaining=${daily_budget_remaining:.2f} "
        f"weekly_remaining=${weekly_remaining:.2f} "
        f"open_positions={len(open_positions)}/{max_positions}"
    )
    parts.append("Signals (score/conf/mentions):")
    if signals:
        for sym, s in sorted(
            signals.items(),
            key=lambda kv: kv[1]["score"] * kv[1]["confidence"],
            reverse=True,
        )[:15]:
            parts.append(
                f"  - {sym}: score={s['score']:+.2f} conf={s['confidence']:.2f} "
                f"mentions={s['mentions']} :: {s.get('rationale', '')[:200]}"
            )
    else:
        parts.append("  (none)")

    parts.append("Trade proposals this run:")
    if proposals:
        for p in proposals:
            parts.append(
                f"  - {p['action'].upper()} {p['side']} {p['symbol']} "
                f"qty={p['qty']} ~${p.get('notional', 0):.2f} :: {p.get('reason', '')[:200]}"
            )
    else:
        parts.append("  (none)")

    parts.append("Market intel:")
    parts.append(intel_brief)
    return "\n".join(parts)


def _recently_bought_symbols(db: Session, mode: str, hours: int) -> dict[str, dict[str, Any]]:
    """Return {symbol -> {'price': float|None, 'created_at': datetime}} for any
    symbol that the agent executed a BUY on within the last `hours`. Used to
    stop us chasing the same ticker run-after-run."""
    if hours <= 0:
        return {}
    since = datetime.utcnow() - timedelta(hours=int(hours))
    rows = (
        db.query(AgentTrade)
        .filter(
            AgentTrade.mode == mode,
            AgentTrade.side == "buy",
            AgentTrade.action == "executed",
            AgentTrade.created_at >= since,
        )
        .order_by(AgentTrade.created_at.desc())
        .all()
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        sym = (r.symbol or "").upper()
        if sym and sym not in out:
            out[sym] = {"price": r.est_price, "created_at": r.created_at}
    return out


def _classify_regime(
    broker: "AlpacaBroker",
    *,
    symbol: str,
    ma_period: int,
    lookback_days: int,
    risk_on_mult: float,
    neutral_mult: float,
    risk_off_mult: float,
) -> "tuple[str, float]":
    """Classify the market into risk_on / neutral / risk_off and return the
    matching slot multiplier.

    Logic (reuses the bars already fetched by swing_runner if possible):
      risk_on  = price > MA  AND  MA slope (last 5 bars) positive
      risk_off = price < MA  AND  MA slope negative
      neutral  = everything else (mixed signal)

    Falls back to neutral if bars are unavailable so a data outage never
    blocks the run.
    """
    try:
        bars_map = broker.fetch_daily_bars([symbol], lookback_days=lookback_days)
        bars = bars_map.get(symbol.upper()) or []
    except Exception:
        bars = []

    if not bars or len(bars) < ma_period + 5:
        return "neutral", neutral_mult

    from . import swing_analyzer as sa
    from .technicals import T
    cs = T.closes(bars)
    sma = T.sma(cs, ma_period)
    sma_prev = T.sma(cs[:-5], ma_period) if len(cs) >= ma_period + 5 else None
    last = cs[-1] if cs else None
    if sma is None or last is None:
        return "neutral", neutral_mult

    above = last > sma
    rising = bool(sma_prev and sma > sma_prev)

    if above and rising:
        return "risk_on", risk_on_mult
    if not above and not rising:
        return "risk_off", risk_off_mult
    return "neutral", neutral_mult


def _adaptive_exit_proposals(
    broker: "AlpacaBroker",
    *,
    db: Session,
    mode: str,
    max_hold_days: int,
    trail_arm_pct: float,
    trail_retrace_pct: float,
    partial_take_pct: float,
    partial_take_fraction: float,
    existing_sell_symbols: set[str],
) -> list[dict[str, Any]]:
    """Priority-ordered exit engine evaluated every run.

    Priority per symbol (first match wins, deduped):
      1. Hard plan stop (AgentPositionPlan.stop_price hit)
      2. Time stop     (position age > max_hold_days)
      3. Momentum fade (peak_plpc >= trail_arm_pct AND current retrace >= trail_retrace_pct of peak)
      4. Partial TP    (plpc >= partial_take_pct AND not already partial_taken)

    All proposals carry executable qty (> 0). Skips logged with reason.
    Also updates peak_unrealized_plpc on open plans each run.
    """
    if not broker.configured:
        return []

    try:
        positions = broker.positions()
    except Exception as e:
        print(f"[adaptive-exit] could not fetch positions: {e}")
        return []

    # Load all open plans indexed by symbol.
    plans: dict[str, AgentPositionPlan] = {
        p.symbol.upper(): p
        for p in db.query(AgentPositionPlan)
        .filter(AgentPositionPlan.status == "open")
        .all()
    }

    proposals: list[dict[str, Any]] = []
    now = datetime.utcnow()

    for pos in positions:
        sym = (pos.get("symbol") or "").upper()
        if not sym or sym in existing_sell_symbols:
            continue
        qty = float(pos.get("qty") or 0.0)
        if qty <= 0:
            continue

        current_price = pos.get("current_price")
        try:
            current_price = float(current_price) if current_price is not None else None
        except Exception:
            current_price = None

        plpc = pos.get("unrealized_plpc")
        try:
            plpc = float(plpc) if plpc is not None else None
        except Exception:
            plpc = None

        plan = plans.get(sym)
        reason: Optional[str] = None
        sell_qty = qty          # default: full close
        exit_type = ""

        # ── 1. Hard plan stop ────────────────────────────────────────────
        if plan and current_price is not None and current_price <= plan.stop_price:
            reason = (
                f"hard-stop hit: last=${current_price:.2f} <= stop=${plan.stop_price:.2f} "
                f"(entry=${plan.entry_price:.2f}) closing {qty} shares"
            )
            exit_type = "hard_stop"

        # ── 2. Time stop ─────────────────────────────────────────────────
        if reason is None and plan:
            age_days = (now - plan.opened_at).total_seconds() / 86400.0
            if age_days >= max_hold_days:
                reason = (
                    f"time-stop: held {age_days:.1f}d >= {max_hold_days}d max "
                    f"closing {qty} shares"
                )
                exit_type = "time_stop"

        # Fallback age estimate from oldest executed BUY (no plan case)
        if reason is None and plan is None:
            oldest = (
                db.query(AgentTrade)
                .filter(
                    AgentTrade.mode == mode,
                    AgentTrade.symbol == sym,
                    AgentTrade.side == "buy",
                    AgentTrade.action == "executed",
                )
                .order_by(AgentTrade.created_at.asc())
                .first()
            )
            if oldest:
                age_days = (now - oldest.created_at).total_seconds() / 86400.0
                if age_days >= max_hold_days:
                    reason = (
                        f"time-stop (no plan): held {age_days:.1f}d >= {max_hold_days}d "
                        f"closing {qty} shares"
                    )
                    exit_type = "time_stop"

        # ── 3. Momentum fade (trailing retrace) ──────────────────────────
        if reason is None and plpc is not None and plan is not None:
            # Update peak gain in plan row.
            if plpc > (plan.peak_unrealized_plpc or 0.0):
                plan.peak_unrealized_plpc = plpc
                db.add(plan)

            peak = plan.peak_unrealized_plpc or 0.0
            if peak >= trail_arm_pct and plpc < peak:
                retrace_frac = (peak - plpc) / peak if peak > 0 else 0.0
                if retrace_frac >= trail_retrace_pct:
                    reason = (
                        f"momentum-fade: peak={peak * 100:+.2f}% "
                        f"current={plpc * 100:+.2f}% "
                        f"retrace={retrace_frac * 100:.1f}% >= {trail_retrace_pct * 100:.0f}% "
                        f"closing {qty} shares"
                    )
                    exit_type = "momentum_fade"

        # ── 4. Partial TP ────────────────────────────────────────────────
        if (
            reason is None
            and plpc is not None
            and partial_take_pct > 0
            and plpc >= partial_take_pct
            and plan is not None
            and not plan.partial_taken
        ):
            sell_qty = round(qty * max(0.01, min(1.0, partial_take_fraction)), 6)
            if sell_qty <= 0:
                sell_qty = qty
            plan.partial_taken = 1
            db.add(plan)
            reason = (
                f"partial-TP: {plpc * 100:+.2f}% >= {partial_take_pct * 100:.1f}% threshold "
                f"selling {sell_qty} of {qty} shares ({partial_take_fraction * 100:.0f}%)"
            )
            exit_type = "partial_tp"

        if reason is None:
            continue

        notional = round(sell_qty * float(current_price or 0.0), 2)
        proposals.append({
            "symbol": sym,
            "side": "sell",
            "qty": sell_qty,
            "est_price": current_price,
            "notional": notional,
            "action": "proposed",
            "reason": reason,
            "exit_type": exit_type,
        })

    try:
        db.commit()
    except Exception:
        db.rollback()

    return proposals


def _coerce_pct(label: str, env_key: str, pct: float) -> float:
    """Accept both fractional (0.07) and whole-percent (7.0) inputs.

    If someone saves `7` thinking "7%" we don't want to silently treat it
    as 700%, so any positive value > 1.0 is divided by 100 and logged.
    """
    if pct <= 0:
        return 0.0
    if pct > 1.0:
        coerced = pct / 100.0
        print(
            f"[{label}] coercing {env_key}={pct} -> {coerced} "
            f"(value > 1 interpreted as whole percent)"
        )
        return coerced
    return pct


def _resolve_entry(
    db: Session, *, mode: str, sym: str, alpaca_entry: Any
) -> Optional[float]:
    """Alpaca's avg_entry_price first, fall back to our latest executed BUY."""
    if alpaca_entry:
        try:
            return float(alpaca_entry)
        except Exception:
            pass
    row = (
        db.query(AgentTrade)
        .filter(
            AgentTrade.mode == mode,
            AgentTrade.symbol == sym,
            AgentTrade.side == "buy",
            AgentTrade.action == "executed",
        )
        .order_by(AgentTrade.created_at.desc())
        .first()
    )
    try:
        return float(row.est_price) if row and row.est_price is not None else None
    except Exception:
        return None


def _take_profit_proposals(
    broker: AlpacaBroker,
    *,
    db: Session,
    mode: str,
    take_profit_pct: float,
    stop_loss_pct: float,
    already_in_proposals: set[str],
) -> list[dict[str, Any]]:
    """Emit SELL-to-close proposals on either take-profit or stop-loss.

    Both thresholds are fractions (0.07 = 7%). Either can be 0 to disable
    that leg. We evaluate take-profit first so a single position that
    somehow satisfies both (pathological) prefers the profit-side log.

    Uses Alpaca's avg_entry_price as the canonical entry, with a fallback
    to the latest executed AgentTrade.est_price.
    """
    if not broker.configured:
        return []
    tp = _coerce_pct("take-profit", "AGENT_TAKE_PROFIT_PCT", take_profit_pct)
    sl = _coerce_pct("stop-loss", "AGENT_STOP_LOSS_PCT", stop_loss_pct)
    if tp <= 0 and sl <= 0:
        return []

    proposals: list[dict[str, Any]] = []
    try:
        positions = broker.positions()
    except Exception as e:
        print(f"[take-profit] could not fetch positions: {e}")
        return []

    for p in positions:
        sym = (p.get("symbol") or "").upper()
        if not sym or sym in already_in_proposals:
            continue
        qty = float(p.get("qty") or 0.0)
        if qty <= 0:
            continue

        entry = _resolve_entry(db, mode=mode, sym=sym, alpaca_entry=p.get("avg_entry_price"))
        current = p.get("current_price")
        plpc = p.get("unrealized_plpc")

        # Compute gain fraction if the broker didn't provide it.
        if plpc is None and entry and current:
            try:
                plpc = (float(current) - float(entry)) / float(entry)
            except Exception:
                plpc = None
        if plpc is None:
            continue

        reason: Optional[str] = None
        if tp > 0 and plpc >= tp:
            reason = (
                f"take-profit hit: {plpc * 100:+.2f}% "
                f"(entry=${float(entry or 0):.2f} -> last=${float(current or 0):.2f}) "
                f"closing {qty} shares"
            )
        elif sl > 0 and plpc <= -sl:
            reason = (
                f"stop-loss hit: {plpc * 100:+.2f}% "
                f"(entry=${float(entry or 0):.2f} -> last=${float(current or 0):.2f}) "
                f"closing {qty} shares"
            )
        if not reason:
            continue

        notional = round(qty * float(current or entry or 0.0), 2)
        proposals.append({
            "symbol": sym,
            "side": "sell",
            "qty": qty,
            "est_price": float(current) if current else None,
            "notional": notional,
            "action": "proposed",
            "reason": reason,
        })
    return proposals


def _ensure_watchlisted(db: Session, symbols: list[str]) -> list[str]:
    """Make sure every symbol the agent is interested in lives in the primary
    user's watchlist. Returns the list of symbols newly added."""
    if not symbols:
        return []
    # Single-user app: the first registered user owns the dashboard.
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        return []
    added: list[str] = []
    for raw in symbols:
        sym = (raw or "").upper().strip()
        if not sym:
            continue
        existing = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == sym)
            .first()
        )
        if existing:
            continue
        db.add(WatchlistItem(user_id=user.id, symbol=sym, feed="ws"))
        added.append(sym)
    if added:
        db.commit()
    return added


async def run_once(broker: AlpacaBroker) -> int:
    """Run the agent pipeline once.

    Returns the AgentRun id on success, or -1 if another run is already in
    progress (single-flight guard). Callers (cron + /agent/run-now) can
    distinguish a skipped call from an error via the return value."""
    if _RUN_LOCK.locked():
        print("[agent] run_once skipped: another run is already in progress")
        return -1
    async with _RUN_LOCK:
        return await _run_once_impl(broker)


async def _run_once_impl(broker: AlpacaBroker) -> int:
    db = SessionLocal()
    run = AgentRun(mode=settings.APP_MODE, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    log = RunLog()
    rs = get_runtime_settings(db)
    log.add(
        f"run #{run_id} starting | mode={settings.APP_MODE} | "
        f"budget=${rs.agent_budget_usd} max/pos=${rs.agent_max_position_usd} | "
        f"llm={rs.llm_provider}:{rs.llm_model}"
    )
    digest_append(
        kind="agent_run",
        summary=f"run #{run_id} started ({settings.APP_MODE}, llm={rs.llm_provider}:{rs.llm_model})",
        data={"run_id": run_id, "mode": settings.APP_MODE},
        db=db,
    )

    def _save_logs():
        run.logs = log.render()[:60000]
        db.commit()

    try:
        handles = rs.twitter_accounts_list
        log.add(f"configured handles: {len(handles)} -> {', '.join(handles) or '(none)'}")
        if not handles:
            run.status = "skipped"
            run.summary = "no twitter accounts configured"
            run.finished_at = datetime.utcnow()
            _save_logs()
            return run_id

        # Daily-loss cap check
        pl = _today_realized_pl(db, settings.APP_MODE)
        cap = abs(rs.agent_daily_loss_cap_usd)
        log.add(
            f"today realized P/L (FIFO): ${pl:+.2f} | "
            f"loss cap: -${cap:.2f} | "
            f"{'CAP HIT — skipping' if cap > 0 and pl <= -cap else 'within cap'}"
        )
        if cap > 0 and pl <= -cap:
            run.status = "skipped"
            run.summary = f"daily loss cap hit (P/L={pl:.2f})"
            run.finished_at = datetime.utcnow()
            _save_logs()
            return run_id

        # 1. Fetch tweets via headless Chromium + twscrape cookies.
        # Playwright is our primary source since Dec-2025 twscrape 0.17.0 hit
        # parsing failures that self-lock accounts for 15 minutes. twscrape
        # remains as a fallback.
        log.add(f"fetching tweets via playwright (lookback={rs.agent_lookback_hours}h, "
                f"max/account={rs.agent_max_tweets_per_account}, "
                f"per-account timeout={rs.agent_per_account_timeout_s}s) ...")
        _save_logs()

        def _tw_log(msg: str):
            log.add(msg)
            # Persist every few lines so the UI can poll for progress.
            if len(log.lines) % 3 == 0:
                try:
                    _save_logs()
                except Exception:
                    pass

        tweets: list[dict] = []
        playwright_failed = False
        try:
            tweets = await playwright_client.fetch_recent_tweets(
                handles=handles,
                lookback_hours=rs.agent_lookback_hours,
                max_per_account=rs.agent_max_tweets_per_account,
                db_path=settings.TWSCRAPE_DB,
                per_account_timeout_s=rs.agent_per_account_timeout_s,
                log=_tw_log,
            )
        except playwright_client.PlaywrightNotInstalledError as e:
            log.add(f"playwright unavailable: {e}")
            log.add("falling back to twscrape ...")
            playwright_failed = True
        except playwright_client.CookiesMissingError as e:
            log.add(f"ERROR cookies missing: {e}")
            run.status = "error"
            run.summary = str(e)
            run.finished_at = datetime.utcnow()
            _save_logs()
            return run_id
        except Exception as e:
            log.add(f"playwright error: {e}")
            log.add("falling back to twscrape ...")
            playwright_failed = True

        if playwright_failed:
            try:
                tweets = await twitter_client.fetch_recent_tweets(
                    handles=handles,
                    lookback_hours=rs.agent_lookback_hours,
                    max_per_account=rs.agent_max_tweets_per_account,
                    db_path=settings.TWSCRAPE_DB,
                    per_account_timeout_s=rs.agent_per_account_timeout_s,
                    log=_tw_log,
                )
            except twitter_client.TwitterPoolExhaustedError as e:
                log.add(f"ERROR twscrape pool exhausted: {e}")
                log.add("  fix: run `.venv/bin/twscrape --db ./twscrape.db reset_locks` "
                        "then `add_cookies` if cookies expired.")
                run.status = "error"
                run.summary = f"twscrape pool exhausted: {e}"
                run.finished_at = datetime.utcnow()
                _save_logs()
                return run_id
            except Exception as e:
                log.add(f"ERROR tweet fetch (both backends): {e}")
                run.status = "error"
                run.summary = f"tweet fetch failed: {e}"
                run.finished_at = datetime.utcnow()
                _save_logs()
                return run_id

        run.accounts_scanned = len(handles)
        run.tweets_fetched = len(tweets)
        # group counts
        by_handle: dict[str, int] = {}
        for tw in tweets:
            by_handle[tw["handle"]] = by_handle.get(tw["handle"], 0) + 1
        log.add(f"fetched {len(tweets)} tweets total")
        if by_handle:
            log.add("  per handle: " + ", ".join(f"@{h}={n}" for h, n in by_handle.items()))
        missing = [h for h in handles if h.lower() not in by_handle]
        if missing:
            log.add(f"  no tweets from: {', '.join('@'+m for m in missing)}")
        db.commit()
        _save_logs()

        # 2. LLM analyze each tweet (limited concurrency; tunable via Settings).
        log.add(f"analysing tweets via {rs.llm_provider} ({rs.llm_model}) "
                f"[concurrency={rs.agent_llm_concurrency}] ...")
        sem = asyncio.Semaphore(max(1, int(rs.agent_llm_concurrency)))
        analyses: list[dict[str, Any]] = []

        async def analyze(tw):
            async with sem:
                a = await llm.analyze_tweet(
                    tw["text"], tw["handle"], rs.llm_host, rs.llm_model,
                    provider=rs.llm_provider, api_key=rs.llm_api_key,
                )
            analyses.append({"tweet": tw, "analysis": a})

            # Persist per-tweet analysis for the debug panel
            tickers = a.get("tickers") or []
            is_noise = bool((a.get("meta") or {}).get("is_noise"))
            err = (a.get("meta") or {}).get("error")
            db.add(AgentTweetAnalysis(
                run_id=run_id,
                handle=tw["handle"],
                tweet_id=tw.get("tweet_id") or "",
                tweet_url=tw.get("url"),
                tweet_text=(tw.get("text") or "")[:4000],
                tweet_created_at=tw.get("created_at"),
                analysis_json=json.dumps(a)[:8000],
                tickers_count=len(tickers),
                is_noise=1 if is_noise else 0,
                error=err,
            ))
            db.commit()

        await asyncio.gather(*(analyze(tw) for tw in tweets))
        non_noise = sum(1 for a in analyses if not (a["analysis"].get("meta") or {}).get("is_noise"))
        total_tickers = sum(len(a["analysis"].get("tickers") or []) for a in analyses)
        log.add(f"analysed {len(analyses)} tweets | non-noise={non_noise} | total ticker mentions={total_tickers}")
        _save_logs()

        # 3. Aggregate — noise-marked tweets excluded; handle weights applied.
        handle_weights, hw_warn = analyzer.normalize_handle_weights(rs.agent_handle_weights)
        if hw_warn:
            log.add(f"[handle-weights] WARNING: {hw_warn} — using default weights")
        if handle_weights:
            top_w = sorted(handle_weights.items(), key=lambda x: x[1], reverse=True)[:5]
            log.add(
                "handle weights active: "
                + ", ".join(f"@{h}={w:.2f}" for h, w in top_w)
                + (f" (+{len(handle_weights) - 5} more)" if len(handle_weights) > 5 else "")
            )
        signals = analyzer.aggregate(analyses, handle_weights=handle_weights)
        ns = analyzer.pop_noise_stats(signals)
        log.add(
            f"aggregation: total={ns['total']} used={ns['used']} "
            f"noise_filtered={ns['noise']} → {len(signals)} tickers"
        )

        # 3a. Collect market intelligence (stockanalysis movers + TradingView news)
        # in parallel-ish - best-effort, never blocks the run on failures.
        try:
            intel = await collect_intel(log=_tw_log)
        except Exception as e:
            log.add(f"intel: unexpected error ({e}); continuing without corroboration")
            from .intel import MarketIntel
            intel = MarketIntel()

        intel_brief_text = intel.brief()
        run.intel_brief = intel_brief_text[:4000]

        # 3b. Apply corroboration boost where ticker also appears in movers/news.
        analyzer.apply_intel_boost(
            signals,
            corroborating_symbols=intel.corroborating_symbols(),
            avoid_symbols=intel.symbols_to_avoid(),
            boost=rs.agent_intel_boost,
        )
        boosted = [s for s, d in signals.items() if d.get("corroborated_by")]
        if boosted:
            log.add(f"intel boost applied to: {', '.join(boosted)}")
            digest_append(
                kind="intel_highlight",
                summary=f"intel corroborated {len(boosted)} tickers: {', '.join(boosted[:10])}",
                data={"run_id": run_id, "symbols": boosted[:25]},
                db=db,
            )
        log.add(f"aggregated into {len(signals)} tickers: " +
                ", ".join(f"{s}({d['score']:+.2f}/{d['mentions']})" for s, d in signals.items()))
        for sym, s in signals.items():
            db.add(AgentSignal(
                run_id=run_id, symbol=sym,
                score=s["score"], confidence=s["confidence"], mentions=s["mentions"],
                rationale=s["rationale"],
                sources=json.dumps(s["sources"])[:8000],
            ))
        db.commit()

        # 4. Allocate
        raw_positions: list[dict[str, Any]] = broker.positions() if broker.configured else []
        open_positions = {p["symbol"] for p in raw_positions}
        # qty map for bearish reversal sizing — qty=0 orders can't execute.
        open_position_qtys: dict[str, float] = {
            p["symbol"]: float(p.get("qty") or 0.0) for p in raw_positions
        }
        daily_budget = _remaining_budget(db, settings.APP_MODE, rs.agent_budget_usd)
        weekly_used = _weekly_deployed(db, settings.APP_MODE)
        weekly_remaining = max(0.0, rs.agent_weekly_budget_usd - weekly_used)
        log.add(
            f"budget: daily_remaining=${daily_budget:.2f} | "
            f"weekly_used=${weekly_used:.2f}/${rs.agent_weekly_budget_usd:.2f} "
            f"(remaining=${weekly_remaining:.2f}) | "
            f"open={len(open_positions)}/{rs.agent_max_open_positions} "
            f"slot=${rs.agent_min_position_usd:.0f}-${rs.agent_max_position_usd:.0f}"
        )
        log.add(f"open positions: {sorted(open_positions) or 'flat'}")

        # ── Regime classification ────────────────────────────────────────
        tweet_regime, risk_mult = _classify_regime(
            broker,
            symbol=rs.swing_market_filter_symbol,
            ma_period=rs.swing_market_filter_ma,
            lookback_days=rs.swing_bar_lookback_days,
            risk_on_mult=rs.agent_regime_risk_on_mult,
            neutral_mult=rs.agent_regime_neutral_mult,
            risk_off_mult=rs.agent_regime_risk_off_mult,
        )
        block_buys = (
            tweet_regime == "risk_off" and rs.agent_risk_off_block_new_buys
        )
        log.add(
            f"regime: {tweet_regime} | risk_mult={risk_mult:.2f} | "
            f"block_new_buys={block_buys}"
        )

        def _price(sym: str) -> float | None:
            q = broker.latest_quote(sym)
            return q.get("ask") or q.get("last")

        # Block names we already bought in the last N hours so we rotate into
        # fresh ideas each run instead of stacking the same ticker.
        recently_bought = _recently_bought_symbols(
            db, settings.APP_MODE, rs.agent_recent_trade_window_hours
        )
        if recently_bought:
            log.add(
                f"recent BUY exclusion ({rs.agent_recent_trade_window_hours}h): "
                + ", ".join(sorted(recently_bought.keys()))
            )

        # --- 4a. Swing-trading skill pass ---------------------------------
        # Apply the 1-2 week setup scanner to every watchlist symbol. This is
        # independent of the tweet pipeline, so we still benefit from a full
        # technical scan even when no tweets fetched.
        regime = {"go": True, "reason": "swing disabled", "symbol": rs.swing_market_filter_symbol}
        swing_plans: dict[str, Any] = {}
        swing_snaps: dict[str, Any] = {}
        swing_proposals: list[dict[str, Any]] = []
        tm_proposals: list[dict[str, Any]] = []

        if rs.swing_enabled:
            regime = swing_runner.evaluate_market_regime(
                broker,
                filter_symbol=rs.swing_market_filter_symbol,
                ma=rs.swing_market_filter_ma,
                lookback_days=rs.swing_bar_lookback_days,
                log=log.add,
            )
            digest_append(
                kind="regime_flip",
                symbol=rs.swing_market_filter_symbol,
                summary=(
                    f"market regime {'GO' if regime.get('go') else 'NO-GO'}: "
                    f"{regime.get('reason', '')[:200]}"
                ),
                data={"run_id": run_id, "regime": regime},
                db=db,
            )
            tweet_syms = sorted(signals.keys())
            swing_plans, swing_snaps = swing_runner.scan_watchlist_for_setups(
                broker, db,
                lookback_days=rs.swing_bar_lookback_days,
                extra_symbols=tweet_syms,
                spy_symbol=rs.swing_market_filter_symbol,
                log=log.add,
            )

            swing_proposals = swing_runner.build_swing_proposals(
                swing_plans,
                signals=signals,
                open_symbols=open_positions,
                recently_bought=recently_bought,
                budget_remaining=daily_budget,
                weekly_remaining=weekly_remaining,
                total_capital_usd=rs.agent_budget_usd,
                risk_pct=rs.swing_risk_per_trade_pct,
                min_rr=rs.swing_min_rr,
                min_position_usd=rs.agent_min_position_usd,
                max_position_usd=rs.agent_max_position_usd,
                max_open_positions=rs.agent_max_open_positions,
                regime_go=bool(regime.get("go")),
            )

            # Trade-management pass: stop hits, time stops, breakeven bumps.
            tm_proposals = swing_runner.trade_management_pass(
                broker, db,
                time_stop_days=rs.swing_time_stop_days,
                move_stop_be_pct=rs.swing_move_stop_be_pct,
                partial_pct=rs.swing_partial_pct,
                log=log.add,
            )

        # --- 4b. Tweet-sentiment allocator (legacy path) ------------------
        # Only fills slots the swing scanner didn't already fill, so the skill
        # remains the primary entry criterion.
        swing_buy_syms = {
            (p["symbol"] or "").upper()
            for p in swing_proposals
            if p.get("side") == "buy" and p.get("action") == "proposed"
        }
        # Count how many real swing BUYs we already committed to so the
        # tweet allocator respects the same position cap.
        effective_open = open_positions | swing_buy_syms
        tweet_proposals = allocator.propose_trades(
            signals=signals,
            open_symbols=effective_open,
            budget_remaining=daily_budget - sum(p.get("notional") or 0.0 for p in swing_proposals if p.get("action") == "proposed" and p.get("side") == "buy"),
            weekly_remaining=weekly_remaining - sum(p.get("notional") or 0.0 for p in swing_proposals if p.get("action") == "proposed" and p.get("side") == "buy"),
            min_position_usd=rs.agent_min_position_usd,
            max_position_usd=rs.agent_max_position_usd,
            max_open_positions=rs.agent_max_open_positions,
            get_price=_price,
            min_score=rs.agent_min_score,
            min_confidence=rs.agent_min_confidence,
            top_n=rs.agent_top_n_candidates,
            recently_bought=recently_bought,
            open_position_qtys=open_position_qtys,
            risk_multiplier=risk_mult,
            block_new_buys=block_buys,
        ) if not rs.swing_enabled or not regime.get("go") else []
        # When swing is on and regime is GO we intentionally suppress the
        # tweet-only allocator so the LLM doesn't chase non-setup signals.

        proposals = swing_proposals + tm_proposals + tweet_proposals

        # ── Adaptive exit engine ─────────────────────────────────────────
        # Runs after swing/tweet passes so we never double-up on a symbol
        # already earmarked for exit. Priority: hard-stop > time-stop >
        # momentum-fade > partial-TP.
        ae_in_hand = {
            (p["symbol"] or "").upper()
            for p in proposals
            if p.get("side") == "sell"
        }
        ae_proposals = _adaptive_exit_proposals(
            broker,
            db=db,
            mode=settings.APP_MODE,
            max_hold_days=rs.agent_max_hold_days,
            trail_arm_pct=rs.agent_trail_arm_pct,
            trail_retrace_pct=rs.agent_trail_retrace_pct,
            partial_take_pct=rs.agent_partial_take_pct,
            partial_take_fraction=rs.agent_partial_take_fraction,
            existing_sell_symbols=ae_in_hand,
        )
        if ae_proposals:
            by_type: dict[str, int] = {}
            for p in ae_proposals:
                t = p.get("exit_type", "other")
                by_type[t] = by_type.get(t, 0) + 1
            log.add(
                f"adaptive-exit: {len(ae_proposals)} proposals "
                + " ".join(f"{t}={n}" for t, n in sorted(by_type.items()))
            )
        proposals = proposals + ae_proposals

        # ── Static TP/SL sweep (legacy fallback for positions without plans)
        # Covers anything the adaptive engine didn't handle (no plan, no bars).
        tp_in_hand = {
            (p["symbol"] or "").upper()
            for p in proposals
            if p.get("side") == "sell"
        }
        tp_proposals = _take_profit_proposals(
            broker,
            db=db,
            mode=settings.APP_MODE,
            take_profit_pct=rs.agent_take_profit_pct,
            stop_loss_pct=rs.agent_stop_loss_pct,
            already_in_proposals=tp_in_hand,
        )
        if tp_proposals:
            log.add(
                f"tp/sl sweep (tp={rs.agent_take_profit_pct * 100:.1f}% "
                f"sl={rs.agent_stop_loss_pct * 100:.1f}%): "
                + ", ".join(f"{p['symbol']} ({p['reason']})" for p in tp_proposals)
            )
        proposals = proposals + tp_proposals

        for p in proposals:
            log.add(f"  candidate {p['symbol']} {p['side']} qty={p['qty']} "
                    f"notional=${p['notional']} -> {p['action']} ({p.get('reason','')})")

        # 4b. Per-ticker enrichment for the shortlist only (keeps us well below
        # the FMP free-tier 250/day and SEC 10-req/sec limits). We enrich
        # anything we're proposing BUY or SELL on this run.
        shortlist = sorted({
            (p["symbol"] or "").upper()
            for p in proposals
            if p.get("action") == "proposed" and p.get("symbol")
        })
        if shortlist:
            try:
                await intel.enrich_symbols(
                    shortlist,
                    fmp_api_key=rs.fmp_api_key,
                    fmp_base_url=rs.fmp_base_url,
                    sec_user_agent=rs.sec_user_agent,
                    stocktwits_cookies=rs.stocktwits_cookies,
                    log=_tw_log,
                )
                # Update the run's stored brief with enrichment baked in.
                intel_brief_text = intel.brief()
                run.intel_brief = intel_brief_text[:6000]
            except Exception as e:
                log.add(f"enrichment failed: {e}")

        # 5. Decide auto-execute
        auto_execute = (
            settings.APP_MODE == "paper"
            or (settings.APP_MODE == "live" and rs.agent_auto_execute_live)
        )
        log.add(f"auto_execute={auto_execute} (app_mode={settings.APP_MODE}, "
                f"auto_exec_live={rs.agent_auto_execute_live})")

        proposed_count = 0
        executed_count = 0

        for p in proposals:
            at = AgentTrade(
                run_id=run_id, symbol=p["symbol"], side=p["side"], qty=p["qty"],
                est_price=p["est_price"], notional=p["notional"],
                action=p["action"], reason=p.get("reason"),
                mode=settings.APP_MODE,
                setup_type=p.get("setup_type"),
                entry_price=p.get("entry_price"),
                stop_price=p.get("stop_price"),
                target_price=p.get("target_price"),
                risk_reward=p.get("risk_reward"),
            )
            db.add(at)
            db.flush()

            if p["action"] != "proposed":
                continue
            proposed_count += 1

            if not auto_execute or not broker.configured or p["qty"] <= 0:
                at.action = "proposed"
                continue
            try:
                result = broker.place_order(
                    symbol=p["symbol"], qty=p["qty"],
                    side=p["side"], type_="market",
                )
                order = Order(
                    alpaca_id=result.get("alpaca_id"),
                    symbol=result["symbol"], qty=result["qty"],
                    side=result["side"], type=result["type"],
                    limit_price=result.get("limit_price"),
                    status=result.get("status", "new"),
                    mode=settings.APP_MODE,
                )
                db.add(order)
                db.flush()
                at.order_id = order.id
                at.action = "executed"
                executed_count += 1
                log.add(f"EXEC {p['symbol']} {p['side']} qty={p['qty']} alpaca_id={order.alpaca_id}")
                digest_append(
                    kind="trade_exec",
                    symbol=p["symbol"],
                    summary=(
                        f"{p['side'].upper()} {p['qty']} {p['symbol']} "
                        f"~${p.get('notional', 0):.2f} "
                        f"({p.get('setup_type') or 'signal'})"
                    ),
                    data={
                        "run_id": run_id,
                        "side": p["side"],
                        "qty": p["qty"],
                        "notional": p.get("notional"),
                        "entry": p.get("entry_price"),
                        "stop": p.get("stop_price"),
                        "target": p.get("target_price"),
                        "rr": p.get("risk_reward"),
                        "setup": p.get("setup_type"),
                        "reason": (p.get("reason") or "")[:200],
                    },
                    db=db,
                )
                # Persist swing plan so subsequent runs can enforce stop/time/breakeven rules.
                plan = swing_plans.get(p["symbol"]) if p.get("side") == "buy" else None
                if plan:
                    try:
                        swing_runner.persist_position_plan(
                            db, plan, run_id=run_id, mode=settings.APP_MODE,
                        )
                    except Exception as e:
                        log.add(f"swing: could not persist plan for {p['symbol']}: {e}")
            except Exception as e:
                at.action = "skipped"
                at.reason = (at.reason or "") + f" | exec failed: {e}"
                log.add(f"EXEC FAILED {p['symbol']}: {e}")

        run.trades_proposed = proposed_count
        run.trades_executed = executed_count
        db.commit()
        _save_logs()

        # 5b. Auto-watchlist: every symbol we took an interest in this run
        # (executed, proposed, or even skipped-due-to-budget) is added to the
        # primary user's dashboard watchlist so they show up in "Watchlist
        # (live)" for ongoing monitoring.
        interested_set: set[str] = set()
        for p in proposals:
            sym = (p.get("symbol") or "").upper()
            if not sym:
                continue
            # BUYs we are proposing or executing this run.
            if p.get("side") == "buy" and p.get("action") in ("executed", "proposed"):
                interested_set.add(sym)
            # Anything flagged for sale (user should see those live).
            if p.get("side") == "sell":
                interested_set.add(sym)
            # Names the swing scanner flagged as watch-only (regime no-go or
            # blocked by caps): the user asked for them to land on the watchlist.
            if (
                p.get("action") == "skipped"
                and p.get("setup_type")
                and "market regime NO-GO" in (p.get("reason") or "")
            ):
                interested_set.add(sym)
        # Any swing plan discovered this run (even if we didn't propose it).
        for sym in swing_plans.keys():
            interested_set.add(sym.upper())
        interested = sorted(interested_set)
        if interested:
            added = _ensure_watchlisted(db, interested)
            if added:
                log.add(f"watchlist: added {len(added)} new symbols -> {', '.join(added)}")
                digest_append(
                    kind="watchlist_delta",
                    summary=f"auto-added {len(added)} symbols: {', '.join(added)}",
                    data={"run_id": run_id, "added": added},
                    db=db,
                )
                # Kick the market-data service so these stream live on the dashboard.
                try:
                    from ...deps import get_market_data
                    _md = get_market_data()
                    if _md:
                        for sym in added:
                            await _md.subscribe(sym, "ws")
                except Exception as e:
                    log.add(f"watchlist: stream subscribe failed ({e})")

        # 6. Portfolio advisor: structured recommendation fed to the UI.
        portfolio_text, _ = _portfolio_brief(broker)
        swing_brief_text = swing_runner.brief_for_prompt(
            regime, swing_plans, swing_snaps,
        ) if rs.swing_enabled else ""
        memory_prefix = advisor_memory_prefix(db)
        advisor_context = _build_advisor_context(
            signals=signals,
            proposals=proposals,
            portfolio_brief=portfolio_text,
            intel_brief=intel_brief_text,
            swing_brief=swing_brief_text,
            daily_budget_remaining=daily_budget,
            weekly_remaining=weekly_remaining,
            open_positions=open_positions,
            max_positions=rs.agent_max_open_positions,
            memory_prefix=memory_prefix,
        )
        log.add(
            f"advisor: generating portfolio recommendation via "
            f"{rs.advisor_provider} ({rs.advisor_model}) "
            f"[deep_llm_enabled={rs.deep_llm_enabled}] ..."
        )
        _save_logs()
        advice = await llm.advise_portfolio(
            advisor_context,
            rs.advisor_host,
            rs.advisor_model,
            provider=rs.advisor_provider,
            api_key=rs.advisor_api_key,
        )
        run.advice = advice[:6000]

        # Short single-line summary for list views (first non-empty line of advice).
        first_line = next(
            (ln.strip() for ln in advice.splitlines() if ln.strip()),
            "(no advice generated)",
        )
        run.summary = first_line[:500]
        run.status = "ok"
        run.finished_at = datetime.utcnow()
        log.add(f"DONE status=ok proposed={proposed_count} executed={executed_count}")
        digest_append(
            kind="advisor",
            summary=f"advisor ({rs.advisor_provider}:{rs.advisor_model}): {first_line[:240]}",
            data={
                "run_id": run_id,
                "provider": rs.advisor_provider,
                "model": rs.advisor_model,
                "deep_llm_enabled": rs.deep_llm_enabled,
            },
            db=db,
        )
        digest_append(
            kind="agent_run",
            summary=(
                f"run #{run_id} done: proposed={proposed_count} "
                f"executed={executed_count} signals={len(signals)} "
                f"tweets={len(tweets)}"
            ),
            data={
                "run_id": run_id,
                "proposed": proposed_count,
                "executed": executed_count,
                "signals": len(signals),
                "tweets": len(tweets),
            },
            db=db,
        )
        _save_logs()
        return run_id

    except Exception as e:
        log.add(f"FATAL {e}")
        run.status = "error"
        run.summary = f"unexpected error: {e}"
        run.finished_at = datetime.utcnow()
        digest_append(
            kind="error",
            summary=f"run #{run_id} crashed: {str(e)[:240]}",
            data={"run_id": run_id, "error": str(e)[:500]},
            db=db,
        )
        _save_logs()
        return run_id
    finally:
        db.close()
