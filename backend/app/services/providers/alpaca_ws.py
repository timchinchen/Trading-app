import asyncio
from datetime import datetime


class AlpacaWsProvider:
    """WebSocket streaming provider using alpaca-py StockDataStream.

    The stream runs in a worker thread (via asyncio.to_thread) because
    alpaca-py's run() blocks with its own internal asyncio.run(). Quote
    callbacks are bridged back to the main event loop via
    run_coroutine_threadsafe so asyncio.Queue notifications fire on the
    correct loop.  If the stream disconnects, it automatically reconnects
    with exponential backoff.
    """

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._stream = None
        self._task: asyncio.Task | None = None
        self._subscribed: set[str] = set()
        self._on_quote = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _build_stream(self):
        if not self.api_key or not self.api_secret:
            return None
        try:
            from alpaca.data.live import StockDataStream
            return StockDataStream(self.api_key, self.api_secret)
        except Exception as e:
            print(f"[ws-provider] stream build error: {e}")
            return None

    async def start(self, on_quote):
        self._on_quote = on_quote
        self._loop = asyncio.get_running_loop()

    async def _handle_quote(self, q):
        """Called from alpaca-py's internal event loop (worker thread).

        Instead of touching the main loop's asyncio.Queues directly (which
        silently breaks cross-thread Future notifications), we schedule the
        broadcast coroutine on the main loop.
        """
        if not self._on_quote or not self._loop:
            return
        try:
            payload = {
                "symbol": q.symbol,
                "bid": float(q.bid_price) if q.bid_price else None,
                "ask": float(q.ask_price) if q.ask_price else None,
                "last": float(q.ask_price) if q.ask_price else None,
                "ts": q.timestamp.isoformat() if q.timestamp else datetime.utcnow().isoformat(),
                "source": "ws",
            }
            asyncio.run_coroutine_threadsafe(self._on_quote(payload), self._loop)
        except Exception as e:
            print(f"[ws-provider] handler error: {e}")

    def _ensure_running(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._runner())

    async def _runner(self):
        """Run the Alpaca stream with automatic reconnection."""
        backoff = 1
        while True:
            stream = self._build_stream()
            if not stream:
                print("[ws-provider] cannot build stream (missing credentials?)")
                return
            self._stream = stream

            if self._subscribed:
                try:
                    stream.subscribe_quotes(self._handle_quote, *self._subscribed)
                    print(f"[ws-provider] subscribed {len(self._subscribed)} symbols")
                except Exception as e:
                    print(f"[ws-provider] subscribe error on connect: {e}")

            print(f"[ws-provider] connecting ({len(self._subscribed)} symbols) ...")
            try:
                await asyncio.to_thread(stream.run)
            except Exception as e:
                print(f"[ws-provider] stream exited: {e}")

            print(f"[ws-provider] disconnected, reconnecting in {backoff}s ...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def subscribe(self, symbols: list[str]):
        new = [s for s in symbols if s not in self._subscribed]
        if not new:
            return
        self._subscribed.update(new)
        if self._stream:
            try:
                self._stream.subscribe_quotes(self._handle_quote, *new)
            except Exception as e:
                print(f"[ws-provider] subscribe error: {e}")
        self._ensure_running()

    async def unsubscribe(self, symbols: list[str]):
        for s in symbols:
            self._subscribed.discard(s)
        if self._stream:
            try:
                await asyncio.to_thread(self._stream.unsubscribe_quotes, *symbols)
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
