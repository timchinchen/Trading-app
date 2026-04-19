"""Financial Modeling Prep per-ticker enrichment.

Three cheap calls per symbol, all on the free tier (v3 endpoints):
  /quote/{sym}        - price, change%, volume, 52wk hi/lo, market cap
  /profile/{sym}      - sector, industry, description, CEO, website, country
  /ratios-ttm/{sym}   - PE TTM, price/sales, debt/equity, current ratio

All calls swallow their errors and return an empty dict on failure (so an
expired key or a 429 never breaks an agent run). Caller passes the API key
+ base URL from runtime settings; if the key is empty we short-circuit to
an empty payload.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


# Conservative concurrency: FMP free tier is 250 calls/day. Enriching the
# ~5-6 ticker shortlist with 3 calls each is ~15-18 calls/run which is fine
# even at one run every 30 minutes during market hours.
_SEM = asyncio.Semaphore(4)


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    api_key: str,
) -> Any:
    async with _SEM:
        r = await client.get(url, params={"apikey": api_key}, timeout=15)
    r.raise_for_status()
    return r.json()


async def fetch_one(
    symbol: str,
    *,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Return an enrichment dict for one symbol. Empty dict on any failure."""
    sym = (symbol or "").upper().strip()
    if not sym or not api_key:
        return {}

    base = (base_url or "https://financialmodelingprep.com/api/v3").rstrip("/")

    urls = {
        "quote": f"{base}/quote/{sym}",
        "profile": f"{base}/profile/{sym}",
        "ratios": f"{base}/ratios-ttm/{sym}",
    }

    out: dict[str, Any] = {"symbol": sym}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "TradingApp/1.0"}) as c:
            tasks = {k: asyncio.create_task(_get(c, u, api_key=api_key)) for k, u in urls.items()}
            for k, t in tasks.items():
                try:
                    data = await t
                except httpx.HTTPStatusError as e:
                    out[f"{k}_error"] = f"HTTP {e.response.status_code}"
                    continue
                except Exception as e:
                    out[f"{k}_error"] = str(e)[:200]
                    continue

                # FMP wraps scalars in a single-item list for these endpoints.
                item = (data[0] if isinstance(data, list) and data else data) or {}

                if k == "quote":
                    out["quote"] = {
                        "price": item.get("price"),
                        "change_pct": item.get("changesPercentage"),
                        "volume": item.get("volume"),
                        "avg_volume": item.get("avgVolume"),
                        "year_high": item.get("yearHigh"),
                        "year_low": item.get("yearLow"),
                        "market_cap": item.get("marketCap"),
                    }
                elif k == "profile":
                    out["profile"] = {
                        "company_name": item.get("companyName"),
                        "sector": item.get("sector"),
                        "industry": item.get("industry"),
                        "country": item.get("country"),
                        "ceo": item.get("ceo"),
                        "website": item.get("website"),
                        "exchange": item.get("exchangeShortName") or item.get("exchange"),
                        "is_etf": bool(item.get("isEtf")),
                        "description": (item.get("description") or "")[:600],
                    }
                elif k == "ratios":
                    out["ratios_ttm"] = {
                        "pe_ttm": item.get("peRatioTTM"),
                        "price_to_sales_ttm": item.get("priceToSalesRatioTTM"),
                        "debt_to_equity_ttm": item.get("debtEquityRatioTTM"),
                        "current_ratio_ttm": item.get("currentRatioTTM"),
                        "return_on_equity_ttm": item.get("returnOnEquityTTM"),
                        "dividend_yield_ttm": item.get("dividendYieldTTM"),
                    }
    except Exception as e:
        out["error"] = str(e)[:300]

    return out


async def fetch_many(
    symbols: list[str],
    *,
    api_key: str,
    base_url: str,
) -> dict[str, dict[str, Any]]:
    """Fetch enrichment for each symbol. Returns {SYM: payload}."""
    if not api_key:
        return {}
    results = await asyncio.gather(
        *(fetch_one(s, api_key=api_key, base_url=base_url) for s in symbols),
        return_exceptions=False,
    )
    return {r.get("symbol"): r for r in results if r and r.get("symbol")}


def brief_line(payload: dict[str, Any]) -> str:
    """One-line summary for a prompt/context. Empty string if nothing usable."""
    bits: list[str] = []
    profile = payload.get("profile") or {}
    quote = payload.get("quote") or {}
    ratios = payload.get("ratios_ttm") or {}

    if profile.get("sector") or profile.get("industry"):
        bits.append(f"{profile.get('sector') or '?'} / {profile.get('industry') or '?'}")
    mc = quote.get("market_cap")
    if mc:
        bits.append(f"mcap ${_fmt_big(mc)}")
    pe = ratios.get("pe_ttm")
    if pe is not None:
        try:
            bits.append(f"P/E {float(pe):.1f}")
        except Exception:
            pass
    if quote.get("change_pct") is not None:
        try:
            bits.append(f"today {float(quote['change_pct']):+.2f}%")
        except Exception:
            pass
    if quote.get("year_high") and quote.get("price"):
        try:
            ratio = float(quote["price"]) / float(quote["year_high"])
            bits.append(f"{ratio * 100:.0f}% of 52wk high")
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
