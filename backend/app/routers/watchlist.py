from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_market_data
from ..models import WatchlistItem
from ..schemas import WatchlistItemIn, WatchlistItemOut
from ..security import get_current_user
from ..services.market_data import MarketDataService

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItemOut])
def list_items(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).all()


@router.post("", response_model=WatchlistItemOut)
async def add_item(
    body: WatchlistItemIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    md: MarketDataService = Depends(get_market_data),
):
    sym = body.symbol.upper()
    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == sym)
        .first()
    )
    if existing:
        existing.feed = body.feed
        db.commit()
        db.refresh(existing)
        await md.set_feed(sym, body.feed)
        return existing
    item = WatchlistItem(user_id=user.id, symbol=sym, feed=body.feed)
    db.add(item)
    db.commit()
    db.refresh(item)
    await md.subscribe(sym, body.feed)
    return item


@router.patch("/{symbol}", response_model=WatchlistItemOut)
async def update_feed(
    symbol: str,
    body: WatchlistItemIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    md: MarketDataService = Depends(get_market_data),
):
    sym = symbol.upper()
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == sym)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    item.feed = body.feed
    db.commit()
    db.refresh(item)
    await md.set_feed(sym, body.feed)
    return item


@router.delete("/{symbol}")
async def remove_item(
    symbol: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    md: MarketDataService = Depends(get_market_data),
):
    sym = symbol.upper()
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == sym)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    db.delete(item)
    db.commit()
    await md.unsubscribe(sym)
    return {"ok": True}
