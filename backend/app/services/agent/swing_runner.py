"""Runner helpers that implement the 1-2 week swing-trading skill.

Split out of runner.py to keep the pipeline readable. Everything in here is
pure orchestration — the actual logic lives in technicals.py + swing_analyzer.py.

Public entry points:
    evaluate_market_regime(broker, rs, log)          -> regime dict
    scan_watchlist_for_setups(broker, db, rs, log)   -> (plans, snapshots)
    build_swing_proposals(...)                       -> proposals list
    sync_position_plans(db, plans, mode)             -> writes AgentPositionPlan rows
    trade_management_pass(broker, db, rs, plans_by_sym, log) -> exit proposals
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..broker import AlpacaBroker
from . import swing_analyzer, technicals as T

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return None


def _watchlist_symbols(db: Session) -> list[str]:
    """All symbols in the primary user's watchlist (single-user app)."""
    from ...models import User, WatchlistItem
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        return []
    rows = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id)
        .all()
    )
    return sorted({(r.symbol or "").upper() for r in rows if r.symbol})


def evaluate_market_regime(
    broker: AlpacaBroker,
    *,
    filter_symbol: str,
    ma: int,
    lookback_days: int,
    log: LogFn = _noop,
) -> dict[str, Any]:
    """Decide go/no-go using the broader-market filter symbol (default SPY)."""
    bars_map = broker.fetch_daily_bars([filter_symbol], lookback_days=lookback_days)
    bars = bars_map.get(filter_symbol.upper()) or []
    if not bars:
        log(f"swing: market-filter bars unavailable for {filter_symbol}; regime=skip")
        return {"symbol": filter_symbol, "go": False, "reason": "bars unavailable"}
    regime = swing_analyzer.market_regime(bars, ma=ma)
    regime["symbol"] = filter_symbol
    verdict = "GO" if regime["go"] else "NO-GO"
    log(f"swing: market regime {filter_symbol} {verdict} :: {regime['reason']}")
    return regime


def scan_watchlist_for_setups(
    broker: AlpacaBroker,
    db: Session,
    *,
    lookback_days: int,
    extra_symbols: Optional[list[str]] = None,
    spy_symbol: str = "SPY",
    log: LogFn = _noop,
) -> tuple[dict[str, swing_analyzer.SetupPlan], dict[str, dict]]:
    """Apply the setup classifier to every watchlist symbol (+ any extras the
    tweet signals produced this run) and return:
        plans_by_symbol : {SYM: SetupPlan} for symbols where a setup fired
        snapshots       : {SYM: indicator snapshot} for every scanned symbol
    """
    watchlist = _watchlist_symbols(db)
    extras = [s.upper() for s in (extra_symbols or []) if s]
    symbols = sorted({*watchlist, *extras, spy_symbol.upper()})
    if not symbols:
        log("swing: no symbols to scan (empty watchlist)")
        return {}, {}

    log(f"swing: scanning {len(symbols)} symbols for setups ({lookback_days}d bars)")
    bars_map = broker.fetch_daily_bars(symbols, lookback_days=lookback_days)
    if not bars_map:
        log("swing: bar fetch returned nothing; skipping scan")
        return {}, {}

    spy_bars = bars_map.get(spy_symbol.upper()) or []
    spy_closes = T.closes(spy_bars) if spy_bars else None

    plans: dict[str, swing_analyzer.SetupPlan] = {}
    snaps: dict[str, dict] = {}
    for sym in symbols:
        if sym == spy_symbol.upper():
            continue
        bars = bars_map.get(sym) or []
        if len(bars) < 30:
            continue
        snap = T.snapshot(bars, spy_closes=spy_closes)
        snaps[sym] = snap
        plan = swing_analyzer.classify(sym, bars, snap)
        if plan:
            plans[sym] = plan

    if plans:
        log(
            "swing: setups found -> "
            + ", ".join(
                f"{p.symbol}({p.setup},R/R={p.rr:.2f})" for p in plans.values()
            )
        )
    else:
        log("swing: no setups fired across the watchlist this run")
    return plans, snaps


