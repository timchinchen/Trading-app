from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_broker, get_market_data
from ..models import Order
from ..schemas import OrderIn, OrderOut
from ..security import get_current_user
from ..services.broker import AlpacaBroker, BrokerError
from ..services.market_data import MarketDataService
from ..services.settings_store import get_runtime_settings

router = APIRouter(prefix="/orders", tags=["orders"])


# Statuses where the local DB row may still be stale vs Alpaca. We reconcile
# these on every GET /orders so fill price + filled_at show up as soon as the
# exchange accepts them, without needing a webhook.
_RECONCILE_STATUSES = {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
}


@router.get("", response_model=list[OrderOut])
async def list_orders(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    broker: AlpacaBroker = Depends(get_broker),
    md: MarketDataService = Depends(get_market_data),
):
    rows = (
        db.query(Order)
        .filter(Order.mode == settings.APP_MODE)
        .order_by(Order.submitted_at.desc())
        .limit(200)
        .all()
    )
    if not rows:
        return []

    # 1) Reconcile: for anything still pending we ask Alpaca for the latest
    # snapshot of that order and write fill fields back to the local row.
    # Bounded to orders in _RECONCILE_STATUSES or those with fill info still
    # missing, so the common case is zero API calls.
    dirty = False
    for r in rows:
        needs_refresh = (
            r.alpaca_id
            and (r.status in _RECONCILE_STATUSES or r.filled_avg_price is None)
        )
        if not needs_refresh:
            continue
        latest = broker.get_order_by_id(r.alpaca_id)
        if not latest:
            continue
        if latest.get("status") and latest["status"] != r.status:
            r.status = latest["status"]
            dirty = True
        fap = latest.get("filled_avg_price")
        fqty = latest.get("filled_qty")
        fat = latest.get("filled_at")
        if fap is not None and r.filled_avg_price != fap:
            r.filled_avg_price = fap
            dirty = True
        if fqty is not None and r.filled_qty != fqty:
            r.filled_qty = fqty
            dirty = True
        if fat is not None and r.filled_at != fat:
            # Alpaca returns a tz-aware datetime; drop the tz because our
            # SQLite column is naive.
            try:
                r.filled_at = fat.replace(tzinfo=None) if hasattr(fat, "tzinfo") else fat
            except Exception:
                r.filled_at = datetime.utcnow()
            dirty = True
    if dirty:
        db.commit()

    # 2) One snapshot-cache lookup for all distinct symbols in the order
    # list. This is the exact same cache the /watchlist endpoint uses, so
    # the usual case is zero extra round-trips. The cache also remembers the
    # last live WS tick, so `last` is as fresh as the price stream.
    symbols = sorted({r.symbol for r in rows})
    snaps = await md.get_snapshots(symbols)

    out: list[OrderOut] = []
    for r in rows:
        snap = snaps.get(r.symbol) or {}
        current = snap.get("last")
        fill_px = r.filled_avg_price
        fill_qty = r.filled_qty if r.filled_qty is not None else r.qty
        total_cost = (fill_px * fill_qty) if (fill_px and fill_qty) else None
        pct_change = None
        if current and fill_px:
            pct_change = (current - fill_px) / fill_px * 100.0

        out.append(
            OrderOut(
                id=r.id,
                alpaca_id=r.alpaca_id,
                symbol=r.symbol,
                qty=r.qty,
                side=r.side,
                type=r.type,
                limit_price=r.limit_price,
                status=r.status,
                mode=r.mode,
                submitted_at=r.submitted_at,
                filled_avg_price=fill_px,
                filled_qty=r.filled_qty,
                filled_at=r.filled_at,
                total_cost=total_cost,
                current_price=current,
                pct_change=pct_change,
            )
        )
    return out


@router.post("", response_model=OrderOut)
def place_order(
    body: OrderIn,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    broker: AlpacaBroker = Depends(get_broker),
):
    # Server-side notional cap. Two ceilings are enforced:
    #   1. `manual_order_max_notional` - user's safety cap (default $100) to
    #      stop a single fat-finger click placing an oversize order. Editable
    #      from the Settings UI.
    #   2. Alpaca's reported `buying_power` for the active mode - real broker
    #      ceiling, so we never submit something the exchange will reject.
    est_price = body.limit_price or 0.0
    if not est_price:
        q = broker.latest_quote(body.symbol)
        est_price = q.get("ask") or q.get("last") or 0.0
    notional = (est_price or 0.0) * body.qty

    rs = get_runtime_settings(db)
    user_cap = float(rs.manual_order_max_notional or 0.0)
    if notional and user_cap > 0 and notional > user_cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Order notional {notional:.2f} exceeds MANUAL_ORDER_MAX_NOTIONAL "
                f"({user_cap:.2f}). Raise the cap in Settings if this is intentional."
            ),
        )

    try:
        broker_cap = float((broker.account() or {}).get("buying_power") or 0.0)
    except Exception:
        broker_cap = 0.0
    if notional and broker_cap > 0 and notional > broker_cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Order notional {notional:.2f} exceeds Alpaca buying_power "
                f"({broker_cap:.2f})."
            ),
        )

    try:
        result = broker.place_order(
            symbol=body.symbol.upper(),
            qty=body.qty,
            side=body.side,
            type_=body.type,
            limit_price=body.limit_price,
        )
    except BrokerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Broker error: {e}")

    fat = result.get("filled_at")
    try:
        fat_val = fat.replace(tzinfo=None) if fat and hasattr(fat, "tzinfo") else fat
    except Exception:
        fat_val = None
    order = Order(
        alpaca_id=result.get("alpaca_id"),
        symbol=result["symbol"],
        qty=result["qty"],
        side=result["side"],
        type=result["type"],
        limit_price=result.get("limit_price"),
        status=result.get("status", "new"),
        mode=settings.APP_MODE,
        filled_avg_price=result.get("filled_avg_price"),
        filled_qty=result.get("filled_qty"),
        filled_at=fat_val,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.delete("/{order_id}")
def cancel_order(
    order_id: int,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    broker: AlpacaBroker = Depends(get_broker),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        if order.alpaca_id:
            broker.cancel_order(order.alpaca_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Broker error: {e}")
    order.status = "cancelled"
    db.commit()
    return {"ok": True}
