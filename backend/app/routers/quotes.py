from fastapi import APIRouter, Depends

from ..deps import get_broker
from ..schemas import QuoteOut
from ..security import get_current_user
from ..services.broker import AlpacaBroker

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.get("/{symbol}", response_model=QuoteOut)
def get_quote(
    symbol: str,
    _user=Depends(get_current_user),
    broker: AlpacaBroker = Depends(get_broker),
):
    return broker.latest_quote(symbol.upper())