def build_swing_proposals(
    plans: dict[str, swing_analyzer.SetupPlan],
    *,
    signals: dict[str, dict[str, Any]],
    open_symbols: set[str],
    recently_bought: dict[str, Any],
    budget_remaining: float,
    weekly_remaining: float,
    total_capital_usd: float,
    risk_pct: float,
    min_rr: float,
    min_position_usd: float,
    max_position_usd: float,
    max_open_positions: int,
    regime_go: bool,
) -> list[dict[str, Any]]:
    """Turn SetupPlans into allocator-compatible proposal dicts.

    Honours the skill's execution flow:
      - Regime off -> every BUY becomes a 'watch' skipped proposal.
      - Open-position cap enforced (3-5 per skill; reuses MAX_OPEN_POSITIONS).
      - Already-held / recently-bought symbols skipped with clear reason.
      - R/R < min_rr -> skipped with reason.
      - Sizing via swing_analyzer.size_plan (1% risk, min/max slot bands).
      - Respects remaining daily + weekly budget.
    """
    proposals: list[dict[str, Any]] = []
    remaining_slots = max(0, max_open_positions - len(open_symbols))
    daily_budget = max(0.0, float(budget_remaining))
    week_budget = max(0.0, float(weekly_remaining))

    # Rank setups: higher R/R first, then prefer breakout > pullback > news > oversold
    order = {"breakout": 0, "trend_pullback": 1, "news_momentum": 2, "oversold_bounce": 3}
    ranked = sorted(
        plans.values(),
        key=lambda p: (-p.rr, order.get(p.setup, 9)),
    )

    for plan in ranked:
        sym = plan.symbol
        base = {
            "symbol": sym,
            "side": "buy",
            "qty": 0.0,
            "est_price": plan.entry,
            "notional": 0.0,
            "action": "proposed",
            "reason": "",
            "setup_type": plan.setup,
            "entry_price": plan.entry,
            "stop_price": plan.stop,
            "target_price": plan.target,
            "risk_reward": plan.rr,
        }

        if not regime_go:
            proposals.append({
                **base, "action": "skipped",
                "reason": (
                    f"market regime NO-GO; watching {sym} ({plan.setup}) "
                    f"for re-entry if SPY turns up"
                ),
            })
            continue

        if sym in open_symbols:
            proposals.append({
                **base, "action": "skipped",
                "reason": f"already holding {sym} (setup={plan.setup})",
            })
            continue

        if sym in recently_bought:
            when = recently_bought[sym].get("created_at")
            when_s = when.strftime("%Y-%m-%d %H:%M") if when else ""
            proposals.append({
                **base, "action": "skipped",
                "reason": f"bought recently{(' on ' + when_s) if when_s else ''}",
            })
            continue

        if remaining_slots <= 0:
            proposals.append({
                **base, "action": "skipped",
                "reason": f"max open positions reached ({max_open_positions})",
            })
            continue

        sizing = swing_analyzer.size_plan(
            plan,
            total_capital_usd=total_capital_usd,
            risk_pct=risk_pct,
            min_position_usd=min_position_usd,
            max_position_usd=max_position_usd,
            min_rr=min_rr,
        )
        if sizing["rejected"]:
            proposals.append({
                **base, "action": "skipped",
                "reason": f"swing skip: {sizing['reason']}",
            })
            continue

        slot = min(sizing["notional"], daily_budget, week_budget)
        if slot < min_position_usd:
            reason_bits = []
            if daily_budget < min_position_usd:
                reason_bits.append(f"daily ${daily_budget:.2f}<min ${min_position_usd:.0f}")
            if week_budget < min_position_usd:
                reason_bits.append(f"weekly ${week_budget:.2f}<min ${min_position_usd:.0f}")
            proposals.append({
                **base, "action": "skipped",
                "reason": "budget below min slot; " + "; ".join(reason_bits),
            })
            continue

        qty = round(slot / plan.entry, 4) if plan.entry > 0 else 0.0
        notional = round(qty * plan.entry, 2)
        if qty <= 0:
            proposals.append({
                **base, "action": "skipped",
                "reason": "qty rounded to 0",
            })
            continue

        # Merge tweet corroboration into the reason when we have it.
        tweet_bits = ""
        sig = signals.get(sym)
        if sig and sig.get("score") is not None:
            tweet_bits = (
                f" | tweets: score={sig['score']:+.2f} conf={sig['confidence']:.2f} "
                f"mentions={sig['mentions']}"
            )

        proposals.append({
            **base,
            "qty": qty,
            "notional": notional,
            "action": "proposed",
            "reason": (
                f"{plan.setup}: entry ${plan.entry:.2f} stop ${plan.stop:.2f} "
                f"target ${plan.target:.2f} R/R {plan.rr:.2f} :: {plan.note}"
                + tweet_bits
            ),
        })
        daily_budget -= notional
        week_budget -= notional
        remaining_slots -= 1

    return proposals


