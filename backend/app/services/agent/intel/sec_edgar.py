"""SEC EDGAR full-text search enrichment.

Two endpoints:
  https://www.sec.gov/files/company_tickers.json
    - static ticker->CIK+name map (cached in memory for the process lifetime).
  https://efts.sec.gov/LATEST/search-index?q="Company Name"&forms=8-K,10-K,10-Q
    - full-text JSON search. Free, no key, requires User-Agent.

We fetch the most recent 5 filings for each ticker, limited to the forms
that drive short-term trading decisions:
  8-K  - current events (earnings, M&A, material events)
  10-K - annual report
  10-Q - quarterly report

Every call swallows errors; a down EDGAR never breaks an agent run.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

_FORMS = "8-K,10-K,10-Q"

# Cache of ticker->{"name":..., "cik":...} populated on first call. Mutable
# module-level state is fine here; the map is small (~10k entries).
_TICKER_MAP: dict[str, dict[str, str]] = {}


async def _load_ticker_map(user_agent: str) -> None:
    global _TICKER_MAP
    if _TICKER_MAP:
        return
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": user_agent}) as c:
            r = await c.get(_TICKER_MAP_URL)
            r.raise_for_status()
            raw = r.json()
        # Response shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        tmp: dict[str, dict[str, str]] = {}
        for v in raw.values():
            sym = (v.get("ticker") or "").upper()
            name = v.get("title") or ""
            cik = str(v.get("cik_str") or "").zfill(10)
            if sym and name:
                tmp[sym] = {"name": name, "cik": cik}
        _TICKER_MAP = tmp
    except Exception as e:
        print(f"[sec-edgar] ticker map load failed: {e}")


def lookup_name(symbol: str) -> Optional[str]:
    sym = (symbol or "").upper()
    rec = _TICKER_MAP.get(sym)
    return rec.get("name") if rec else None


async def fetch_filings(
    symbol: str,
    *,
    user_agent: str,
    limit: int = 5,
    forms: str = _FORMS,
) -> dict[str, Any]:
    """Return {'symbol': SYM, 'entity_name': ..., 'filings': [{...}], 'search_url': ...}.
    Always returns a dict (with an 'error' key on failure) - never raises."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return {}
    if not user_agent:
        return {"symbol": sym, "error": "SEC_USER_AGENT not set"}

    await _load_ticker_map(user_agent)
    entity = lookup_name(sym)

    # Build the EDGAR search URL the user can open in the browser for the
    # same query (matches the format in the user's request).
    search_url = (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK="
        + sym
        + "&type=&dateb=&owner=include&count=40"
    )
    ui_search_url = None
    if entity:
        from urllib.parse import quote_plus
        ui_search_url = (
            f"https://www.sec.gov/edgar/search/#/entityName={quote_plus(entity)}"
        )

    out: dict[str, Any] = {
        "symbol": sym,
        "entity_name": entity,
        "search_url": ui_search_url or search_url,
        "filings": [],
    }
    if not entity:
        out["error"] = "entity not found in SEC ticker map"
        return out

    params = {
        "q": f'"{entity}"',
        "forms": forms,
        "size": str(max(1, min(10, limit * 2))),
    }
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": user_agent}) as c:
            r = await c.get(_EFTS_URL, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        out["error"] = str(e)[:200]
        return out

    hits = ((data or {}).get("hits") or {}).get("hits") or []
    filings: list[dict[str, Any]] = []
    for h in hits[:limit]:
        src = h.get("_source") or {}
        accession_raw = (h.get("_id") or "").split(":")[0]
        filename = (h.get("_id") or "").split(":")[1] if ":" in (h.get("_id") or "") else ""
        doc_url = None
        if accession_raw and filename:
            cik = str(src.get("ciks", [""])[0] or "").lstrip("0") or "0"
            accession_no_dash = accession_raw.replace("-", "")
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession_no_dash}/{filename}"
            )
        filings.append({
            "form_type": src.get("form") or src.get("form_type"),
            "file_date": src.get("file_date") or src.get("filed"),
            "entity_name": src.get("display_names", [src.get("entity_name")])[0]
                if isinstance(src.get("display_names"), list) and src.get("display_names")
                else src.get("entity_name"),
            "accession": accession_raw,
            "url": doc_url,
        })
    out["filings"] = filings
    return out


async def fetch_many(
    symbols: list[str],
    *,
    user_agent: str,
    limit_per_symbol: int = 5,
) -> dict[str, dict[str, Any]]:
    """Enrich each symbol with recent SEC filings. Returns {SYM: payload}."""
    if not symbols or not user_agent:
        return {}
    # Keep it sequential-ish (small batch, 10 req/sec SEC limit). Sleep 120ms
    # between batches to stay well clear of the cap.
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        payload = await fetch_filings(sym, user_agent=user_agent, limit=limit_per_symbol)
        if payload and payload.get("symbol"):
            out[payload["symbol"]] = payload
        await asyncio.sleep(0.12)
    return out


def brief_line(payload: dict[str, Any]) -> str:
    """Short summary for advisor prompts. E.g. '3 recent filings: 8-K 2d ago, 10-Q 32d ago'."""
    filings = payload.get("filings") or []
    if not filings:
        return ""
    from datetime import datetime, date

    def _age(s: str | None) -> str:
        if not s:
            return "?d"
        try:
            d = datetime.fromisoformat(s).date() if "T" in s else date.fromisoformat(s)
            return f"{(date.today() - d).days}d"
        except Exception:
            return "?d"

    return "recent filings: " + ", ".join(
        f"{f.get('form_type','?')} {_age(f.get('file_date'))} ago"
        for f in filings[:4]
    )
