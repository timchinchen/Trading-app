"""Playwright-based X/Twitter timeline scraper.

Uses the auth cookies already registered with twscrape (`auth_token` + `ct0`)
to load the logged-in timeline for each handle via headless Chromium. This
sidesteps the twscrape 0.17.0 parsing failures that trigger 15-minute account
locks on every request, and also avoids the aggressive IP rate limits on the
public syndication endpoints.

Public entry point: `fetch_recent_tweets(...)` - matches the signature of
`twitter_client.fetch_recent_tweets` so the runner can drop it in.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

LogFn = Callable[[str], None]


class PlaywrightNotInstalledError(RuntimeError):
    """Raised when the playwright package or chromium binary is missing."""


class CookiesMissingError(RuntimeError):
    """Raised when we can't find auth cookies in the twscrape db."""


def _log(log: Optional[LogFn], msg: str):
    if log:
        try:
            log(msg)
        except Exception:
            pass
    else:
        print(f"[pw-tw] {msg}")


def _load_cookies(db_path: str) -> list[dict[str, Any]]:
    """Pull auth_token + ct0 from twscrape sqlite and expand to Playwright cookies."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT cookies FROM accounts WHERE active=1 LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError as e:
        raise CookiesMissingError(f"twscrape db at {db_path} not initialized: {e}")
    finally:
        conn.close()

    if not row or not row[0]:
        raise CookiesMissingError(
            f"no active account with cookies in {db_path} - run setup add_cookies"
        )
    raw = json.loads(row[0])
    out: list[dict[str, Any]] = []
    for name, value in raw.items():
        for domain in (".x.com", ".twitter.com"):
            out.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "httpOnly": name == "auth_token",
                "secure": True,
                "sameSite": "Lax",
            })
    return out


def _resolved_per_account_timeout_s(raw: int) -> int:
    """X.com navigation + hydration routinely exceeds very tight budgets."""
    t = int(raw or 0)
    if t < 30:
        return 45
    return t


def _navigation_timeout_ms(per_account_s: int) -> int:
    """page.goto budget; must stay below asyncio.wait_for(per_account_s)."""
    pat = _resolved_per_account_timeout_s(per_account_s)
    # Leave ~12s for post-goto waits (hydrate + tweet selector + scroll loop).
    return max(40_000, min(110_000, pat * 1000 - 12_000))


@dataclass
class _FetchConfig:
    lookback_hours: int
    max_per_account: int
    per_account_timeout_s: int
    navigation_timeout_ms: int
    headless: bool = True


async def _fetch_handle(
    ctx,
    handle: str,
    cfg: _FetchConfig,
    log: Optional[LogFn],
) -> list[dict[str, Any]]:
    """Scrape one handle's public timeline using an already-authenticated context."""
    url = f"https://x.com/{handle}"
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=cfg.lookback_hours)
    tweets: dict[str, dict[str, Any]] = {}

    page = await ctx.new_page()

    async def _route(r):
        try:
            t = r.request.resource_type
            # Do not block "media" — X sometimes classifies XHR/fetch oddly; blocking media
            # has been linked to hung navigations in headless profiles.
            if t in ("image", "font"):
                await r.abort()
            else:
                await r.continue_()
        except Exception:
            pass

    await page.route("**/*", _route)

    try:
        async def _goto_profile() -> None:
            """X often never reaches domcontentloaded in headless; try commit first."""
            last_err: BaseException | None = None
            for mode in ("commit", "domcontentloaded"):
                try:
                    await page.goto(
                        url,
                        wait_until=mode,  # type: ignore[arg-type]
                        timeout=cfg.navigation_timeout_ms,
                    )
                    return
                except BaseException as e:
                    last_err = e
            assert last_err is not None
            raise last_err

        async def _do_fetch():
            await _goto_profile()
            # Let React hydrate + timeline request fire.
            await page.wait_for_timeout(4000)

            try:
                await page.wait_for_selector(
                    "article[data-testid='tweet']", timeout=18_000
                )
            except Exception:
                # Page rendered but no tweets (private / suspended / empty)
                return

            max_scrolls = 8
            for _ in range(max_scrolls):
                arts = await page.query_selector_all("article[data-testid='tweet']")
                saw_old = False

                for art in arts:
                    try:
                        time_el = await art.query_selector("a[href*='/status/'] time")
                        if not time_el:
                            continue
                        dt_str = await time_el.get_attribute("datetime")
                        if not dt_str:
                            continue
                        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

                        a_el = await time_el.evaluate_handle(
                            "el => el.closest('a')"
                        )
                        href_prop = await a_el.get_property("href")
                        href = await href_prop.json_value()
                        m = re.search(r"/([^/]+)/status/(\d+)", href or "")
                        if not m:
                            continue
                        tweet_author, tid = m.group(1), m.group(2)
                        # Skip retweets (author path != current handle).
                        if tweet_author.lower() != handle.lower():
                            continue
                        if tid in tweets:
                            continue
                        if dt < cutoff:
                            saw_old = True
                            continue

                        text_el = await art.query_selector(
                            "div[data-testid='tweetText']"
                        )
                        text = ""
                        if text_el:
                            text = await text_el.inner_text()

                        tweets[tid] = {
                            "handle": handle,
                            "tweet_id": tid,
                            "url": href,
                            "text": text or "",
                            "created_at": dt.isoformat(),
                        }
                    except Exception:
                        continue

                if len(tweets) >= cfg.max_per_account or saw_old:
                    break
                await page.mouse.wheel(0, 2800)
                await page.wait_for_timeout(700)

        await asyncio.wait_for(_do_fetch(), timeout=cfg.per_account_timeout_s)
    except asyncio.TimeoutError:
        _log(log, f"TIMEOUT @{handle} after {cfg.per_account_timeout_s}s")
    except Exception as e:
        _log(log, f"fetch error @{handle}: {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return list(tweets.values())[: cfg.max_per_account]


async def fetch_recent_tweets(
    handles: list[str],
    lookback_hours: int,
    max_per_account: int,
    db_path: str,
    per_account_timeout_s: int = 45,
    log: Optional[LogFn] = None,
    headless: bool = True,
) -> list[dict[str, Any]]:
    """Fetch recent tweets for each handle via headless Chromium + twscrape cookies.

    Reuses a single browser context so cookies stay hot across handles.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        raise PlaywrightNotInstalledError(
            f"playwright not installed: {e}. Run `pip install playwright && playwright install chromium`."
        )

    cookies = _load_cookies(db_path)
    _log(log, f"playwright: loaded {len(cookies)} cookies from twscrape db")

    pat = _resolved_per_account_timeout_s(per_account_timeout_s)
    nav_ms = _navigation_timeout_ms(pat)
    if int(per_account_timeout_s or 0) < 30:
        _log(
            log,
            f"playwright: per-account timeout was {int(per_account_timeout_s or 0)}s; "
            f"raised to {pat}s minimum for X reliability",
        )
    _log(
        log,
        f"playwright: outer deadline {pat}s per handle, navigation timeout {nav_ms / 1000:.0f}s",
    )

    cfg = _FetchConfig(
        lookback_hours=lookback_hours,
        max_per_account=max_per_account,
        per_account_timeout_s=pat,
        navigation_timeout_ms=nav_ms,
        headless=headless,
    )
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    _log(log, f"cutoff = {cutoff.isoformat()} (looking back {lookback_hours}h)")

    out: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    # Common in containers / low-memory hosts where Chromium can hang on /dev/shm.
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
        except Exception as e:
            raise PlaywrightNotInstalledError(
                f"failed to launch chromium: {e}. Run `playwright install chromium`."
            )

        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 1000},
                locale="en-US",
                timezone_id="Etc/UTC",
            )
            ctx.set_default_navigation_timeout(nav_ms)
            await ctx.add_cookies(cookies)

            for idx, h in enumerate(handles, start=1):
                h_clean = h.strip().lstrip("@").lower()
                if not h_clean:
                    continue
                _log(log, f"[{idx}/{len(handles)}] @{h_clean} ...")
                tweets = await _fetch_handle(ctx, h_clean, cfg, log)
                out.extend(tweets)
                _log(
                    log,
                    f"  @{h_clean}: +{len(tweets)} tweets (running total {len(out)})",
                )
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    return out
