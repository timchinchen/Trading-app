from datetime import datetime, timedelta

from app.models import Order
from app.routers.orders import _compute_realized_sell_pl


def _mk_order(
    *,
    oid: int,
    side: str,
    symbol: str,
    qty: float,
    fill_px: float,
    ts: datetime,
) -> Order:
    o = Order(
        id=oid,
        side=side,
        symbol=symbol,
        qty=qty,
        filled_qty=qty,
        filled_avg_price=fill_px,
        status="filled",
        mode="paper",
        submitted_at=ts,
        filled_at=ts,
        type="market",
    )
    return o


def test_compute_realized_sell_pl_uses_fifo_lots():
    t0 = datetime(2026, 5, 1, 10, 0, 0)
    rows = [
        _mk_order(oid=1, side="buy", symbol="VECO", qty=1.0, fill_px=50.0, ts=t0),
        _mk_order(oid=2, side="buy", symbol="VECO", qty=1.0, fill_px=60.0, ts=t0 + timedelta(minutes=1)),
        _mk_order(oid=3, side="sell", symbol="VECO", qty=1.5, fill_px=70.0, ts=t0 + timedelta(minutes=2)),
    ]

    by_id = _compute_realized_sell_pl(rows)
    # 1.0 share from $50 lot => +$20
    # 0.5 share from $60 lot => +$5
    assert by_id[3] == 25.0


def test_compute_realized_sell_pl_returns_none_if_basis_unknown():
    t0 = datetime(2026, 5, 1, 10, 0, 0)
    rows = [
        _mk_order(oid=1, side="buy", symbol="VECO", qty=1.0, fill_px=50.0, ts=t0),
        _mk_order(oid=2, side="sell", symbol="VECO", qty=2.0, fill_px=70.0, ts=t0 + timedelta(minutes=1)),
    ]

    by_id = _compute_realized_sell_pl(rows)
    assert by_id[2] is None
