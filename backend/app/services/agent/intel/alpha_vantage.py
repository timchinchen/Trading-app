"""Alpha Vantage per-ticker enrichment.

Three lightweight calls per symbol (all on the free tier at 25 req/day):
  GLOBAL_QUOTE      - price, change%, volume, 52-week hi/lo
  OVERVIEW          - sector, industry, market cap, PE, EPS, dividend yield
  EARNINGS          - next / most-recent quarterly EPS + surprise

All calls swallow their errors and return an empty dict on failure (so an
expired key or a 429 never breaks an agent run). Caller passes the API key
from runtime settings; if the key is empty we short-circuit to an empty
payload.

Free tier = 25 calls/day. Enriching a ~5 ticker shortlist with 3 calls each
is ~15 calls/run, leaving room for roughly 1 full run per day. If you have a
premium key the 75-1200 calls/min tiers remove this constraint entirely.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

_BASE = "https://www.alphavantage.co/query"
_SEM = asyncio.Semaphore(3)


async def _get(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    params: dict[str, str],
) -> Any:
    async with _SEM:
        r = await client.get(
            _BASE,
            params={**params, "apikey": api_key},
            timeout=15,
        )
    r.raise_for_status()
    data = r.json()
    if "Error Message" in data:
        raise ValueError(data["Error Message"])
    if "Note" in data:
        raise ValueError(data["Note"])
    if "Information" in data:
        raise ValueError(data["Information"])
    return data


def _safe_float(val: Any) -> float | None:
    if val is None or val == "" or val == "None":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def fetch_one(
    symbol: str,
    *,
    api_key: str,
) -> dict[str, Any]:
    """Return an enrichment dict for one symbol. Empty dict on any failure."""
    sym = (symbol or "").upper().strip()
    if not sym or not api_key:
        return {}

    out: dict[str, Any] = {"symbol": sym}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "TradingApp/1.0"}) as c:
            tasks = {
                "quote": asyncio.create_task(
                    _get(c, api_key=api_key, params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": sym,
                    })
                ),
                "overview": asyncio.create_task(
                    _get(c, api_key=api_key, params={
                        "function": "OVERVIEW",
                        "symbol": sym,
                    })
                ),
                "earnings": asyncio.create_task(
                    _get(c, api_key=api_key, params={
                        "function": "EARNINGS",
                        "symbol": sym,
                    })
                ),
            }

            for k, t in tasks.items():
                try:
                    data = await t
                except httpx.HTTPStatusError as e:
                    out[f"{k}_error"] = f"HTTP {e.response.status_code}"
                    continue
                except Exception as e:
                    out[f"{k}_error"] = str(e)[:200]
                    continue

                if k == "quote":
                    gq = data.get("Global Quote") or {}
                    out["quote"] = {
                        "price": _safe_float(gq.get("05. price")),
                        "change_pct": _safe_float(
                            (gq.get("10. change percent") or "").rstrip("%")
                        ),
                        "volume": _safe_float(gq.get("06. volume")),
                        "prev_close": _safe_float(gq.get("08. previous close")),
                        "open": _safe_float(gq.get("02. open")),
                        "high": _safe_float(gq.get("03. high")),
                        "low": _safe_float(gq.get("04. low")),
                    }
                elif k == "overview":
                    out["overview"] = {
                        "company_name": data.get("Name"),
                        "sector": data.get("Sector"),
                        "industry": data.get("Industry"),
                        "country": data.get("Country"),
                        "exchange": data.get("Exchange"),
                        "market_cap": _safe_float(data.get("MarketCapitalization")),
                        "pe_ratio": _safe_float(data.get("PERatio")),
                        "eps": _safe_float(data.get("EPS")),
                        "dividend_yield": _safe_float(data.get("DividendYield")),
                        "52_week_high": _safe_float(data.get("52WeekHigh")),
                        "52_week_low": _safe_float(data.get("52WeekLow")),
                        "50_day_ma": _safe_float(data.get("50DayMovingAverage")),
                        "200_day_ma": _safe_float(data.get("200DayMovingAverage")),
                        "beta": _safe_float(data.get("Beta")),
                        "description": (data.get("Description") or "")[:600],
                    }
                elif k == "earnings":
                    quarterly = data.get("quarterlyEarnings") or []
                    latest = quarterly[0] if quarterly else {}
                    out["earnings"] = {
                        "latest_quarter": latest.get("fiscalDateEnding"),
                        "reported_eps": _safe_float(latest.get("reportedEPS")),
                        "estimated_eps": _safe_float(latest.get("estimatedEPS")),
                        "surprise_pct": _safe_float(latest.get("surprisePercentage")),
                    }
    except Exception as e:
        out["error"] = str(e)[:300]

    return out


async def fetch_many(
    symbols: list[str],
    *,
    api_key: str,
) -> dict[str, dict[str, Any]]:
    """Fetch enrichment for each symbol. Returns {SYM: payload}.

    Uses return_exceptions=True so one symbol's failure never blocks the rest.
    """
    if not api_key:
        return {}
    results = await asyncio.gather(
        *(fetch_one(s, api_key=api_key) for s in symbols),
        return_exceptions=True,
    )
    return {
        r.get("symbol"): r
        for r in results
        if isinstance(r, dict) and r.get("symbol")
    }


def brief_line(payload: dict[str, Any]) -> str:
    """One-line summary for a prompt/context. Empty string if nothing usable."""
    bits: list[str] = []
    overview = payload.get("overview") or {}
    quote = payload.get("quote") or {}
    earnings = payload.get("earnings") or {}

    if overview.get("sector") or overview.get("industry"):
        bits.append(f"{overview.get('sector') or '?'} / {overview.get('industry') or '?'}")
    mc = overview.get("market_cap")
    if mc:
        bits.append(f"mcap ${_fmt_big(mc)}")
    pe = overview.get("pe_ratio")
    if pe is not None:
        try:
            bits.append(f"P/E {float(pe):.1f}")
        except Exception:
            pass
    eps = overview.get("eps")
    if eps is not None:
        try:
            bits.append(f"EPS ${float(eps):.2f}")
        except Exception:
            pass
    if quote.get("change_pct") is not None:
        try:
            bits.append(f"today {float(quote['change_pct']):+.2f}%")
        except Exception:
            pass
    surprise = earnings.get("surprise_pct")
    if surprise is not None:
        try:
            bits.append(f"EPS surprise {float(surprise):+.1f}%")
        except Exception:
            pass
    return " · ".join(bits)


def _fmt_big(n: float | int | None) -> str:
    if n is None:
        return "?"
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"
