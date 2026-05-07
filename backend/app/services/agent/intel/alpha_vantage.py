"""Alpha Vantage earnings-focused enrichment.

We use the EARNINGS_CALENDAR endpoint for the whole market (12-month horizon),
cache it in-memory, and then filter it down to the shortlist symbols.

This keeps call volume low on free-tier keys while giving actionable context:
  - next report date
  - days until report
  - fiscal period end
  - estimated EPS
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, date, timedelta
from typing import Any

import httpx

_BASE = "https://www.alphavantage.co/query"
_CACHE_TTL = timedelta(hours=6)

# Shared cache of the all-symbol earnings calendar.
_CALENDAR_CACHE: dict[str, Any] = {
    "expires_at": datetime.min,
    "rows_by_symbol": {},
}


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _safe_float(val: Any) -> float | None:
    if val is None or val == "" or val == "None":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_calendar_csv(text: str) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        sym = (raw.get("symbol") or "").upper().strip()
        if not sym:
            continue
        row = {
            "symbol": sym,
            "name": (raw.get("name") or "").strip(),
            "reportDate": (raw.get("reportDate") or "").strip(),
            "fiscalDateEnding": (raw.get("fiscalDateEnding") or "").strip(),
            "estimate": (raw.get("estimate") or "").strip(),
            "currency": (raw.get("currency") or "").strip(),
        }
        out.setdefault(sym, []).append(row)
    for sym, rows in out.items():
        rows.sort(key=lambda r: (r.get("reportDate") or "9999-12-31"))
        out[sym] = rows
    return out


def _build_symbol_payload(symbol: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    today = date.today()
    sym = (symbol or "").upper().strip()
    out: dict[str, Any] = {"symbol": sym}
    if not rows:
        return out

    upcoming: dict[str, str] | None = None
    previous: dict[str, str] | None = None
    for row in rows:
        rd = _parse_date(row.get("reportDate"))
        if rd is None:
            continue
        if rd >= today and upcoming is None:
            upcoming = row
        if rd < today:
            previous = row

    sample = upcoming or previous or rows[0]
    out["company_name"] = sample.get("name") or None

    if upcoming:
        rd = _parse_date(upcoming.get("reportDate"))
        if rd:
            out["upcoming_report_date"] = rd.isoformat()
            out["days_to_report"] = (rd - today).days
        out["fiscal_date_ending"] = upcoming.get("fiscalDateEnding") or None
        out["estimate_eps"] = _safe_float(upcoming.get("estimate"))
        out["currency"] = upcoming.get("currency") or None

    if previous:
        rd = _parse_date(previous.get("reportDate"))
        if rd:
            out["last_report_date"] = rd.isoformat()

    return out


async def _fetch_calendar_rows(
    *,
    api_key: str,
    horizon: str = "12month",
) -> tuple[dict[str, list[dict[str, str]]], str | None]:
    now = datetime.utcnow()
    if (
        _CALENDAR_CACHE.get("rows_by_symbol")
        and _CALENDAR_CACHE.get("expires_at")
        and now < _CALENDAR_CACHE["expires_at"]
    ):
        return _CALENDAR_CACHE["rows_by_symbol"], None

    params = {
        "function": "EARNINGS_CALENDAR",
        "horizon": horizon,
        "apikey": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.get(_BASE, params=params)
            r.raise_for_status()
            txt = r.text or ""
    except Exception as e:
        return {}, f"http: {e}"

    stripped = txt.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except Exception:
            payload = {}
        msg = (
            payload.get("Note")
            or payload.get("Information")
            or payload.get("Error Message")
            or "unexpected JSON response from EARNINGS_CALENDAR"
        )
        return {}, str(msg)[:240]

    rows_by_symbol = _parse_calendar_csv(txt)
    _CALENDAR_CACHE["rows_by_symbol"] = rows_by_symbol
    _CALENDAR_CACHE["expires_at"] = now + _CACHE_TTL
    return rows_by_symbol, None


async def fetch_many(symbols: list[str], *, api_key: str) -> dict[str, dict[str, Any]]:
    """Fetch earnings-calendar context for each symbol."""
    if not api_key:
        return {}

    syms = sorted({(s or "").upper().strip() for s in symbols if s and s.strip()})
    if not syms:
        return {}

    rows_by_symbol, err = await _fetch_calendar_rows(
        api_key=api_key,
        horizon="12month",
    )
    out: dict[str, dict[str, Any]] = {}
    for sym in syms:
        payload = _build_symbol_payload(sym, rows_by_symbol.get(sym) or [])
        if err and len(payload.keys()) <= 1:
            payload["error"] = err
        out[sym] = payload
    return out


def brief_line(payload: dict[str, Any]) -> str:
    """One-line summary for a prompt/context. Empty string if nothing usable."""
    bits: list[str] = []
    up = payload.get("upcoming_report_date")
    days = payload.get("days_to_report")
    est = payload.get("estimate_eps")
    if up:
        if isinstance(days, int):
            bits.append(f"next earnings {up} ({days}d)")
        else:
            bits.append(f"next earnings {up}")
        if est is not None:
            try:
                bits.append(f"est EPS {float(est):.2f}")
            except Exception:
                bits.append(f"est EPS {est}")

    last = payload.get("last_report_date")
    if last:
        bits.append(f"last report {last}")

    if not bits and payload.get("error"):
        bits.append(f"error: {str(payload.get('error'))[:80]}")

    return " | ".join(bits)
