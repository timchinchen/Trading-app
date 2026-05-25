from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_broker
from ..models import AgentRun, AgentSignal, AgentTrade, AgentTweetAnalysis, TwitterUserCache
from ..schemas import (
    AgentAccountCacheOut,
    AgentRunOut,
    AgentSignalOut,
    AgentStatusOut,
    AgentTradeOut,
    AgentTweetAnalysisOut,
)
from ..security import get_current_user
from ..services.agent.auto_sell import preview as auto_sell_preview, run_auto_sell
from ..services.agent import llm as agent_llm
from ..services.agent.runner import run_once
from ..services.prompt_feedback import (
    compute_weekly_stats,
    format_stats_brief,
    load_latest_weekly_lessons,
)
from ..services.trading_context import build_trading_context_text
from ..services.digest_store import append_entry as digest_append
from ..services.settings_store import (
    EDITABLE_KEYS,
    SECRET_KEYS,
    editable_settings_snapshot,
    get_runtime_settings,
    public_view,
    update_settings,
)

router = APIRouter(prefix="/agent", tags=["agent"])


def _scheduler():
    from .. import main as _m
    return getattr(_m, "agent_scheduler", None)


def _diagnostic_assumptions(rs) -> list[dict[str, Any]]:
    """Human-readable snapshot of the assumptions the trading logic uses."""
    return [
        {
            "name": "Trading horizon",
            "value": "1-2 week swings (3-10 trading days)",
            "source": "agent llm role preamble",
        },
        {
            "name": "Approved buy setups",
            "value": "trend_pullback, breakout, oversold_bounce, news_momentum",
            "source": "swing_analyzer.classify priority rules",
        },
        {
            "name": "Market regime buy gate",
            "value": (
                f"{rs.swing_market_filter_symbol} above SMA{rs.swing_market_filter_ma}, "
                "MA rising, and above SMA20 for GO"
            ),
            "source": "swing_analyzer.market_regime + swing_runner.build_swing_proposals",
        },
        {
            "name": "Risk per trade",
            "value": f"{rs.swing_risk_per_trade_pct * 100:.2f}% of capital",
            "source": "swing_analyzer.size_plan",
        },
        {
            "name": "Minimum reward/risk",
            "value": f"R/R >= {rs.swing_min_rr:.2f}",
            "source": "swing_analyzer.size_plan",
        },
        {
            "name": "No-progress time stop",
            "value": f"{rs.swing_time_stop_days} trading-day proxy",
            "source": "swing_runner.trade_management_pass",
        },
        {
            "name": "Hard max hold",
            "value": f"{rs.agent_max_hold_days} calendar days",
            "source": "runner._adaptive_exit_proposals",
        },
        {
            "name": "Partial take profit",
            "value": (
                f"{rs.agent_partial_take_fraction * 100:.0f}% size at "
                f"+{rs.agent_partial_take_pct * 100:.1f}%"
            ),
            "source": "runner._adaptive_exit_proposals",
        },
        {
            "name": "Trailing momentum exit",
            "value": (
                f"arm at +{rs.agent_trail_arm_pct * 100:.1f}% then exit on "
                f"{rs.agent_trail_retrace_pct * 100:.0f}% retrace from peak"
            ),
            "source": "runner._adaptive_exit_proposals",
        },
        {
            "name": "Static TP/SL fallback",
            "value": (
                f"take-profit +{rs.agent_take_profit_pct * 100:.1f}% | "
                f"stop-loss -{rs.agent_stop_loss_pct * 100:.1f}%"
            ),
            "source": "runner._take_profit_proposals",
        },
        {
            "name": "Position and allocation caps",
            "value": (
                f"max open {rs.agent_max_open_positions}, slot "
                f"${rs.agent_min_position_usd:.0f}-${rs.agent_max_position_usd:.0f}"
            ),
            "source": "allocator.propose_trades + swing_runner.build_swing_proposals",
        },
        {
            "name": "Risk-off behavior",
            "value": (
                f"risk multipliers on/neutral/off = "
                f"{rs.agent_regime_risk_on_mult:.2f}/"
                f"{rs.agent_regime_neutral_mult:.2f}/"
                f"{rs.agent_regime_risk_off_mult:.2f}; "
                f"block_new_buys={rs.agent_risk_off_block_new_buys}"
            ),
            "source": "runner._classify_regime + allocator.propose_trades",
        },
        {
            "name": "Legacy signal thresholds (fallback allocator)",
            "value": (
                f"min_score={rs.agent_min_score:.2f}, "
                f"min_confidence={rs.agent_min_confidence:.2f}, "
                f"top_n={rs.agent_top_n_candidates}"
            ),
            "source": "allocator.propose_trades",
        },
    ]


