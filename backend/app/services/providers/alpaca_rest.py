import asyncio
from datetime import datetime
from typing import Optional


class AlpacaRestProvider:
    """Polling provider: fetches latest quotes via REST every N seconds."""

    def __init__(self, api_key: str, api_secret: str, poll_interval: int = 5):
        self.api_key = api_key
        self.api_secret = api_secret
        self.poll_interval = poll_interval
        self._client = None
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            if api_key and api_secret:
                self._client = StockHistoricalDataClient(api_key, api_secret)
        except Exception as e:
            print(f"[rest-provider] init warning: {e}")

    async def poll_loop(self, symbols_provider, on_quote):
        """symbols_provider: callable returning current set[str] of symbols.
        on_quote: async callable(quote_dict)."""
        while True:
            symbols = list(symbols_provider())
            if symbols and self._client:
                try:
                    await self._fetch_and_emit(symbols, on_quote)
                except Exception as e:
                    print(f"[rest-provider] fetch error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _fetch_and_emit(self, symbols, on_quote):
        from alpaca.data.requests import StockLatestQuoteRequest

        loop = asyncio.get_event_loop()

        def _do():
            return self._client.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=symbols)
            )

        result = await loop.run_in_executor(None, _do)
        for sym, q in result.items():
            await on_quote({
                "symbol": sym,
                "bid": float(q.bid_price) if q.bid_price else None,
                "ask": float(q.ask_price) if q.ask_price else None,
                "last": float(q.ask_price) if q.ask_price else None,
                "ts": q.timestamp.isoformat() if q.timestamp else datetime.utcnow().isoformat(),
                "source": "poll",
            })
