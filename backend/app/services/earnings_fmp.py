"""Earnings calendar rows from Financial Modeling Prep (FMP).

Uses the same API key + base URL as the rest of the app (runtime settings).
We only call documented JSON endpoints — no third-party HTML scraping."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _as_opt_str(v: Any) -> str | None:
    """FMP sometimes returns non-strings; Pydantic `EarningsEventOut` expects optional str."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


def _row_from_fmp(sym: str, row: dict[str, Any]) -> dict[str, Any]:
    d = row.get("date")
    return {
        "date": str(d) if d is not None else "",
        "symbol": sym,
        "time": _as_opt_str(row.get("time")),
        "eps_actual": _f(row.get("eps")),
        "eps_estimate": _f(row.get("epsEstimated")),
        "revenue_actual": _f(row.get("revenue")),
        "revenue_estimate": _f(row.get("revenueEstimated")),
        "fiscal_date_ending": _as_opt_str(row.get("fiscalDateEnding")),
    }


def _merge_fmp(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k, v in src.items():
        if k in ("symbol", "date"):
            continue
        if v is None or v == "":
            continue
        if dst.get(k) in (None, "") and v not in (None, ""):
            dst[k] = v


async def fetch_earnings_rows(
    symbol: str,
    *,
    api_key: str,
    base_url: str,
    history_limit: int = 16,
) -> list[dict[str, Any]]:
    """Return normalized earnings rows (newest first). Empty on missing key or error."""
    sym = (symbol or "").upper().strip()
    if not sym or not api_key:
        return []

    base = (base_url or "https://financialmodelingprep.com/api/v3").rstrip("/")
    headers = {"User-Agent": "TradingApp/1.0"}

    merged: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(headers=headers, timeout=25) as client:
        hist_url = f"{base}/historical/earning_calendar/{sym}"
        try:
            hr = await client.get(hist_url, params={"apikey": api_key, "limit": history_limit})
            hr.raise_for_status()
            hist = hr.json()
        except Exception:
            hist = None

        if isinstance(hist, list):
            for row in hist:
                if not isinstance(row, dict):
                    continue
                d = row.get("date")
                if not d:
                    continue
                key = str(d)
                merged[key] = _row_from_fmp(sym, row)

        start = (date.today() - timedelta(days=14)).isoformat()
        end = (date.today() + timedelta(days=120)).isoformat()
        cal_url = f"{base}/earning_calendar"
        try:
            cr = await client.get(
                cal_url,
                params={
                    "symbol": sym,
                    "from": start,
                    "to": end,
                    "apikey": api_key,
                },
            )
            cr.raise_for_status()
            cal = cr.json()
        except Exception:
            cal = None

        if isinstance(cal, list):
            for row in cal:
                if not isinstance(row, dict):
                    continue
                if (row.get("symbol") or "").upper() != sym:
                    continue
                d = row.get("date")
                if not d:
                    continue
                key = str(d)
                incoming = _row_from_fmp(sym, row)
                if key in merged:
                    _merge_fmp(merged[key], incoming)
                else:
                    merged[key] = incoming

    rows = [r for r in merged.values() if r.get("date")]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[: max(history_limit, 24)]
