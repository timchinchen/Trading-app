from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_broker
from ..schemas import AccountOut, ModeOut, PositionOut
from ..security import get_current_user
from ..services.broker import AlpacaBroker
from ..services.settings_store import get_runtime_settings

router = APIRouter(tags=["account"])


@router.get("/mode", response_model=ModeOut)
def mode(db: Session = Depends(get_db)):
    rs = get_runtime_settings(db)
    return ModeOut(
        mode=settings.APP_MODE,
        market_data_mode=settings.MARKET_DATA_MODE,
        max_order_notional=rs.manual_order_max_notional,
    )


@router.get("/account", response_model=AccountOut)
def account(_user=Depends(get_current_user), broker: AlpacaBroker = Depends(get_broker)):
    return broker.account()


@router.get("/positions", response_model=list[PositionOut])
def positions(_user=Depends(get_current_user), broker: AlpacaBroker = Depends(get_broker)):
    return broker.positions()
