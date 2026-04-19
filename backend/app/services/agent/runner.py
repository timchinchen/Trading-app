"""One-shot agent execution: fetch -> analyze -> aggregate -> allocate -> execute."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...config import settings
from ...db import SessionLocal
from ...models import AgentRun, AgentSignal, AgentTrade, AgentTweetAnalysis, Order, Trade
from ..broker import AlpacaBroker
from . import analyzer, allocator, llm, playwright_client, twitter_client


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


async def run_once(broker: AlpacaBroker) -> int:
    """Run the agent pipeline once. Returns the AgentRun id."""
    db = SessionLocal()
    run = AgentRun(mode=settings.APP_MODE, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    log = RunLog()
    log.add(f"run #{run_id} starting | mode={settings.APP_MODE} | "
            f"budget=${settings.AGENT_BUDGET_USD} max/pos=${settings.AGENT_MAX_POSITION_USD}")

    def _save_logs():
        run.logs = log.render()[:60000]
        db.commit()

    try:
        handles = settings.twitter_accounts_list
        log.add(f"configured handles: {len(handles)} -> {', '.join(handles) or '(none)'}")
        if not handles:
            run.status = "skipped"
            run.summary = "no twitter accounts configured"
            run.finished_at = datetime.utcnow()
            _save_logs()
            return run_id

        # Daily-loss cap check
        pl = _today_realized_pl(db, settings.APP_MODE)
        log.add(f"today realized P/L: ${pl:.2f} (cap -${settings.AGENT_DAILY_LOSS_CAP_USD})")
        if pl <= -abs(settings.AGENT_DAILY_LOSS_CAP_USD):
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
        log.add(f"analysing tweets via ollama ({settings.OLLAMA_MODEL}) ...")
        sem = asyncio.Semaphore(3)
        analyses: list[dict[str, Any]] = []

        async def analyze(tw):
            async with sem:
                a = await llm.analyze_tweet(
                    tw["text"], tw["handle"], settings.OLLAMA_HOST, settings.OLLAMA_MODEL
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
        budget = _remaining_budget(db, settings.APP_MODE)
        log.add(f"open positions: {sorted(open_positions)} | remaining budget today: ${budget:.2f}")

        def _price(sym: str) -> float | None:
            q = broker.latest_quote(sym)
            return q.get("ask") or q.get("last")

        proposals = allocator.propose_trades(
            signals=signals,
            open_symbols=open_positions,
            budget_remaining=budget,
            max_position_usd=settings.AGENT_MAX_POSITION_USD,
            get_price=_price,
        )
        for p in proposals:
            log.add(f"  candidate {p['symbol']} {p['side']} qty={p['qty']} "
                    f"notional=${p['notional']} -> {p['action']} ({p.get('reason','')})")

        # 5. Decide auto-execute
        auto_execute = (
            settings.APP_MODE == "paper"
            or (settings.APP_MODE == "live" and settings.AGENT_AUTO_EXECUTE_LIVE)
        )
        log.add(f"auto_execute={auto_execute} (app_mode={settings.APP_MODE}, "
                f"auto_exec_live={settings.AGENT_AUTO_EXECUTE_LIVE})")

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

        # 6. Summary via LLM (optional / best-effort)
        summary_blob_lines = []
        for sym, s in signals.items():
            summary_blob_lines.append(
                f"{sym}: score={s['score']} conf={s['confidence']} "
                f"mentions={s['mentions']} :: {s['rationale']}"
            )
        blob = "\n".join(summary_blob_lines) or "no tradable signals"
        summary = await llm.summarize_run(blob, settings.OLLAMA_HOST, settings.OLLAMA_MODEL)
        run.summary = summary[:4000]
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
