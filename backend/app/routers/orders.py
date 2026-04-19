from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_broker
from ..models import Order
from ..schemas import OrderIn, OrderOut
from ..security import get_current_user
from ..services.broker import AlpacaBroker, BrokerError

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
def list_orders(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Order)
        .filter(Order.mode == settings.APP_MODE)
        .order_by(Order.submitted_at.desc())
        .limit(200)
        .all()
    )


@router.post("", response_model=OrderOut)
def place_order(
    body: OrderIn,
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
    broker: AlpacaBroker = Depends(get_broker),
):
    # Server-side notional cap (estimate using limit price or last quote)
    est_price = body.limit_price or 0.0
    if not est_price:
        q = broker.latest_quote(body.symbol)
        est_price = q.get("ask") or q.get("last") or 0.0
    notional = (est_price or 0.0) * body.qty
    if notional and notional > settings.MAX_ORDER_NOTIONAL:
        raise HTTPException(
            status_code=400,
            detail=f"Order notional {notional:.2f} exceeds MAX_ORDER_NOTIONAL ({settings.MAX_ORDER_NOTIONAL})",
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

    order = Order(
        alpaca_id=result.get("alpaca_id"),
        symbol=result["symbol"],
        qty=result["qty"],
        side=result["side"],
        type=result["type"],
        limit_price=result.get("limit_price"),
        status=result.get("status", "new"),
        mode=settings.APP_MODE,
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
