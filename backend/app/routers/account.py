from fastapi import APIRouter, Depends

from ..config import settings
from ..deps import get_broker
from ..schemas import AccountOut, ModeOut, PositionOut
from ..security import get_current_user
from ..services.broker import AlpacaBroker

router = APIRouter(tags=["account"])


@router.get("/mode", response_model=ModeOut)
def mode():
    return ModeOut(
        mode=settings.APP_MODE,
        market_data_mode=settings.MARKET_DATA_MODE,
        max_order_notional=settings.MAX_ORDER_NOTIONAL,
    )


@router.get("/account", response_model=AccountOut)
def account(_user=Depends(get_current_user), broker: AlpacaBroker = Depends(get_broker)):
    return broker.account()


@router.get("/positions", response_model=list[PositionOut])
def positions(_user=Depends(get_current_user), broker: AlpacaBroker = Depends(get_broker)):
    return broker.positions()
