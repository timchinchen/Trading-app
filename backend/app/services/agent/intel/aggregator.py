"""Aggregate market-intelligence sources into a single MarketIntel payload.

Exposes:
    MarketIntel - dataclass describing the merged state.
    collect_intel(log=?) - async function that fetches everything with graceful
        degradation and returns a MarketIntel.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import fmp, sec_edgar, stockanalysis, tradingview

LogFn = Callable[[str], None]


@dataclass
class MarketIntel:
    gainers: list[dict[str, Any]] = field(default_factory=list)
    losers: list[dict[str, Any]] = field(default_factory=list)
    active: list[dict[str, Any]] = field(default_factory=list)
    screener: list[dict[str, Any]] = field(default_factory=list)
    headlines: list[dict[str, Any]] = field(default_factory=list)
    # Per-ticker enrichment populated lazily when runner calls enrich_symbols().
    # Shape: {SYM: {"fmp": {...}, "sec": {...}}}
    enrichment: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def corroborating_symbols(self) -> set[str]:
        """Symbols that independently appear in movers/news lists."""
        out: set[str] = set()
        for row in self.gainers + self.active:
            if s := row.get("symbol"):
                out.add(s.upper())
        for item in self.headlines:
            for s in item.get("symbols") or []:
                out.add(s.upper())
        return out

    def symbols_to_avoid(self) -> set[str]:
        """Symbols we flag as bearish-contextual (big losers today)."""
        return {r["symbol"].upper() for r in self.losers if r.get("symbol")}

    def brief(self, max_items: int = 6) -> str:
        """Compact text representation for inclusion in LLM prompts."""
        lines: list[str] = []

        def _fmt_movers(rows: list[dict[str, Any]], label: str):
            if not rows:
                return
            bits = ", ".join(
                f"{r['symbol']} {r['pct_change']:+.1f}%"
                for r in rows[:max_items]
                if r.get("pct_change") is not None
            )
            if bits:
                lines.append(f"{label}: {bits}")

        _fmt_movers(self.gainers, "Top gainers")
        _fmt_movers(self.losers, "Top losers")
        _fmt_movers(self.active, "Most active")

        if self.headlines:
            lines.append("Headlines:")
            for h in self.headlines[:max_items]:
                syms = ",".join(h.get("symbols") or [])
                lines.append(f"  - [{syms}] {h.get('title','')[:110]}")

        if self.enrichment:
            lines.append("Per-ticker enrichment:")
            for sym, payload in self.enrichment.items():
                parts: list[str] = []
                fmp_line = fmp.brief_line(payload.get("fmp") or {})
                if fmp_line:
                    parts.append(f"FMP: {fmp_line}")
                sec_line = sec_edgar.brief_line(payload.get("sec") or {})
                if sec_line:
                    parts.append(f"SEC: {sec_line}")
                entity = (payload.get("sec") or {}).get("entity_name")
                if entity:
                    lines.append(f"  - {sym} ({entity}): " + " | ".join(parts))
                else:
                    lines.append(f"  - {sym}: " + " | ".join(parts))

        if self.errors:
            lines.append(
                "(sources unavailable: " + ", ".join(self.errors.keys()) + ")"
            )

        return "\n".join(lines) or "(no market-intel data)"

    async def enrich_symbols(
        self,
        symbols: list[str],
        *,
        fmp_api_key: str,
        fmp_base_url: str,
        sec_user_agent: str,
        log: Optional[LogFn] = None,
    ) -> None:
        """Pull FMP + SEC EDGAR data for a small list of tickers and stash it
        on `self.enrichment`. Idempotent - re-calling with new symbols only
        enriches the new ones. Best-effort; failures are tracked in `errors`."""
        syms = sorted({s.upper().strip() for s in symbols if s and s.strip()})
        if not syms:
            return

        def _log(msg: str):
            if log:
                try:
                    log(msg)
                except Exception:
                    pass

        # Parallel FMP + SEC
        fmp_task = asyncio.create_task(
            fmp.fetch_many(syms, api_key=fmp_api_key, base_url=fmp_base_url)
        )
        sec_task = asyncio.create_task(
            sec_edgar.fetch_many(syms, user_agent=sec_user_agent)
        )
        fmp_map = await fmp_task
        sec_map = await sec_task

        for sym in syms:
            slot = self.enrichment.setdefault(sym, {})
            if fmp_map.get(sym):
                slot["fmp"] = fmp_map[sym]
            if sec_map.get(sym):
                slot["sec"] = sec_map[sym]

        fmp_ok = sum(1 for s in syms if fmp_map.get(s) and not fmp_map[s].get("error"))
        sec_ok = sum(1 for s in syms if sec_map.get(s) and not sec_map[s].get("error"))
        _log(
            f"enrichment: fmp_ok={fmp_ok}/{len(syms)} sec_ok={sec_ok}/{len(syms)} "
            f"(symbols: {', '.join(syms)})"
        )
        if fmp_api_key == "":
            self.errors["fmp"] = "FMP_API_KEY not set"


async def collect_intel(log: Optional[LogFn] = None) -> MarketIntel:
    def _log(msg: str):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    _log("intel: fetching stockanalysis movers + screener + tradingview news ...")

    # Launch everything in parallel; each coroutine swallows its own errors
    # and always returns a dict.
    sa_task = asyncio.create_task(stockanalysis.fetch_all())
    tv_task = asyncio.create_task(tradingview.fetch_news(limit=20))

    sa = await sa_task
    tv = await tv_task

    mi = MarketIntel()
    mi.gainers = sa.get("gainers", {}).get("rows", []) or []
    mi.losers = sa.get("losers", {}).get("rows", []) or []
    mi.active = sa.get("active", {}).get("rows", []) or []
    mi.screener = sa.get("screener", {}).get("rows", []) or []
    mi.headlines = tv.get("items", []) or []

    for name, payload in sa.items():
        if payload and payload.get("error"):
            mi.errors[f"stockanalysis/{name}"] = payload["error"]
    if tv.get("error"):
        mi.errors["tradingview/news"] = tv["error"]

    _log(
        f"intel: gainers={len(mi.gainers)} losers={len(mi.losers)} "
        f"active={len(mi.active)} screener={len(mi.screener)} "
        f"headlines={len(mi.headlines)} errors={list(mi.errors.keys())}"
    )
    return mi
