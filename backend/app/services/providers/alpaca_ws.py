import asyncio
from datetime import datetime


class AlpacaWsProvider:
    """WebSocket streaming provider using alpaca-py StockDataStream."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._stream = None
        self._task: asyncio.Task | None = None
        self._subscribed: set[str] = set()
        self._on_quote = None

    def _ensure_stream(self):
        if self._stream is None and self.api_key and self.api_secret:
            try:
                from alpaca.data.live import StockDataStream
                self._stream = StockDataStream(self.api_key, self.api_secret)
            except Exception as e:
                print(f"[ws-provider] init warning: {e}")

    async def start(self, on_quote):
        self._on_quote = on_quote
        self._ensure_stream()

    async def _handle_quote(self, q):
        if not self._on_quote:
            return
        try:
            await self._on_quote({
                "symbol": q.symbol,
                "bid": float(q.bid_price) if q.bid_price else None,
                "ask": float(q.ask_price) if q.ask_price else None,
                "last": float(q.ask_price) if q.ask_price else None,
                "ts": q.timestamp.isoformat() if q.timestamp else datetime.utcnow().isoformat(),
                "source": "ws",
            })
        except Exception as e:
            print(f"[ws-provider] handler error: {e}")

    def _ensure_running(self):
        if self._stream and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._runner())

    async def _runner(self):
        try:
            await asyncio.to_thread(self._stream.run)
        except Exception as e:
            print(f"[ws-provider] runner exited: {e}")

    async def subscribe(self, symbols: list[str]):
        if not self._stream:
            return
        new = [s for s in symbols if s not in self._subscribed]
        if not new:
            return
        try:
            self._stream.subscribe_quotes(self._handle_quote, *new)
            self._subscribed.update(new)
            self._ensure_running()
        except Exception as e:
            print(f"[ws-provider] subscribe error: {e}")

    async def unsubscribe(self, symbols: list[str]):
        if not self._stream:
            return
        try:
            await asyncio.to_thread(self._stream.unsubscribe_quotes, *symbols)
            for s in symbols:
                self._subscribed.discard(s)
        except Exception as e:
            print(f"[ws-provider] unsubscribe error: {e}")

    async def stop(self):
        if self._stream:
            try:
                await asyncio.to_thread(self._stream.stop)
            except Exception:
                pass
        if self._task:
            self._task.cancel()
