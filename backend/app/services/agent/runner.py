"""One-shot agent execution: fetch -> analyze -> aggregate -> allocate -> execute."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...config import settings
from ...db import SessionLocal
from ...models import (
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
from ..settings_store import get_runtime_settings
from . import analyzer, allocator, llm, playwright_client, twitter_client
from .intel import collect_intel


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
    """Very rough daily P/L estimate from trade rows in today's date."""
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Trade)
        .filter(Trade.mode == mode, Trade.filled_at >= start)
        .all()
    )
    total = 0.0
    for t in rows:
        sign = 1 if t.side == "sell" else -1
        total += sign * t.qty * t.price
    return total


def _remaining_budget(db: Session, mode: str) -> float:
    """Budget remaining = BUDGET_USD minus gross notional of today's agent BUY trades."""
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
    return max(0.0, settings.AGENT_BUDGET_USD - used)


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
    daily_budget_remaining: float,
    weekly_remaining: float,
    open_positions: set[str],
    max_positions: int,
) -> str:
    parts: list[str] = []
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


def _take_profit_proposals(
    broker: AlpacaBroker,
    *,
    db: Session,
    mode: str,
    take_profit_pct: float,
    already_in_proposals: set[str],
) -> list[dict[str, Any]]:
    """Emit SELL-to-close proposals for any held position that is up at least
    `take_profit_pct` vs entry. Uses Alpaca's avg_entry_price as the canonical
    entry, with a fallback to the latest executed AgentTrade.est_price."""
    if take_profit_pct <= 0 or not broker.configured:
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

        entry = p.get("avg_entry_price")
        current = p.get("current_price")
        plpc = p.get("unrealized_plpc")

        # Fallback entry price: most recent agent BUY for this symbol.
        if not entry:
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
            entry = (row.est_price if row else None)

        # Compute gain fraction.
        if plpc is None and entry and current:
            try:
                plpc = (float(current) - float(entry)) / float(entry)
            except Exception:
                plpc = None
        if plpc is None:
            continue

        if plpc >= take_profit_pct:
            notional = round(qty * float(current or entry or 0.0), 2)
            proposals.append({
                "symbol": sym,
                "side": "sell",
                "qty": qty,
                "est_price": float(current) if current else None,
                "notional": notional,
                "action": "proposed",
                "reason": (
                    f"take-profit hit: {plpc * 100:+.2f}% "
                    f"(entry=${float(entry):.2f} -> last=${float(current or 0):.2f}) "
                    f"closing {qty} shares"
                ),
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
    """Run the agent pipeline once. Returns the AgentRun id."""
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
        log.add(f"today realized P/L: ${pl:.2f} (cap -${rs.agent_daily_loss_cap_usd})")
        if pl <= -abs(rs.agent_daily_loss_cap_usd):
            run.status = "skipped"
            run.summary = f"daily loss cap hit (P/L={pl:.2f})"
            run.finished_at = datetime.utcnow()
            _save_logs()
            return run_id

        # 1. Fetch tweets via headless Chromium + twscrape cookies.
        # Playwright is our primary source since Dec-2025 twscrape 0.17.0 hit
        # parsing failures that self-lock accounts for 15 minutes. twscrape
        # remains as a fallback.
        log.add(f"fetching tweets via playwright (lookback={settings.AGENT_LOOKBACK_HOURS}h, "
                f"max/account={settings.AGENT_MAX_TWEETS_PER_ACCOUNT}, "
                f"per-account timeout={settings.AGENT_PER_ACCOUNT_TIMEOUT_S}s) ...")
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
                lookback_hours=settings.AGENT_LOOKBACK_HOURS,
                max_per_account=settings.AGENT_MAX_TWEETS_PER_ACCOUNT,
                db_path=settings.TWSCRAPE_DB,
                per_account_timeout_s=settings.AGENT_PER_ACCOUNT_TIMEOUT_S,
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
                    lookback_hours=settings.AGENT_LOOKBACK_HOURS,
                    max_per_account=settings.AGENT_MAX_TWEETS_PER_ACCOUNT,
                    db_path=settings.TWSCRAPE_DB,
                    per_account_timeout_s=settings.AGENT_PER_ACCOUNT_TIMEOUT_S,
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

        # 2. LLM analyze each tweet (limited concurrency)
        log.add(f"analysing tweets via {rs.llm_provider} ({rs.llm_model}) ...")
        sem = asyncio.Semaphore(3)
        analyses: list[dict[str, Any]] = []

        async def analyze(tw):
            async with sem:
                a = await llm.analyze_tweet(
                    tw["text"], tw["handle"], rs.llm_host, rs.llm_model,
                    provider=rs.llm_provider, api_key=rs.openai_api_key,
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

        # 3. Aggregate
        signals = analyzer.aggregate(analyses)

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
        open_positions = {p["symbol"] for p in broker.positions()} if broker.configured else set()
        daily_budget = _remaining_budget(db, settings.APP_MODE)
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

        proposals = allocator.propose_trades(
            signals=signals,
            open_symbols=open_positions,
            budget_remaining=daily_budget,
            weekly_remaining=weekly_remaining,
            min_position_usd=rs.agent_min_position_usd,
            max_position_usd=rs.agent_max_position_usd,
            max_open_positions=rs.agent_max_open_positions,
            get_price=_price,
            recently_bought=recently_bought,
        )

        # Take-profit: after deciding on BUYs, sweep held positions for anything
        # that has gained >= TAKE_PROFIT_PCT since entry and emit a SELL proposal.
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
            already_in_proposals=tp_in_hand,
        )
        if tp_proposals:
            log.add(
                f"take-profit ({rs.agent_take_profit_pct * 100:.1f}%): "
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
        interested = sorted({
            (p["symbol"] or "").upper()
            for p in proposals
            if p.get("symbol") and p.get("side") == "buy" and p.get("action") in ("executed", "proposed")
        })
        # Also include anything we're now holding and anything flagged for sale
        # (user should see those live).
        for p in proposals:
            if p.get("side") == "sell" and p.get("symbol"):
                interested.append(p["symbol"].upper())
        interested = sorted(set(interested))
        if interested:
            added = _ensure_watchlisted(db, interested)
            if added:
                log.add(f"watchlist: added {len(added)} new symbols -> {', '.join(added)}")
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
        advisor_context = _build_advisor_context(
            signals=signals,
            proposals=proposals,
            portfolio_brief=portfolio_text,
            intel_brief=intel_brief_text,
            daily_budget_remaining=daily_budget,
            weekly_remaining=weekly_remaining,
            open_positions=open_positions,
            max_positions=rs.agent_max_open_positions,
        )
        log.add(f"advisor: generating portfolio recommendation via {rs.llm_provider} ({rs.llm_model}) ...")
        _save_logs()
        advice = await llm.advise_portfolio(
            advisor_context, rs.llm_host, rs.llm_model,
            provider=rs.llm_provider, api_key=rs.openai_api_key,
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
        _save_logs()
        return run_id

    except Exception as e:
        log.add(f"FATAL {e}")
        run.status = "error"
        run.summary = f"unexpected error: {e}"
        run.finished_at = datetime.utcnow()
        _save_logs()
        return run_id
    finally:
        db.close()
