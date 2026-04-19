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

from . import fmp, sec_edgar, stockanalysis, stocktwits, tradingview

LogFn = Callable[[str], None]


@dataclass
class MarketIntel:
    gainers: list[dict[str, Any]] = field(default_factory=list)
    losers: list[dict[str, Any]] = field(default_factory=list)
    active: list[dict[str, Any]] = field(default_factory=list)
    screener: list[dict[str, Any]] = field(default_factory=list)
    headlines: list[dict[str, Any]] = field(default_factory=list)
    # Per-ticker enrichment populated lazily when runner calls enrich_symbols().
    # Shape: {SYM: {"fmp": {...}, "sec": {...}, "stocktwits": {...}}}
    enrichment: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Stocktwits-wide news headlines (not per-symbol). Merged in alongside
    # tradingview headlines for advisor context.
    stocktwits_news: list[dict[str, Any]] = field(default_factory=list)
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
        for item in self.stocktwits_news:
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

        if self.stocktwits_news:
            lines.append("Stocktwits news:")
            for h in self.stocktwits_news[:max_items]:
                lines.append("  - " + stocktwits.brief_news_line(h))

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
                st_line = stocktwits.brief_line(sym, payload.get("stocktwits") or {})
                if st_line:
                    parts.append(f"ST: {st_line}")
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
        stocktwits_cookies: str = "",
        log: Optional[LogFn] = None,
    ) -> None:
        """Pull FMP + SEC EDGAR + Stocktwits data for a small list of tickers
        and stash it on `self.enrichment`. Idempotent - re-calling with new
        symbols only enriches the new ones. Best-effort; failures are
        tracked in `errors`."""
        syms = sorted({s.upper().strip() for s in symbols if s and s.strip()})
        if not syms:
            return

        def _log(msg: str):
            if log:
                try:
                    log(msg)
                except Exception:
                    pass

        # Parallel FMP + SEC + Stocktwits
        fmp_task = asyncio.create_task(
            fmp.fetch_many(syms, api_key=fmp_api_key, base_url=fmp_base_url)
        )
        sec_task = asyncio.create_task(
            sec_edgar.fetch_many(syms, user_agent=sec_user_agent)
        )
        if stocktwits_cookies:
            st_task = asyncio.create_task(
                stocktwits.fetch_all(syms, stocktwits_cookies, log=log)
            )
        else:
            st_task = None

        fmp_map = await fmp_task
        sec_map = await sec_task
        st_result = await st_task if st_task else None

        for sym in syms:
            slot = self.enrichment.setdefault(sym, {})
            if fmp_map.get(sym):
                slot["fmp"] = fmp_map[sym]
            if sec_map.get(sym):
                slot["sec"] = sec_map[sym]
            if st_result and st_result.sentiment.get(sym):
                slot["stocktwits"] = st_result.sentiment[sym]

        if st_result:
            # Merge any news headlines from stocktwits into the top-level list.
            if st_result.news:
                self.stocktwits_news.extend(st_result.news)
            for k, v in st_result.errors.items():
                self.errors[k] = v

        fmp_ok = sum(1 for s in syms if fmp_map.get(s) and not fmp_map[s].get("error"))
        sec_ok = sum(1 for s in syms if sec_map.get(s) and not sec_map[s].get("error"))
        st_ok = (
            sum(
                1
                for s in syms
                if st_result
                and st_result.sentiment.get(s)
                and not st_result.sentiment[s].get("error")
            )
            if st_result
            else 0
        )
        _log(
            f"enrichment: fmp_ok={fmp_ok}/{len(syms)} sec_ok={sec_ok}/{len(syms)} "
            f"stocktwits_ok={st_ok}/{len(syms)} news={len(st_result.news) if st_result else 0} "
            f"(symbols: {', '.join(syms)})"
        )
        if fmp_api_key == "":
            self.errors["fmp"] = "FMP_API_KEY not set"
        if not stocktwits_cookies:
            self.errors["stocktwits"] = "STOCKTWITS_COOKIES not set"


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
