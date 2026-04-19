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
from ..services.agent.runner import run_once
from ..services.settings_store import (
    EDITABLE_KEYS,
    get_runtime_settings,
    public_view,
    update_settings,
)

router = APIRouter(prefix="/agent", tags=["agent"])


def _scheduler():
    from .. import main as _m
    return getattr(_m, "agent_scheduler", None)


@router.get("/status", response_model=AgentStatusOut)
def status(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    last = db.query(AgentRun).order_by(AgentRun.started_at.desc()).first()
    sched = _scheduler()
    next_run = sched.next_run_at() if sched else None
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
    )


@router.get("/settings")
def get_settings(_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the current runtime settings (env defaults + DB overrides).
    OPENAI_API_KEY is masked - the UI sees only a preview + a 'set' flag."""
    return public_view(get_runtime_settings(db))


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
    return db.query(AgentRun).filter(AgentRun.id == run_id).first()


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
