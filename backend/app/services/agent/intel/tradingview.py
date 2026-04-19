"""Pull the latest US-stocks news headlines from TradingView.

TradingView publishes a JSON feed at
    https://news-headlines.tradingview.com/v2/headlines?category=stock&client=web&lang=en
which is the same endpoint their website calls. We keep only items whose
`relatedSymbols` contain a NASDAQ/NYSE/AMEX-listed ticker so the output is
actionable (and not filled with Asia-Pacific news).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_URL = "https://news-headlines.tradingview.com/v2/headlines?category=stock&client=web&lang=en"
_ALLOWED_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}


def _parse_symbol(raw: str) -> str | None:
    """Extract the bare ticker from `NASDAQ:AAPL` style references."""
    if not raw:
        return None
    if ":" in raw:
        ex, sym = raw.split(":", 1)
        if ex.upper() not in _ALLOWED_EXCHANGES:
            return None
        return sym.upper()
    return raw.upper()


async def fetch_news(limit: int = 20) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": _UA, "Accept": "application/json"},
        ) as c:
            r = await c.get(_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {"items": [], "error": f"http: {e}"}

    items: list[dict[str, Any]] = []
    for raw in data.get("items", []):
        syms = []
        for rs in raw.get("relatedSymbols") or []:
            sym = _parse_symbol(rs.get("symbol") or "")
            if sym:
                syms.append(sym)
        if not syms:
            continue
        ts = raw.get("published")
        dt: str | None = None
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        items.append({
            "title": (raw.get("title") or "").strip(),
            "source": raw.get("source"),
            "urgency": raw.get("urgency"),
            "story_path": raw.get("storyPath"),
            "published_at": dt,
            "symbols": syms[:4],  # keep headline focused
        })
        if len(items) >= limit:
            break
    return {"items": items}