@router.get("/status", response_model=AgentStatusOut)
def status(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    last = db.query(AgentRun).order_by(AgentRun.started_at.desc()).first()
    sched = _scheduler()
    next_run = sched.next_run_at() if sched else None
    next_auto_sell = (
        sched.next_auto_sell_at() if sched and hasattr(sched, "next_auto_sell_at") else None
    )
    rs = get_runtime_settings(db)
    return AgentStatusOut(
        enabled=rs.agent_enabled,
        mode=settings.APP_MODE,
        auto_execute_live=rs.agent_auto_execute_live,
        budget_usd=rs.agent_budget_usd,
        weekly_budget_usd=rs.agent_weekly_budget_usd,
        min_position_usd=rs.agent_min_position_usd,
        max_position_usd=rs.agent_max_position_usd,
        daily_loss_cap_usd=rs.agent_daily_loss_cap_usd,
        max_open_positions=rs.agent_max_open_positions,
        cron_minutes=rs.agent_cron_minutes,
        accounts=rs.twitter_accounts_list,
        ollama_host=rs.llm_host,
        ollama_model=rs.llm_model,
        last_run_id=last.id if last else None,
        last_run_started_at=last.started_at if last else None,
        last_run_status=last.status if last else None,
        next_run_at=next_run,
        auto_sell_enabled=rs.auto_sell_enabled,
        auto_sell_max_hold_days=rs.auto_sell_max_hold_days,
        next_auto_sell_at=next_auto_sell,
    )


@router.get("/settings")
def get_settings(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the current runtime settings (env defaults + DB overrides).
    OPENAI_API_KEY is masked - the UI sees only a preview + a 'set' flag."""
    return public_view(get_runtime_settings(db))


@router.get("/diagnostics")
def diagnostics(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    rs = get_runtime_settings(db)
    effective = agent_llm.build_role_preamble(
        db,
        enabled=rs.agent_dynamic_preamble_enabled,
        max_supplement_chars=rs.agent_weekly_lesson_max_chars,
    )
    weekly = load_latest_weekly_lessons(db)
    return {
        "prompts": {
            "role_preamble_base": agent_llm.ROLE_PREAMBLE_BASE,
            "role_preamble": effective,
            "weekly_lessons": (weekly.text if weekly else None),
            "weekly_lessons_week_key": (weekly.week_key if weekly else None),
            "tweet_system_prompt": agent_llm.build_tweet_system_prompt(effective),
            "advisor_system_prompt": agent_llm.build_advisor_system_prompt(effective),
        },
        "weekly_stats": format_stats_brief(compute_weekly_stats(db, settings.APP_MODE)),
        "assumptions": _diagnostic_assumptions(rs),
    }


@router.get("/context")
def agent_context(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    broker=Depends(get_broker),
    digests_limit: int = 5,
    runs_limit: int = 20,
):
    """Trading app context block (same sections as Chat 'include context')."""
    text = build_trading_context_text(
        db,
        broker,
        digests_limit=max(1, min(30, digests_limit)),
        runs_limit=max(1, min(50, runs_limit)),
    )
    return {"text": text}


@router.put("/settings")
def put_settings(
    payload: dict = Body(...),
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist runtime overrides for any of the editable keys. To clear an
    override and fall back to the .env default, send the key with an empty
    string value."""
    unknown = [k for k in payload.keys() if k.upper() not in EDITABLE_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown / non-editable keys: {unknown}. Allowed: {sorted(EDITABLE_KEYS)}",
        )
    rs = update_settings(db, payload)
    # If the agent cron was changed, ask the scheduler to re-arm itself
    sched = _scheduler()
    if sched and hasattr(sched, "reschedule"):
        try:
            sched.reschedule(rs.agent_cron_minutes, enabled=rs.agent_enabled)
        except Exception:
            pass
    # Digest: record what changed (mask secret values so we don't write keys
    # into the memory log).
    try:
        changed = sorted(k.upper() for k in payload.keys())
        safe_payload = {
            k.upper(): ("***" if k.upper() in SECRET_KEYS else v)
            for k, v in payload.items()
        }
        digest_append(
            kind="settings_change",
            summary=f"settings updated: {', '.join(changed)[:240]}",
            data=safe_payload,
            db=db,
        )
    except Exception:
        pass
    return public_view(rs)


@router.get("/settings/export")
def export_settings(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Export all editable runtime settings, including secret values.

    Intended for one-shot migration between self-hosted instances."""
    rs = get_runtime_settings(db)
    return {
        "schema": "trading-app-settings-v1",
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "app_mode": settings.APP_MODE,
        "overridden_keys": sorted(rs.overridden),
        "settings": editable_settings_snapshot(rs),
    }


@router.post("/settings/import")
def import_settings(
    payload: dict = Body(...),
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import an exported runtime-settings JSON payload.

    Accepts either:
      1) {"settings": {...}} from /agent/settings/export
      2) a flat {"KEY": value, ...} object.
    """
    raw = payload.get("settings") if isinstance(payload, dict) and "settings" in payload else payload
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Invalid import payload: expected JSON object")

    normalized = {str(k).upper(): v for k, v in raw.items()}
    unknown = [k for k in normalized.keys() if k not in EDITABLE_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown / non-editable keys in import: {unknown}. Allowed: {sorted(EDITABLE_KEYS)}",
        )

    rs = update_settings(db, normalized)
    sched = _scheduler()
    if sched and hasattr(sched, "reschedule"):
        try:
            sched.reschedule(rs.agent_cron_minutes, enabled=rs.agent_enabled)
        except Exception:
            pass

    try:
        changed = sorted(normalized.keys())
        safe_payload = {
            k: ("***" if k in SECRET_KEYS else v)
            for k, v in normalized.items()
        }
        digest_append(
            kind="settings_change",
            summary=f"settings imported: {', '.join(changed)[:240]}",
            data=safe_payload,
            db=db,
        )
    except Exception:
        pass
    return public_view(rs)


@router.get("/runs", response_model=list[AgentRunOut])
def list_runs(_user=Depends(get_current_user), db: Session = Depends(get_db), limit: int = 20):
    return (
        db.query(AgentRun)
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/runs/{run_id}/signals", response_model=list[AgentSignalOut])
def run_signals(run_id: int, _user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(AgentSignal).filter(AgentSignal.run_id == run_id).all()


@router.get("/runs/{run_id}/trades", response_model=list[AgentTradeOut])
def run_trades(run_id: int, _user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(AgentTrade).filter(AgentTrade.run_id == run_id).all()


@router.get("/runs/{run_id}/tweets", response_model=list[AgentTweetAnalysisOut])
def run_tweets(run_id: int, _user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(AgentTweetAnalysis)
        .filter(AgentTweetAnalysis.run_id == run_id)
        .order_by(AgentTweetAnalysis.created_at.asc())
        .all()
    )
    return [
        AgentTweetAnalysisOut(
            id=r.id,
            run_id=r.run_id,
            handle=r.handle,
            tweet_id=r.tweet_id,
            tweet_url=r.tweet_url,
            tweet_text=r.tweet_text,
            tweet_created_at=r.tweet_created_at,
            analysis_json=r.analysis_json,
            tickers_count=r.tickers_count or 0,
            is_noise=bool(r.is_noise),
            error=r.error,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/run-now", response_model=AgentRunOut)
async def run_now(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    broker=Depends(get_broker),
):
    run_id = await run_once(broker)
    if run_id == -1:
        # Single-flight guard: another run (cron or prior manual) is still
        # going. Return the latest AgentRun so the UI can show its progress
        # instead of spawning a duplicate.
        raise HTTPException(
            status_code=409,
            detail="An agent run is already in progress; try again when it finishes.",
        )
    return db.query(AgentRun).filter(AgentRun.id == run_id).first()


@router.get("/auto-sell/preview")
def auto_sell_preview_endpoint(
    _user=Depends(get_current_user),
    broker=Depends(get_broker),
):
    """Dry-run: list every open position with its held-days and flag the
    ones that would be auto-sold on the next daily scan. Safe to call at
    any time; makes no changes."""
    return auto_sell_preview(broker)


@router.post("/auto-sell/run-now")
async def auto_sell_run_now(
    force: bool = False,
    _user=Depends(get_current_user),
    broker=Depends(get_broker),
):
    """Trigger the auto-sell scan immediately. Honours AUTO_SELL_ENABLED
    unless ?force=true is passed, in which case it runs regardless of the
    toggle (useful for one-off cleanups)."""
    return await run_auto_sell(broker, forced=bool(force))


@router.get("/accounts-cache", response_model=list[AgentAccountCacheOut])
def accounts_cache(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Show resolution status for every handle in TWITTER_ACCOUNTS, plus any
    cached handles no longer in the config list."""
    in_config = {h.lower() for h in get_runtime_settings(db).twitter_accounts_list}
    rows = db.query(TwitterUserCache).all()
    cached_by_handle = {r.handle: r for r in rows}
    out: list[AgentAccountCacheOut] = []
    for h in sorted(in_config):
        r = cached_by_handle.get(h)
        if r:
            out.append(AgentAccountCacheOut(
                handle=h,
                user_id=r.user_id or None,
                resolved_at=r.resolved_at,
                not_found=bool(r.not_found),
                in_config=True,
            ))
        else:
            out.append(AgentAccountCacheOut(handle=h, in_config=True))
    # Also surface any stale cached handles that are no longer in config.
    for h, r in cached_by_handle.items():
        if h not in in_config:
            out.append(AgentAccountCacheOut(
                handle=h,
                user_id=r.user_id or None,
                resolved_at=r.resolved_at,
                not_found=bool(r.not_found),
                in_config=False,
            ))
    return out
