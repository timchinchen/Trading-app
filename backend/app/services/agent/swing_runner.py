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


def _bar_age_days(bar: dict | None) -> Optional[float]:
    """Calendar-day age of a bar's timestamp vs now (UTC). None if unknown."""
    if not bar:
        return None
    raw = bar.get("t")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.utcnow()
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def _intraday_confirmation(
    broker: AlpacaBroker,
    *,
    symbol: str,
    lookback_minutes: int,
    fast: int = 20,
    slow: int = 50,
    stale_minutes: int = 30,
) -> dict[str, Any]:
    """Best-effort intraday read of `symbol`. Never raises; returns a status
    dict. ``available`` is False (and ``weak`` None) on any failure so callers
    treat it as "no confirmation" rather than a block."""
    status: dict[str, Any] = {
        "enabled": True, "available": False, "bar_count": 0, "last_ts": None,
        "volume_ok": False, "ma20": None, "ma50": None, "cross": None,
        "weak": None, "issues": [],
    }
    try:
        bars = broker.fetch_intraday_bars(symbol, timeframe="1Min", lookback_minutes=lookback_minutes)
    except Exception as e:
        status["issues"].append(f"fetch error: {e}")
        return status
    status["bar_count"] = len(bars)
    if not bars:
        status["issues"].append("no intraday bars")
        return status
    status["last_ts"] = bars[-1].get("t")
    # Freshness
    age = _bar_age_days(bars[-1])
    if age is not None and age * 24 * 60 > stale_minutes:
        status["issues"].append(f"stale intraday ({age * 24 * 60:.0f}m old)")
    # Session volume present
    recent_vol = sum((b.get("v") or 0) for b in bars[-min(len(bars), fast):])
    status["volume_ok"] = recent_vol > 0
    if not status["volume_ok"]:
        status["issues"].append("no intraday volume")
    cs = T.closes(bars)
    ma_fast = T.sma(cs, fast)
    ma_slow = T.sma(cs, slow)
    status["ma20"] = ma_fast
    status["ma50"] = ma_slow
    if ma_fast is not None and ma_slow is not None:
        status["cross"] = "bullish" if ma_fast > ma_slow else "bearish" if ma_fast < ma_slow else "flat"
    last = cs[-1] if cs else None
    # "Weak" intraday = price below the fast MA, or fast MA below slow MA.
    if last is not None and ma_fast is not None:
        weak = last < ma_fast
        if ma_slow is not None and ma_fast < ma_slow:
            weak = True
        status["weak"] = bool(weak)
    # Available only when we have enough bars + fresh + volume to trust it.
    status["available"] = bool(
        len(bars) >= slow + 1
        and status["volume_ok"]
        and not any("stale" in i for i in status["issues"])
    )
    return status


