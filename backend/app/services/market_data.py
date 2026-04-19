import asyncio
import time
from typing import Literal

from .providers.alpaca_rest import AlpacaRestProvider
from .providers.alpaca_ws import AlpacaWsProvider


# OPEN / PREV CLOSE are session-scoped and don't change tick-by-tick, so we
# cache them per-symbol for this long before re-hitting the snapshot API.
_SNAPSHOT_TTL_S = 5 * 60


class MarketDataService:
    """Routes per-symbol subscriptions to either WebSocket or REST polling.

    mode:
      - "ws"    : everything via websocket
      - "poll"  : everything via REST polling
      - "mixed" : per-symbol routing (default "ws" unless caller overrides)
    """

    def __init__(self, mode: Literal["ws", "poll", "mixed"], api_key: str,
                 api_secret: str, paper: bool, poll_interval: int = 5):
        self.mode = mode
        self.ws = AlpacaWsProvider(api_key, api_secret)
        self.rest = AlpacaRestProvider(api_key, api_secret, poll_interval=poll_interval)

        self._routes: dict[str, str] = {}     # symbol -> "ws" | "poll"
        self._listeners: set[asyncio.Queue] = set()
        self._poll_task: asyncio.Task | None = None
        self._started = False
        # symbol -> (expires_at_unix, {"open": float|None, "prev_close": float|None, ...})
        self._snapshots: dict[str, tuple[float, dict]] = {}
        self._snapshot_lock = asyncio.Lock()

    async def start(self):
        if self._started:
            return
        self._started = True
        await self.ws.start(self._broadcast)
        if self.mode in ("poll", "mixed"):
            self._poll_task = asyncio.create_task(
                self.rest.poll_loop(self._poll_symbols, self._broadcast)
            )

    def _poll_symbols(self) -> set[str]:
        return {s for s, feed in self._routes.items() if feed == "poll"}

    async def _broadcast(self, quote: dict):
        dead = []
        for q in self._listeners:
            try:
                q.put_nowait(quote)
            except Exception:
                dead.append(q)
        for q in dead:
            self._listeners.discard(q)

    def add_listener(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._listeners.add(q)
        return q

    def remove_listener(self, q: asyncio.Queue) -> None:
        self._listeners.discard(q)

    def _resolve_feed(self, requested: str | None) -> str:
        if self.mode == "ws":
            return "ws"
        if self.mode == "poll":
            return "poll"
        # mixed
        return requested or "ws"

    async def subscribe(self, symbol: str, feed: str | None = None):
        symbol = symbol.upper()
        feed_resolved = self._resolve_feed(feed)
        prev = self._routes.get(symbol)
        self._routes[symbol] = feed_resolved
        if feed_resolved == "ws":
            if prev == "poll":
                pass  # rest poller will simply stop including it
            await self.ws.subscribe([symbol])
        else:  # poll
            if prev == "ws":
                await self.ws.unsubscribe([symbol])

    async def unsubscribe(self, symbol: str):
        symbol = symbol.upper()
        feed = self._routes.pop(symbol, None)
        if feed == "ws":
            await self.ws.unsubscribe([symbol])

    async def set_feed(self, symbol: str, feed: str):
        await self.subscribe(symbol, feed)

    def routes(self) -> dict[str, str]:
        return dict(self._routes)

    async def get_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        """Return cached session snapshots (open + prev_close) for each symbol,
        fetching any that are missing or expired. Safe to call from request
        handlers — one combined REST call, serialised by `_snapshot_lock`."""
        if not symbols:
            return {}
        syms = [s.upper() for s in symbols]
        now = time.time()

        stale: list[str] = []
        out: dict[str, dict] = {}
        for sym in syms:
            cached = self._snapshots.get(sym)
            if cached and cached[0] > now:
                out[sym] = cached[1]
            else:
                stale.append(sym)

        if stale:
            async with self._snapshot_lock:
                # Re-check inside the lock to dedupe concurrent callers.
                still_stale = [
                    s for s in stale
                    if not self._snapshots.get(s)
                    or self._snapshots[s][0] <= time.time()
                ]
                if still_stale:
                    fresh = await self.rest.fetch_snapshots(still_stale)
                    exp = time.time() + _SNAPSHOT_TTL_S
                    for sym in still_stale:
                        self._snapshots[sym] = (exp, fresh.get(sym) or {})
                for sym in stale:
                    entry = self._snapshots.get(sym)
                    if entry:
                        out[sym] = entry[1]

        return out

    async def snapshot_for(self, symbol: str) -> dict:
        res = await self.get_snapshots([symbol])
        return res.get(symbol.upper(), {})