def persist_position_plan(
    db: Session,
    plan: swing_analyzer.SetupPlan,
    *,
    run_id: int,
    mode: str,
) -> None:
    """Upsert (symbol-unique) the position plan for a BUY we just emitted.
    Runner calls this only when the proposal actually executes."""
    from ...models import AgentPositionPlan

    row = (
        db.query(AgentPositionPlan)
        .filter(AgentPositionPlan.symbol == plan.symbol)
        .first()
    )
    if row:
        row.run_id = run_id
        row.setup_type = plan.setup
        row.entry_price = plan.entry
        row.stop_price = plan.stop
        row.target_price = plan.target
        row.risk_reward = plan.rr
        row.status = "open"
        row.breakeven_moved = 0
        row.partial_taken = 0
        row.opened_at = datetime.utcnow()
        row.notes = plan.note
    else:
        db.add(AgentPositionPlan(
            symbol=plan.symbol, run_id=run_id,
            setup_type=plan.setup, entry_price=plan.entry,
            stop_price=plan.stop, target_price=plan.target,
            risk_reward=plan.rr, status="open",
            notes=plan.note,
        ))
    db.commit()


def trade_management_pass(
    broker: AlpacaBroker,
    db: Session,
    *,
    time_stop_days: int,
    move_stop_be_pct: float,
    partial_pct: float,
    log: LogFn = _noop,
) -> list[dict[str, Any]]:
    """Apply SKILL trade-management rules to every open position that has a
    stored plan. Emits EXIT proposals when:
      - current price <= stop
      - elapsed trading days since open >= time_stop_days with no progress
    Also mutates plan rows:
      - breakeven_moved=1 once +move_stop_be_pct reached (and raises stop)
      - partial_taken=1 once +partial_pct reached (advisor surfaces; no sell)
    """
    from ...models import AgentPositionPlan

    proposals: list[dict[str, Any]] = []
    if not broker.configured:
        return proposals

    try:
        positions = {p["symbol"].upper(): p for p in broker.positions()}
    except Exception as e:
        log(f"swing: trade-mgmt could not list positions ({e})")
        return proposals

    plans = (
        db.query(AgentPositionPlan)
        .filter(AgentPositionPlan.status == "open")
        .all()
    )
    now = datetime.utcnow()
    dirty = False
    for row in plans:
        pos = positions.get(row.symbol)
        if not pos:
            # Position was closed externally (e.g. manual sell); mark the
            # plan closed so we don't keep alerting on it.
            row.status = "closed"
            row.notes = (row.notes or "") + f" | auto-closed plan ({now.date()})"
            dirty = True
            continue
        current = float(pos.get("current_price") or 0.0)
        qty = float(pos.get("qty") or 0.0)
        if current <= 0 or qty <= 0:
            continue

        # Stop hit.
        if current <= row.stop_price:
            proposals.append({
                "symbol": row.symbol, "side": "sell", "qty": qty,
                "est_price": current, "notional": round(qty * current, 2),
                "action": "proposed",
                "reason": (
                    f"STOP HIT ({row.setup_type}): last ${current:.2f} "
                    f"<= stop ${row.stop_price:.2f}; exit now"
                ),
                "setup_type": row.setup_type,
                "entry_price": row.entry_price,
                "stop_price": row.stop_price,
                "target_price": row.target_price,
                "risk_reward": row.risk_reward,
            })
            row.status = "closed"
            row.notes = (row.notes or "") + f" | stop hit @ {current:.2f}"
            dirty = True
            continue

        # Time stop (calendar days since opened_at; good-enough proxy for
        # trading days in a 1-2 week horizon).
        elapsed = (now - row.opened_at).days
        plpc = (current - row.entry_price) / row.entry_price if row.entry_price else 0.0
        if elapsed >= time_stop_days and plpc < 0.02:
            proposals.append({
                "symbol": row.symbol, "side": "sell", "qty": qty,
                "est_price": current, "notional": round(qty * current, 2),
                "action": "proposed",
                "reason": (
                    f"TIME STOP ({row.setup_type}): {elapsed}d in trade with "
                    f"{plpc*100:+.2f}% P/L; exit and redeploy"
                ),
                "setup_type": row.setup_type,
                "entry_price": row.entry_price,
                "stop_price": row.stop_price,
                "target_price": row.target_price,
                "risk_reward": row.risk_reward,
            })
            row.status = "closed"
            row.notes = (row.notes or "") + f" | time stop {elapsed}d"
            dirty = True
            continue

        # Move stop to breakeven at +8% (or configured %).
        if plpc >= move_stop_be_pct and not row.breakeven_moved:
            old_stop = row.stop_price
            row.stop_price = max(row.stop_price, row.entry_price)
            row.breakeven_moved = 1
            row.notes = (row.notes or "") + (
                f" | moved stop ${old_stop:.2f}->${row.stop_price:.2f} at +{plpc*100:.1f}%"
            )
            dirty = True
            log(
                f"swing: {row.symbol} moved stop to breakeven "
                f"(${old_stop:.2f}->${row.stop_price:.2f})"
            )

        # Flag partial at +5%.
        if plpc >= partial_pct and not row.partial_taken:
            row.partial_taken = 1
            row.notes = (row.notes or "") + f" | partial-profit flag at +{plpc*100:.1f}%"
            dirty = True

    if dirty:
        db.commit()
    if proposals:
        log(
            "swing: trade-mgmt exits -> "
            + ", ".join(f"{p['symbol']} ({p['reason'].split(':')[0]})" for p in proposals)
        )
    return proposals


