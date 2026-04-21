"""/digest endpoints - Trading Memory.

- GET /digest                  latest daily summary + recent raw entries (dashboard)
- GET /digest/entries          paginated raw entries (debug/history)
- GET /digest/daily            list of daily digests
- POST /digest/compress        force a compression now (manual trigger)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DailyDigest, DigestEntry
from ..schemas import (
    DailyDigestOut,
    DigestEntryOut,
    DigestSummaryOut,
)
from ..security import get_current_user
from ..services.digest_store import compress_daily

router = APIRouter(prefix="/digest", tags=["digest"])


def _scheduler():
    from .. import main as _m
    return getattr(_m, "agent_scheduler", None)


@router.get("", response_model=DigestSummaryOut)
def get_digest(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    history_limit: int = Query(5, ge=1, le=60),
    entries_limit: int = Query(25, ge=1, le=200),
):
    daily_rows = (
        db.query(DailyDigest)
        .order_by(DailyDigest.generated_at.desc())
        .limit(history_limit)
        .all()
    )
    entry_rows = (
        db.query(DigestEntry)
        .order_by(DigestEntry.created_at.desc())
        .limit(entries_limit)
        .all()
    )
    sched = _scheduler()
    next_at = sched.next_digest_at() if sched and hasattr(sched, "next_digest_at") else None
    return DigestSummaryOut(
        latest=DailyDigestOut.model_validate(daily_rows[0]) if daily_rows else None,
        history=[DailyDigestOut.model_validate(d) for d in daily_rows],
        recent_entries=[DigestEntryOut.model_validate(e) for e in entry_rows],
        next_compression_at=next_at,
    )


@router.get("/entries", response_model=list[DigestEntryOut])
def list_entries(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    kind: str | None = None,
    symbol: str | None = None,
):
    q = db.query(DigestEntry).order_by(DigestEntry.created_at.desc())
    if kind:
        q = q.filter(DigestEntry.kind == kind)
    if symbol:
        q = q.filter(DigestEntry.symbol == symbol.upper())
    rows = q.limit(limit).all()
    return [DigestEntryOut.model_validate(r) for r in rows]


@router.get("/daily", response_model=list[DailyDigestOut])
def list_daily(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(60, ge=1, le=365),
):
    rows = (
        db.query(DailyDigest)
        .order_by(DailyDigest.generated_at.desc())
        .limit(limit)
        .all()
    )
    return [DailyDigestOut.model_validate(r) for r in rows]


@router.post("/compress", response_model=DailyDigestOut | None)
async def compress_now(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    force: bool = True,
):
    """Force a daily-digest compression now (bypass the 09:30 schedule).
    Useful for smoke-testing or catching up after a downtime."""
    row = await compress_daily(force=force, db=db)
    if row is None:
        return None
    return DailyDigestOut.model_validate(row)
