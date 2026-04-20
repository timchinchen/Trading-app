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

    async def fetch_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch per-symbol session snapshots (today's open + previous close).

        Uses Alpaca's snapshot endpoint which returns latest trade + today's
        daily bar + previous daily bar in a single round-trip. Returns
        {SYM: {"open": float|None, "prev_close": float|None,
               "prev_open": float|None, "day_high": float|None,
               "day_low": float|None}}.
        """
        if not symbols or not self._client:
            return {}
        try:
            from alpaca.data.requests import StockSnapshotRequest
        except Exception as e:
            print(f"[rest-provider] snapshot req import error: {e}")
            return {}

        loop = asyncio.get_event_loop()

        def _do():
            return self._client.get_stock_snapshot(
                StockSnapshotRequest(symbol_or_symbols=symbols)
            )

        try:
            result = await loop.run_in_executor(None, _do)
        except Exception as e:
            print(f"[rest-provider] snapshot fetch error: {e}")
            return {}

        out: dict[str, dict] = {}
        for sym, snap in (result or {}).items():
            if snap is None:
                continue
            daily = getattr(snap, "daily_bar", None)
            prev = getattr(snap, "previous_daily_bar", None)
            latest_trade = getattr(snap, "latest_trade", None)
            minute = getattr(snap, "minute_bar", None)

            def _f(obj, attr):
                if obj is None:
                    return None
                v = getattr(obj, attr, None)
                try:
                    return float(v) if v is not None else None
                except Exception:
                    return None

            # Prefer the most recent price we can see in the snapshot:
            # latest trade > latest minute bar close > today's daily close.
            last_px = (
                _f(latest_trade, "price")
                or _f(minute, "close")
                or _f(daily, "close")
            )

            out[sym] = {
                "open": _f(daily, "open"),
                "day_high": _f(daily, "high"),
                "day_low": _f(daily, "low"),
                "prev_close": _f(prev, "close"),
                "prev_open": _f(prev, "open"),
                "last": last_px,
            }
        return out

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
