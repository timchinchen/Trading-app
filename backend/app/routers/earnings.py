import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import EarningsEventOut
from ..security import get_current_user
from ..services.earnings_fmp import fetch_earnings_rows
from ..services.settings_store import get_runtime_settings

router = APIRouter(prefix="/earnings", tags=["earnings"])


@router.get("/{symbol}", response_model=list[EarningsEventOut])
async def earnings_calendar(
    symbol: str,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Earnings dates and EPS/revenue estimates vs actuals (FMP).

    Requires `FMP_API_KEY` in Settings / env. Returns an empty list when the key
    is unset or FMP returns an error — the UI explains how to enable it.
    """
    sym = (symbol or "").upper().strip()
    if not sym or len(sym) > 32 or not re.fullmatch(r"[A-Z0-9.\-]+", sym):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    rs = get_runtime_settings(db)
    raw = await fetch_earnings_rows(
        sym,
        api_key=(rs.fmp_api_key or "").strip(),
        base_url=(rs.fmp_base_url or "").strip(),
    )
    return [EarningsEventOut.model_validate(r) for r in raw]