def brief_for_prompt(
    regime: dict[str, Any],
    plans: dict[str, swing_analyzer.SetupPlan],
    snaps: dict[str, dict],
    *,
    max_items: int = 8,
) -> str:
    """Compact block appended to the advisor LLM prompt."""
    lines: list[str] = []
    sym = regime.get("symbol", "SPY")
    verdict = "GO" if regime.get("go") else "NO-GO"
    lines.append(f"Market Regime: {sym} {verdict} — {regime.get('reason','')}")
    if plans:
        lines.append("Swing setups (this run):")
        for p in list(plans.values())[:max_items]:
            lines.append("  - " + swing_analyzer.brief_line(p))
    else:
        lines.append("Swing setups: (none fired across watchlist)")
    if snaps:
        lines.append("Watchlist technical scan:")
        for sym2, snap in list(snaps.items())[:max_items]:
            rsi_v = snap.get("rsi14")
            rsi_s = f"RSI={rsi_v:.1f}" if rsi_v is not None else "RSI=?"
            sma20 = snap.get("sma20")
            sma50 = snap.get("sma50")
            last = snap.get("last")
            trend = "?"
            if last and sma20 and sma50:
                trend = "up" if (last > sma20 > sma50) else "down" if (last < sma20 < sma50) else "mixed"
            lines.append(f"  - {sym2}: trend={trend} {rsi_s}")
    return "\n".join(lines)
