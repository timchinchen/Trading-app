from functools import lru_cache

from .config import settings
from .services.broker import AlpacaBroker
from .services.market_data import MarketDataService


@lru_cache
def get_broker() -> AlpacaBroker:
    return AlpacaBroker(settings.APP_MODE)


@lru_cache
def get_market_data() -> MarketDataService:
    return MarketDataService(
        mode=settings.MARKET_DATA_MODE,
        api_key=settings.alpaca_key,
        api_secret=settings.alpaca_secret,
        paper=settings.is_paper,
        poll_interval=settings.POLL_INTERVAL_SECONDS,
    )
