"""Stocktwits scraper — sentiment + news headlines via Playwright + user cookies.

Stocktwits wraps all `/sentiment` and `/news-articles` pages (plus their
`api.stocktwits.com` host) behind Cloudflare's managed challenge, so every
plain-HTTP request gets back a 403. The same pattern that unblocked us on X
works here: drive a headless Chromium session seeded with the user's own
session cookies (copied out of their logged-in browser).

Public entry points:
    parse_cookie_blob(blob)   -> list[playwright cookie dicts]
    fetch_all(symbols, cookies, ...) -> _ScrapeResult(sentiment, news, watchers, errors)
    brief_line(sym, entry)    -> one-line string for per-symbol sentiment
    brief_news_line(item)     -> one-line string for a news article
    brief_watcher_line(item)  -> one-line string for a /sentiment/watchers row

Every function is best-effort: on any error (cookies missing, Cloudflare
still challenging, Playwright not installed, etc.) it returns an empty
payload rather than raising, so an agent run never breaks because of this
source. The caller can inspect the `errors` dict on MarketIntel to see why.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

LogFn = Callable[[str], None]

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

# Domains we want cookies attached to. Stocktwits spreads session across a few.
_COOKIE_DOMAINS = (".stocktwits.com", "stocktwits.com", ".api.stocktwits.com")


def _log(log: Optional[LogFn], msg: str):
    if log:
        try:
            log(msg)
        except Exception:
            pass
    else:
        print(f"[stocktwits] {msg}")


# --------------------------------------------------------------------------- #
# Cookie parsing
# --------------------------------------------------------------------------- #

def parse_cookie_blob(blob: str) -> list[dict[str, Any]]:
    """Accept either a JSON dict ({name: value, ...}), a JSON list of
    Playwright/Chrome cookie dicts, or a Netscape-style cookies.txt body.

    Always returns a list of Playwright-shaped cookie dicts, fanned out to
    all stocktwits.com domains so at least one binding lands during the
    Cloudflare bootstrap."""
    if not blob or not blob.strip():
        return []

    body = blob.strip()

    # 1) JSON dict {name: value}
    # 2) JSON list [{name, value, domain?}, ...]
    if body.startswith("{") or body.startswith("["):
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return _fanout_name_value(parsed)
        if isinstance(parsed, list):
            return _normalize_cookie_list(parsed)

    # 3) Netscape cookies.txt
    if "\t" in body:
        return _parse_netscape(body)

    # 4) Last resort: "name=value; name2=value2" single-line cookie string
    if "=" in body:
        pairs: dict[str, str] = {}
        for chunk in body.split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            k, v = chunk.split("=", 1)
            pairs[k.strip()] = v.strip()
        if pairs:
            return _fanout_name_value(pairs)

    return []


def _fanout_name_value(kv: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, value in kv.items():
        if not name or value is None:
            continue
        for domain in _COOKIE_DOMAINS:
            out.append({
                "name": str(name),
                "value": str(value),
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })
    return out


def _normalize_cookie_list(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        value = it.get("value")
        if not name or value is None:
            continue
        domain = it.get("domain") or ".stocktwits.com"
        path = it.get("path") or "/"
        entry = {
            "name": str(name),
            "value": str(value),
            "domain": domain,
            "path": path,
            "httpOnly": bool(it.get("httpOnly", False)),
            "secure": bool(it.get("secure", True)),
            "sameSite": it.get("sameSite") or "Lax",
        }
        out.append(entry)
        # Also fan out to sibling stocktwits domains so Cloudflare's WAF gets
        # the session on whichever host it decides to bounce through.
        if "stocktwits.com" in domain:
            for extra in _COOKIE_DOMAINS:
                if extra == domain:
                    continue
                dup = dict(entry)
                dup["domain"] = extra
                out.append(dup)
    return out


def _parse_netscape(body: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, _expires, name, value = parts[:7]
        out.append({
            "name": name,
            "value": value,
            "domain": domain if domain.startswith(".") else f".{domain}",
            "path": path or "/",
            "httpOnly": False,
            "secure": str(secure).upper() == "TRUE",
            "sameSite": "Lax",
        })
    return out


# --------------------------------------------------------------------------- #
# Playwright scraping
# --------------------------------------------------------------------------- #

@dataclass
class _ScrapeResult:
    sentiment: dict[str, dict[str, Any]]
    news: list[dict[str, Any]]
    watchers: list[dict[str, Any]]
    errors: dict[str, str]


async def _block_heavy(r):
    try:
        t = r.request.resource_type
        if t in ("image", "media", "font"):
            await r.abort()
        else:
            await r.continue_()
    except Exception:
        pass


async def _grab_sentiment_for_symbol(ctx, symbol: str, timeout_s: int, log: Optional[LogFn]) -> dict[str, Any]:
    """Scrape a single symbol's bull/bear percentage from its symbol page.

    Stocktwits renders the sentiment ratio on `/symbol/{SYM}` inside a
    data-testid="sentiment-*" block. We try a handful of selectors + also
    fall back to regex-ing any rendered 'X% Bullish' / 'X% Bearish' text
    so minor UI revamps don't kill us."""
    sym = symbol.upper().strip()
    url = f"https://stocktwits.com/symbol/{sym}"
    page = await ctx.new_page()
    await page.route("**/*", _block_heavy)
    out: dict[str, Any] = {"symbol": sym, "url": url}
    try:
        async def _do():
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            # Let client-side hydration finish.
            await page.wait_for_timeout(2500)
            html = await page.content()
            return html

        html = await asyncio.wait_for(_do(), timeout=timeout_s)
    except asyncio.TimeoutError:
        _log(log, f"sentiment TIMEOUT {sym} after {timeout_s}s")
        out["error"] = "timeout"
        try:
            await page.close()
        except Exception:
            pass
        return out
    except Exception as e:
        _log(log, f"sentiment error {sym}: {e}")
        out["error"] = str(e)[:200]
        try:
            await page.close()
        except Exception:
            pass
        return out
    finally:
        pass

    try:
        # Regex both "Bullish" and "Bearish" percentages from rendered HTML.
        # Matches things like "72% Bullish", "72%<...>Bullish", etc.
        bull = _find_pct(html, "Bullish")
        bear = _find_pct(html, "Bearish")
        if bull is not None:
            out["bull_pct"] = bull
        if bear is not None:
            out["bear_pct"] = bear
        if bull is None and bear is None:
            # Cloudflare or logged-out shell. Detect and annotate.
            if "Just a moment" in html or "cf-browser-verification" in html:
                out["error"] = "cloudflare_challenge"
            elif "Sign in" in html and "sentiment" not in html.lower():
                out["error"] = "not_logged_in"
            else:
                out["error"] = "no_sentiment_found"
        out["captured_at"] = datetime.now(tz=timezone.utc).isoformat()
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return out


