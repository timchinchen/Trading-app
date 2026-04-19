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

from . import stockanalysis, tradingview

LogFn = Callable[[str], None]


@dataclass
class MarketIntel:
    gainers: list[dict[str, Any]] = field(default_factory=list)
    losers: list[dict[str, Any]] = field(default_factory=list)
    active: list[dict[str, Any]] = field(default_factory=list)
    screener: list[dict[str, Any]] = field(default_factory=list)
    headlines: list[dict[str, Any]] = field(default_factory=list)
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

        if self.errors:
            lines.append(
                "(sources unavailable: " + ", ".join(self.errors.keys()) + ")"
            )

        return "\n".join(lines) or "(no market-intel data)"


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