def evaluate_market_regime(
    broker: AlpacaBroker,
    *,
    filter_symbol: str,
    ma: int,
    lookback_days: int,
    stale_bars_days: int = 4,
    use_intraday: bool = False,
    intraday_lookback_minutes: int = 390,
    log: LogFn = _noop,
) -> dict[str, Any]:
    """Classify the broader-market regime (default SPY) and flag data outages.

    Returns the swing_analyzer.market_regime dict plus ``symbol`` and a
    staleness-adjusted ``data_complete``. ``state`` is one of go/caution/no_go;
    ``data_complete`` is False when bars are missing, volume is absent, or the
    most recent bar is older than ``stale_bars_days`` calendar days (a stalled
    feed). The runner uses these to gate new buys.
    """
    bars_map = broker.fetch_daily_bars([filter_symbol], lookback_days=lookback_days)
    bars = bars_map.get(filter_symbol.upper()) or []
    if not bars:
        log(
            f"swing: market-filter bars unavailable for {filter_symbol}; "
            "regime=CAUTION (data degraded — mitigating, not stopping)"
        )
        return {
            "symbol": filter_symbol,
            "go": False,
            "state": "caution",
            "data_complete": False,
            "data_issues": ["bars unavailable"],
            "reason": (
                "data incomplete (bars unavailable); "
                "regime unknown — trading with caution"
            ),
            "ma_cross": None,
            "ma_cross_event": None,
        }
    regime = swing_analyzer.market_regime(bars, ma=ma)
    regime["symbol"] = filter_symbol

    # Staleness: a stalled feed serves old bars with no fresh prints.
    age = _bar_age_days(bars[-1])
    if age is not None and stale_bars_days > 0 and age > float(stale_bars_days):
        issues = list(regime.get("data_issues") or [])
        issues.append(f"latest SPY bar is {age:.1f}d old (>{stale_bars_days}d)")
        regime["data_issues"] = issues
        regime["data_complete"] = False
        regime["reason"] = f"data incomplete (stale {age:.1f}d); " + regime.get("reason", "")

    # ── Optional intraday confirmation (never hard-blocks) ───────────────
    if use_intraday:
        intra = _intraday_confirmation(
            broker, symbol=filter_symbol, lookback_minutes=intraday_lookback_minutes,
        )
        regime["intraday"] = intra
        if intra.get("available"):
            xc = intra.get("cross")
            log(
                f"swing: intraday {filter_symbol} bars={intra['bar_count']} "
                f"last={intra['last_ts']} vol_ok={intra['volume_ok']} "
                f"MA20={intra['ma20']:.2f} MA50={intra['ma50']:.2f} cross={xc} "
                f"weak={intra['weak']}"
                if intra.get("ma20") is not None and intra.get("ma50") is not None
                else f"swing: intraday {filter_symbol} bars={intra['bar_count']} (partial)"
            )
            if intra.get("cross"):
                log(f"ALERT {filter_symbol} intraday 20/50 MA cross={intra['cross']}")
            # Downgrade a daily GO to CAUTION when intraday is clearly weak.
            if regime.get("state") == "go" and intra.get("weak"):
                regime["state"] = "caution"
                regime["go"] = False
                regime["reason"] = (
                    "intraday weakness downgraded GO->CAUTION; " + regime.get("reason", "")
                )
                log(f"swing: intraday weakness downgraded {filter_symbol} GO -> CAUTION")
            elif regime.get("state") == "go":
                regime["reason"] = regime.get("reason", "") + " (intraday confirms)"
        else:
            issues = ", ".join(intra.get("issues") or []) or "unavailable"
            log(
                f"swing: intraday confirmation unavailable ({issues}); "
                "using daily regime only"
            )

    state = str(regime.get("state", "no_go")).upper().replace("_", "-")
    data_tag = "DATA OK" if regime.get("data_complete") else "DATA INCOMPLETE"
    cross = regime.get("ma_cross")
    cross_event = regime.get("ma_cross_event")
    cross_bits = ""
    if cross:
        cross_bits = f" | 20/50DMA={cross}"
        if cross_event:
            cross_bits += f" ({cross_event.upper().replace('_', ' ')})"
    log(
        f"swing: market regime {filter_symbol} {state} [{data_tag}] "
        f":: {regime['reason']}{cross_bits}"
    )
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
    regime_tier: str = "go",
    caution_size_mult: float = 0.5,
    caution_min_rr: float = 0.0,
    caution_require_corroboration: bool = False,
) -> list[dict[str, Any]]:
    """Turn SetupPlans into allocator-compatible proposal dicts.

    Honours the skill's execution flow:
      - Regime off (regime_go=False) -> every BUY becomes a 'watch' skipped proposal.
      - CAUTION tier (regime_tier='caution') -> half-size (caution_size_mult),
        stricter R/R floor (max(min_rr, caution_min_rr)), and optionally require
        tweet/intel corroboration before entering.
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
    is_caution = str(regime_tier).lower() == "caution"
    eff_min_rr = max(float(min_rr), float(caution_min_rr)) if is_caution else float(min_rr)
    size_mult = float(caution_size_mult) if is_caution else 1.0

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
            info = recently_bought[sym]
            when = info.get("created_at")
            when_s = when.strftime("%Y-%m-%d %H:%M") if when else ""
            side_s = info.get("side", "traded")
            proposals.append({
                **base, "action": "skipped",
                "reason": (
                    f"{side_s} recently{(' on ' + when_s) if when_s else ''} "
                    "(re-entry cooldown)"
                ),
            })
            continue

        if remaining_slots <= 0:
            proposals.append({
                **base, "action": "skipped",
                "reason": f"max open positions reached ({max_open_positions})",
            })
            continue

        # CAUTION: optionally require tweet/intel corroboration before entering.
        if is_caution and caution_require_corroboration:
            sig = signals.get(sym) or {}
            corroborated = bool(
                (sig.get("score") or 0) > 0 or sig.get("corroborated_by")
            )
            if not corroborated:
                proposals.append({
                    **base, "action": "skipped",
                    "reason": (
                        f"CAUTION regime: {sym} ({plan.setup}) lacks tweet/intel "
                        "corroboration; waiting for confirmation"
                    ),
                })
                continue

        # CAUTION: trim slot to half size (or configured fraction) BEFORE the
        # min/max clamp inside size_plan, so a trimmed slot lands on the floor
        # instead of being clamped up and then halved below it.
        sizing = swing_analyzer.size_plan(
            plan,
            total_capital_usd=total_capital_usd,
            risk_pct=risk_pct,
            min_position_usd=min_position_usd,
            max_position_usd=max_position_usd,
            min_rr=eff_min_rr,
            size_mult=size_mult,
        )
        if sizing["rejected"]:
            proposals.append({
                **base, "action": "skipped",
                "reason": (
                    f"swing skip: {sizing['reason']}"
                    + (f" (CAUTION R/R floor {eff_min_rr:.2f})" if is_caution else "")
                ),
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

        caution_bits = (
            f" [CAUTION {int(size_mult * 100)}% size, R/R>={eff_min_rr:.1f}]"
            if is_caution else ""
        )
        proposals.append({
            **base,
            "qty": qty,
            "notional": notional,
            "action": "proposed",
            "reason": (
                f"{plan.setup}: entry ${plan.entry:.2f} stop ${plan.stop:.2f} "
                f"target ${plan.target:.2f} R/R {plan.rr:.2f} :: {plan.note}"
                + caution_bits
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
        row.created_run_id = run_id
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
            symbol=plan.symbol, run_id=run_id, created_run_id=run_id,
            setup_type=plan.setup, entry_price=plan.entry,
            stop_price=plan.stop, target_price=plan.target,
            risk_reward=plan.rr, status="open",
            notes=plan.note,
        ))
    db.commit()


def backfill_position_plans(
    broker: AlpacaBroker,
    db: Session,
    *,
    mode: str,
    default_stop_pct: float,
    default_target_pct: float,
    current_run_id: Optional[int] = None,
    log: LogFn = _noop,
) -> int:
    """Create an AgentPositionPlan for every open broker position that lacks
    one (manual buys, tweet-allocator buys, or positions opened before plans
    existed). Without this, those positions fall back to the weaker static
    TP/SL sweep instead of the adaptive exit + invalidation engine.

    Entry = broker avg_entry_price; stop/target = entry shifted by the
    configured default percentages; setup_type='backfilled'. Returns the
    number of plans created.

    Guards against synthesising a stop that is already below the market: for a
    position more than ``default_stop_pct`` underwater, an entry-based stop
    would sit above the current price and the very next trade-management pass
    would liquidate it on the run that created the plan. When that happens we
    anchor the stop below the *current* price instead. ``current_run_id`` is
    stamped onto each new plan so the same-run hard-stop guard can skip it until
    the next run.
    """
    from ...models import AgentPositionPlan

    if not broker.configured:
        return 0
    try:
        positions = broker.positions()
    except Exception as e:
        log(f"swing: plan-backfill could not list positions ({e})")
        return 0

    existing = {
        (p.symbol or "").upper()
        for p in db.query(AgentPositionPlan)
        .filter(AgentPositionPlan.status == "open")
        .all()
    }
    created = 0
    for pos in positions:
        sym = (pos.get("symbol") or "").upper()
        if not sym or sym in existing:
            continue
        qty = float(pos.get("qty") or 0.0)
        entry = float(pos.get("avg_entry_price") or 0.0)
        if qty <= 0 or entry <= 0:
            continue
        current = float(pos.get("current_price") or 0.0)
        stop = round(entry * (1 - max(0.0, default_stop_pct)), 2)
        target = round(entry * (1 + max(0.0, default_target_pct)), 2)
        note = f"backfilled plan from open position (entry ${entry:.2f})"
        # Don't write a stop that is already at/above the market — that would
        # trip STOP HIT on the next pass. Anchor below current price instead.
        if current > 0 and current <= stop:
            stop = round(current * (1 - max(0.0, default_stop_pct)), 2)
            note += f"; entry-based stop already breached, anchored to current ${current:.2f}"
            log(
                f"swing: backfill {sym} entry-based stop breached "
                f"(last ${current:.2f}); anchoring stop -> ${stop:.2f}"
            )
        risk = max(1e-9, entry - stop)
        rr = round((target - entry) / risk, 2)
        db.add(AgentPositionPlan(
            symbol=sym, run_id=None, created_run_id=current_run_id,
            setup_type="backfilled", entry_price=entry,
            stop_price=stop, target_price=target,
            risk_reward=rr, status="open",
            notes=note,
        ))
        created += 1
    if created:
        try:
            db.commit()
            log(f"swing: plan-backfill created {created} plan(s) for un-planned positions")
        except Exception as e:
            db.rollback()
            log(f"swing: plan-backfill commit failed ({e})")
            return 0
    return created


def invalidation_exit_proposals(
    broker: AlpacaBroker,
    db: Session,
    *,
    lookback_days: int,
    mode: str = "",
    sma_period: int = 20,
    consec_closes: int = 2,
    first_close_on_confirmed: bool = True,
    existing_sell_symbols: Optional[set] = None,
    min_hold_hours: int = 0,
    current_run_id: Optional[int] = None,
    log: LogFn = _noop,
) -> list[dict[str, Any]]:
    """Exit positions whose *thesis* has broken, not just on a fixed % stop.

    Soft invalidation (default): ``consec_closes`` consecutive daily closes
    below the ``sma_period`` SMA -> exit.

    Confirmed-weakness single-close invalidation (when
    ``first_close_on_confirmed``): one close below the SMA that is *also*
    decisively weak -> exit immediately. "Decisive" means either a failed
    breakout (price back below the plan entry for a breakout setup) or a
    down-day that closes below the prior bar's low (a clean break).

    Only positions with an open plan are evaluated; pair with
    backfill_position_plans to cover manual/tweet positions. Symbols already
    earmarked for sale this run are skipped.
    """
    from ...models import AgentPositionPlan
    from datetime import timedelta
    from .position_age import open_lot_opened_at

    existing_sell_symbols = {s.upper() for s in (existing_sell_symbols or set())}
    if not broker.configured:
        return []
    now = datetime.utcnow()
    try:
        positions = {(p.get("symbol") or "").upper(): p for p in broker.positions()}
    except Exception as e:
        log(f"swing: invalidation could not list positions ({e})")
        return []
    plans = {
        (p.symbol or "").upper(): p
        for p in db.query(AgentPositionPlan)
        .filter(AgentPositionPlan.status == "open")
        .all()
    }
    held = [s for s in plans.keys() if s in positions and s not in existing_sell_symbols]
    if not held:
        return []

    bars_map = broker.fetch_daily_bars(held, lookback_days=lookback_days)
    proposals: list[dict[str, Any]] = []
    for sym in held:
        bars = bars_map.get(sym) or []
        if len(bars) < sma_period + 1:
            continue
        cs = T.closes(bars)
        sma = T.sma(cs, sma_period)
        if sma is None or not cs:
            continue
        pos = positions[sym]
        plan = plans[sym]
        qty = float(pos.get("qty") or 0.0)
        current = float(pos.get("current_price") or cs[-1] or 0.0)
        if qty <= 0 or current <= 0:
            continue

        # Same-run guard: never invalidate a plan created this run.
        if (
            current_run_id is not None
            and getattr(plan, "created_run_id", None) == current_run_id
        ):
            continue

        # Minimum-hold guard: invalidation is not a hard stop, so it waits for
        # the position to breathe. A setup can't be "invalidated" 30 minutes
        # after entry by daily closes that happened before we bought.
        if min_hold_hours > 0 and mode:
            opened = open_lot_opened_at(db, sym, mode)
            if opened is not None and (now - opened) < timedelta(hours=min_hold_hours):
                continue

        below = [c < sma for c in cs[-consec_closes:]]
        soft = len(below) >= consec_closes and all(below)

        confirmed = False
        confirm_reason = ""
        if first_close_on_confirmed and cs[-1] < sma:
            # Failed breakout: a breakout setup that has fallen back below entry.
            if (plan.setup_type or "").lower() == "breakout" and current < float(plan.entry_price or 0):
                confirmed = True
                confirm_reason = f"failed breakout (last ${current:.2f} < entry ${plan.entry_price:.2f})"
            # Decisive break: today closed below the prior bar's low.
            elif len(bars) >= 2 and bars[-1].get("c") is not None and bars[-2].get("l") is not None \
                    and bars[-1]["c"] < bars[-2]["l"]:
                confirmed = True
                confirm_reason = f"decisive break below prior-day low ${bars[-2]['l']:.2f}"

        if not (soft or confirmed):
            continue

        if soft:
            reason = (
                f"thesis invalidated ({plan.setup_type}): {consec_closes} consecutive "
                f"closes below SMA{sma_period} ${sma:.2f}; exit {qty} shares"
            )
        else:
            reason = (
                f"thesis invalidated ({plan.setup_type}): close ${cs[-1]:.2f} < "
                f"SMA{sma_period} ${sma:.2f} + {confirm_reason}; exit {qty} shares"
            )
        proposals.append({
            "symbol": sym, "side": "sell", "qty": qty,
            "est_price": current, "notional": round(qty * current, 2),
            "action": "proposed", "reason": reason,
            "exit_type": "invalidation",
            "setup_type": plan.setup_type,
            "entry_price": plan.entry_price,
            "stop_price": plan.stop_price,
            "target_price": plan.target_price,
            "risk_reward": plan.risk_reward,
        })
        plan.status = "closed"
        plan.notes = (plan.notes or "") + f" | invalidated @ {current:.2f}"
        db.add(plan)

    if proposals:
        try:
            db.commit()
        except Exception:
            db.rollback()
        log("swing: invalidation exits -> " + ", ".join(p["symbol"] for p in proposals))
    return proposals


def trade_management_pass(
    broker: AlpacaBroker,
    db: Session,
    *,
    mode: str,
    time_stop_days: int,
    move_stop_be_pct: float,
    partial_pct: float,
    time_stop_min_progress_pct: float = 0.02,
    move_stop_be_target_frac: float = 0.5,
    min_hold_hours: int = 0,
    current_run_id: Optional[int] = None,
    log: LogFn = _noop,
) -> list[dict[str, Any]]:
    """Apply SKILL trade-management rules to every open position that has a
    stored plan. Emits EXIT proposals when:
      - current price <= stop
      - elapsed trading days since open >= time_stop_days with no progress
    Also mutates plan rows:
      - breakeven_moved=1 once price covers move_stop_be_target_frac of the
        entry→target distance (and raises stop to entry)
      - partial_taken=1 once +partial_pct reached (advisor surfaces; no sell)

    Guards:
      - Only a hard stop may fire within ``min_hold_hours`` of the lot opening
        (from the shared position-age walk); time-stop / breakeven / partial all
        wait for the position to breathe.
      - A plan created on the current run (``created_run_id == current_run_id``)
        is skipped entirely, so a freshly-synthesised stop can't liquidate the
        position on the very run that created it.
      - Position age comes from the shared open_lot_opened_at helper, not
        ``plan.opened_at`` (which backfill stamps with utcnow, reading age 0).
    """
    from ...models import AgentPositionPlan
    from datetime import timedelta
    from .position_age import open_lot_opened_at

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

        # Same-run guard: never exit on a plan created this run (e.g. a stop
        # synthesised by backfill moments ago).
        if (
            current_run_id is not None
            and getattr(row, "created_run_id", None) == current_run_id
        ):
            continue

        # Minimum-hold guard: within the window only a hard stop may fire.
        opened = open_lot_opened_at(db, row.symbol, mode)
        within_min_hold = (
            min_hold_hours > 0
            and opened is not None
            and (now - opened) < timedelta(hours=min_hold_hours)
        )

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

        # Everything below is a soft exit / adjustment: skip while inside the
        # minimum-hold window.
        if within_min_hold:
            continue

        # Time stop (calendar days since the current lot opened; from the shared
        # age walk, not plan.opened_at). If we have no local lineage, opened is
        # None and we do NOT time-stop rather than guess.
        plpc = (current - row.entry_price) / row.entry_price if row.entry_price else 0.0
        elapsed = (now - opened).days if opened is not None else None
        if elapsed is not None and elapsed >= time_stop_days and plpc < time_stop_min_progress_pct:
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

        # Move stop to breakeven once price has covered move_stop_be_target_frac
        # of the entry->target distance (default 50%). Scaling the trigger to
        # each setup's own target avoids the old absolute +8% bump firing two
        # points short of a +10% target and scratching winners on any retrace.
        # Falls back to the legacy absolute % if there's no usable target.
        entry_price = row.entry_price or 0.0
        target_price = row.target_price or 0.0
        if entry_price > 0 and target_price > entry_price:
            be_trigger_plpc = move_stop_be_target_frac * ((target_price / entry_price) - 1.0)
        else:
            be_trigger_plpc = move_stop_be_pct
        if plpc >= be_trigger_plpc and not row.breakeven_moved:
            old_stop = row.stop_price
            row.stop_price = max(row.stop_price, row.entry_price)
            row.breakeven_moved = 1
            row.notes = (row.notes or "") + (
                f" | moved stop ${old_stop:.2f}->${row.stop_price:.2f} at +{plpc*100:.1f}% "
                f"(be trigger +{be_trigger_plpc*100:.1f}%)"
            )
            dirty = True
            log(
                f"swing: {row.symbol} moved stop to breakeven "
                f"(${old_stop:.2f}->${row.stop_price:.2f}) at +{plpc*100:.1f}%"
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
