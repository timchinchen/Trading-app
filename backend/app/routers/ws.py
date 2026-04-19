import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from ..config import settings
from ..deps import get_market_data
from ..security import ALGO
from ..services.market_data import MarketDataService

router = APIRouter(tags=["ws"])


def _verify_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGO])
        return True
    except JWTError:
        return False


@router.websocket("/ws/prices")
async def ws_prices(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
    symbols: Optional[str] = Query(default=None),
    md: MarketDataService = Depends(get_market_data),
):
    if not _verify_token(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    if symbols:
        for s in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
            await md.subscribe(s)

    queue = md.add_listener()
    try:
        while True:
            try:
                quote = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(quote, default=str))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        md.remove_listener(queue)