def _find_pct(html: str, label: str) -> Optional[int]:
    """Extract the integer percentage immediately preceding (or following)
    the word Bullish/Bearish in the rendered HTML."""
    # "72% Bullish"
    m = re.search(rf"(\d{{1,3}})\s*%[^<]{{0,40}}{label}", html, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # "Bullish ... 72%"
    m = re.search(rf"{label}[^<]{{0,40}}?(\d{{1,3}})\s*%", html, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None


async def _grab_news_articles(ctx, limit: int, timeout_s: int, log: Optional[LogFn]) -> list[dict[str, Any]]:
    """Scrape the `/news-articles` feed for global headlines + ticker tags."""
    url = "https://stocktwits.com/news-articles"
    page = await ctx.new_page()
    await page.route("**/*", _block_heavy)
    try:
        async def _do():
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await page.wait_for_timeout(2500)

            # Scroll a couple of times to hydrate more items.
            for _ in range(3):
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(600)

            # Collect anchor nodes that look like article links.
            articles = await page.evaluate(
                """
                () => {
                  const out = [];
                  const seen = new Set();
                  // Articles tend to live inside <article> containers OR as
                  // <a> tags whose href contains "/news-articles/" or an
                  // external URL with a headline-like inner text.
                  const anchors = Array.from(document.querySelectorAll('a'));
                  for (const a of anchors) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim();
                    if (!href || !text || text.length < 20) continue;
                    if (seen.has(href)) continue;
                    const looksLikeNews = (
                      href.includes('/news-articles/') ||
                      href.match(/^https?:\\/\\//)
                    );
                    if (!looksLikeNews) continue;
                    // Ticker chips often share an ancestor; collect any
                    // sibling $TICKER tokens.
                    let container = a.closest('article') || a.parentElement;
                    let symbols = [];
                    if (container) {
                      const chips = container.querySelectorAll(
                        'a[href*="/symbol/"], span, div'
                      );
                      const found = new Set();
                      chips.forEach((c) => {
                        const t = (c.innerText || '').trim();
                        const m = t.match(/^\\$?([A-Z]{1,6})$/);
                        if (m) found.add(m[1]);
                        const h = c.getAttribute && c.getAttribute('href') || '';
                        const hm = h.match(/\\/symbol\\/([A-Z]{1,6})/);
                        if (hm) found.add(hm[1]);
                      });
                      symbols = Array.from(found);
                    }
                    // Try to find a timestamp in the container.
                    let published = null;
                    if (container) {
                      const t = container.querySelector('time');
                      if (t) {
                        published = t.getAttribute('datetime') || t.innerText;
                      }
                    }
                    seen.add(href);
                    out.push({
                      title: text.split('\\n')[0].slice(0, 220),
                      url: href,
                      symbols: symbols,
                      published_at: published,
                    });
                  }
                  return out;
                }
                """
            )
            return articles or []

        items = await asyncio.wait_for(_do(), timeout=timeout_s)
    except asyncio.TimeoutError:
        _log(log, f"news TIMEOUT after {timeout_s}s")
        items = []
    except Exception as e:
        _log(log, f"news error: {e}")
        items = []
    finally:
        try:
            await page.close()
        except Exception:
            pass

    # Normalize absolute URLs.
    cleaned: list[dict[str, Any]] = []
    for it in items:
        url_i = it.get("url") or ""
        if url_i.startswith("/"):
            url_i = f"https://stocktwits.com{url_i}"
        cleaned.append({
            "title": it.get("title") or "",
            "url": url_i,
            "symbols": [s.upper() for s in (it.get("symbols") or []) if s],
            "published_at": it.get("published_at"),
            "source": "stocktwits",
        })
    return cleaned[:limit]


async def _grab_watchers_leaderboard(
    ctx,
    limit: int,
    timeout_s: int,
    log: Optional[LogFn],
) -> list[dict[str, Any]]:
    """Scrape the /sentiment/watchers leaderboard — ranked list of the
    tickers with the most watchers on Stocktwits right now. Useful as a
    crowd-flow signal separate from per-symbol sentiment.

    Returns a list of {"rank","symbol","name","watchers","change_pct","url"}.
    Any row where we can't find a ticker symbol is dropped."""
    url = "https://stocktwits.com/sentiment/watchers"
    page = await ctx.new_page()
    await page.route("**/*", _block_heavy)
    try:
        async def _do():
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await page.wait_for_timeout(2500)

            # The leaderboard is rendered as a table/list of rows; scroll a
            # bit to trigger any virtualization hydration.
            for _ in range(2):
                await page.mouse.wheel(0, 1500)
                await page.wait_for_timeout(500)

            rows = await page.evaluate(
                """
                () => {
                  const out = [];
                  const seen = new Set();
                  // Prefer anchors into /symbol/<TICKER> - they're always
                  // present for every row on the leaderboard.
                  const anchors = Array.from(
                    document.querySelectorAll('a[href*="/symbol/"]')
                  );
                  for (const a of anchors) {
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/symbol\\/([A-Z.\\-]{1,10})/);
                    if (!m) continue;
                    const sym = m[1];
                    if (seen.has(sym)) continue;

                    // Row container: walk up until we find something that
                    // looks like a whole table row / list item.
                    let row = a.closest('tr, li, [role="row"]');
                    if (!row) row = a.parentElement;
                    if (!row) continue;

                    const text = (row.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (!text) continue;

                    // Pull the biggest integer on the row as the watcher
                    // count (Stocktwits renders "12,345" style counts).
                    let watchers = null;
                    const nums = (text.match(/\\b\\d[\\d,]*\\b/g) || [])
                      .map((x) => parseInt(x.replace(/,/g, ''), 10))
                      .filter((n) => !isNaN(n));
                    if (nums.length) watchers = Math.max(...nums);

                    // Extract a signed % change if present.
                    let change_pct = null;
                    const pm = text.match(/([+\\-]?\\d+(?:\\.\\d+)?)\\s*%/);
                    if (pm) {
                      const v = parseFloat(pm[1]);
                      if (!isNaN(v)) change_pct = v;
                    }

                    // Company name: grab the longest word-chunk on the row
                    // that isn't the ticker itself.
                    let name = '';
                    const chunks = text.split(/\\s{2,}|\\|/);
                    for (const c of chunks) {
                      const t = c.trim();
                      if (!t) continue;
                      if (t === sym) continue;
                      if (/^[\\d,+\\-.%$\\s]+$/.test(t)) continue;
                      if (t.length > name.length) name = t;
                    }

                    seen.add(sym);
                    out.push({
                      symbol: sym,
                      name: name.slice(0, 80),
                      watchers: watchers,
                      change_pct: change_pct,
                      url: 'https://stocktwits.com' + href,
                    });
                  }
                  return out;
                }
                """
            )
            return rows or []

        rows = await asyncio.wait_for(_do(), timeout=timeout_s)
    except asyncio.TimeoutError:
        _log(log, f"watchers TIMEOUT after {timeout_s}s")
        rows = []
    except Exception as e:
        _log(log, f"watchers error: {e}")
        rows = []
    finally:
        try:
            await page.close()
        except Exception:
            pass

    # Sort by watcher count desc and rank.
    rows = [r for r in rows if r.get("symbol")]
    rows.sort(key=lambda r: (r.get("watchers") or 0), reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows[:limit]


async def fetch_all(
    symbols: list[str],
    cookies_blob: str,
    *,
    news_limit: int = 20,
    watchers_limit: int = 25,
    per_request_timeout_s: int = 30,
    log: Optional[LogFn] = None,
    headless: bool = True,
) -> _ScrapeResult:
    """Launch one Chromium context, pull sentiment for each symbol plus the
    news-articles feed in parallel, and return a structured result.

    Any failure (cookies missing, Playwright not installed, Cloudflare wins)
    is reflected in `errors` instead of raised."""
    errors: dict[str, str] = {}
    sentiment: dict[str, dict[str, Any]] = {}
    news: list[dict[str, Any]] = []
    watchers: list[dict[str, Any]] = []

    if not cookies_blob or not cookies_blob.strip():
        errors["stocktwits"] = "cookies_not_configured"
        return _ScrapeResult(sentiment=sentiment, news=news, watchers=watchers, errors=errors)

    cookies = parse_cookie_blob(cookies_blob)
    if not cookies:
        errors["stocktwits"] = "cookies_unparseable"
        return _ScrapeResult(sentiment=sentiment, news=news, watchers=watchers, errors=errors)

    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        errors["stocktwits"] = f"playwright_missing: {e}"
        return _ScrapeResult(sentiment=sentiment, news=news, watchers=watchers, errors=errors)

    _log(log, f"launching chromium with {len(cookies)} cookies; symbols={symbols} news_limit={news_limit}")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=headless)
        except Exception as e:
            errors["stocktwits"] = f"chromium_launch_failed: {e}"
            return _ScrapeResult(sentiment=sentiment, news=news, watchers=watchers, errors=errors)

        try:
            ctx = await browser.new_context(
                user_agent=_UA,
                viewport={"width": 1280, "height": 1000},
                locale="en-US",
            )
            try:
                await ctx.add_cookies(cookies)
            except Exception as e:
                errors["stocktwits"] = f"cookie_inject_failed: {e}"
                return _ScrapeResult(sentiment=sentiment, news=news, watchers=watchers, errors=errors)

            syms_clean = [s.upper().strip() for s in (symbols or []) if s and s.strip()]

            # Run news + watchers leaderboard + per-symbol sentiment in parallel.
            news_task = asyncio.create_task(
                _grab_news_articles(ctx, news_limit, per_request_timeout_s, log)
            )
            watchers_task = asyncio.create_task(
                _grab_watchers_leaderboard(ctx, watchers_limit, per_request_timeout_s, log)
            )
            sent_tasks = [
                asyncio.create_task(
                    _grab_sentiment_for_symbol(ctx, s, per_request_timeout_s, log)
                )
                for s in syms_clean
            ]
            results = await asyncio.gather(*sent_tasks, return_exceptions=True)
            news = await news_task
            watchers = await watchers_task

            for res in results:
                if isinstance(res, Exception):
                    continue
                if not res or not res.get("symbol"):
                    continue
                sentiment[res["symbol"]] = res
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    return _ScrapeResult(sentiment=sentiment, news=news, watchers=watchers, errors=errors)


# --------------------------------------------------------------------------- #
# Prompt rendering helpers
# --------------------------------------------------------------------------- #

def brief_line(sym: str, entry: dict[str, Any]) -> str:
    """One-line summary for per-symbol sentiment. Empty if no data."""
    bull = entry.get("bull_pct")
    bear = entry.get("bear_pct")
    bits: list[str] = []
    if bull is not None:
        bits.append(f"{bull}% bull")
    if bear is not None:
        bits.append(f"{bear}% bear")
    if not bits:
        err = entry.get("error")
        if err:
            return f"(no sentiment: {err})"
        return ""
    return " · ".join(bits)


def brief_news_line(item: dict[str, Any]) -> str:
    syms = ",".join(item.get("symbols") or [])
    title = (item.get("title") or "").strip()
    if syms:
        return f"[{syms}] {title[:110]}"
    return title[:110]


def brief_watcher_line(item: dict[str, Any]) -> str:
    sym = item.get("symbol") or "?"
    rank = item.get("rank")
    watchers = item.get("watchers")
    chg = item.get("change_pct")
    bits: list[str] = []
    if rank is not None:
        bits.append(f"#{rank}")
    bits.append(sym)
    if watchers:
        bits.append(f"{watchers:,} watchers")
    if chg is not None:
        bits.append(f"{chg:+.2f}%")
    return " ".join(bits)
