"""Scrape top movers and the default screener table from stockanalysis.com.

Both pages render a server-side HTML table with id `main-table` that we can
parse without running JavaScript. We tolerate layout changes - if the shape
shifts we return an empty payload instead of crashing the agent run.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

_MOVERS_URLS = {
    "gainers": "https://stockanalysis.com/markets/gainers/",
    "losers": "https://stockanalysis.com/markets/losers/",
    "active": "https://stockanalysis.com/markets/active/",
}
_SCREENER_URL = "https://stockanalysis.com/stocks/screener/"

_TABLE_RE = re.compile(
    r'<table[^>]*id="main-table"[^>]*>(.*?)</table>', re.DOTALL
)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_rows(html: str) -> list[list[str]]:
    m = _TABLE_RE.search(html)
    if not m:
        return []
    rows = _ROW_RE.findall(m.group(1))
    out: list[list[str]] = []
    for r in rows:
        cells = [
            _TAG_RE.sub("", c).replace("&amp;", "&").strip()
            for c in _CELL_RE.findall(r)
        ]
        if cells:
            out.append(cells)
    return out


def _pct_to_float(v: str) -> float | None:
    v = v.strip().rstrip("%").replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def _price_to_float(v: str) -> float | None:
    v = v.replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


async def _get(url: str, timeout: float = 10.0) -> str:
    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True
    ) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def _col_index(header: list[str], *needles: str) -> int | None:
    """Return the first column whose header contains any needle (case-insensitive)."""
    for i, h in enumerate(header):
        lh = h.lower()
        if any(n.lower() in lh for n in needles):
            return i
    return None


async def fetch_movers(kind: str = "gainers", limit: int = 10) -> dict[str, Any]:
    """kind in {'gainers','losers','active'}.

    Note: column order differs between pages (e.g. active puts Volume before
    % Change) so we look up columns by header text instead of assuming a
    fixed layout.
    """
    url = _MOVERS_URLS[kind]
    try:
        html = await _get(url)
    except Exception as e:
        return {"kind": kind, "rows": [], "error": f"http: {e}"}

    rows = _parse_rows(html)
    if len(rows) < 2:
        return {"kind": kind, "rows": [], "error": "no rows parsed"}

    header = rows[0]
    i_sym = _col_index(header, "Symbol")
    i_co = _col_index(header, "Company")
    i_pct = _col_index(header, "% Change", "Change %")
    i_price = _col_index(header, "Stock Price", "Price")
    if i_sym is None or i_pct is None or i_price is None:
        return {
            "kind": kind, "rows": [],
            "error": f"unexpected header: {header}",
        }

    out: list[dict[str, Any]] = []
    for r in rows[1:]:
        if len(r) <= max(i_sym, i_pct, i_price):
            continue
        symbol = r[i_sym].upper()
        company = r[i_co] if i_co is not None and i_co < len(r) else ""
        pct = _pct_to_float(r[i_pct])
        price = _price_to_float(r[i_price])
        out.append({
            "symbol": symbol,
            "company": company,
            "pct_change": pct,
            "price": price,
        })
        if len(out) >= limit:
            break
    return {"kind": kind, "rows": out}


async def fetch_screener(limit: int = 15) -> dict[str, Any]:
    """Default screener page (large-cap US stocks by market cap)."""
    try:
        html = await _get(_SCREENER_URL)
    except Exception as e:
        return {"rows": [], "error": f"http: {e}"}

    rows = _parse_rows(html)
    if len(rows) < 2:
        return {"rows": [], "error": "no rows parsed"}

    header = rows[0]
    i_sym = _col_index(header, "Symbol")
    i_co = _col_index(header, "Company")
    i_mc = _col_index(header, "Market Cap")
    i_price = _col_index(header, "Stock Price", "Price")
    i_pct = _col_index(header, "% Change", "Change %")
    i_ind = _col_index(header, "Industry")
    if i_sym is None:
        return {"rows": [], "error": f"no Symbol col: {header}"}

    out: list[dict[str, Any]] = []
    for r in rows[1:]:
        if len(r) <= i_sym:
            continue
        out.append({
            "symbol": r[i_sym].upper(),
            "company": r[i_co] if i_co is not None and i_co < len(r) else "",
            "market_cap": r[i_mc] if i_mc is not None and i_mc < len(r) else None,
            "price": _price_to_float(r[i_price]) if i_price is not None and i_price < len(r) else None,
            "pct_change": _pct_to_float(r[i_pct]) if i_pct is not None and i_pct < len(r) else None,
            "industry": r[i_ind] if i_ind is not None and i_ind < len(r) else None,
        })
        if len(out) >= limit:
            break
    return {"rows": out}


async def fetch_all() -> dict[str, Any]:
    gainers, losers, active, screener = await asyncio.gather(
        fetch_movers("gainers", limit=10),
        fetch_movers("losers", limit=10),
        fetch_movers("active", limit=10),
        fetch_screener(limit=15),
        return_exceptions=False,
    )
    return {
        "gainers": gainers,
        "losers": losers,
        "active": active,
        "screener": screener,
    }
