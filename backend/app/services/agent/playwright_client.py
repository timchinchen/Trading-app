"""Playwright-based X/Twitter timeline scraper.

Authentication sources (pick one):

1. **Default:** twscrape SQLite (`TWSCRAPE_DB`) — `auth_token` + `ct0` injected into Chromium.
2. **Optional:** `PLAYWRIGHT_STORAGE_STATE_PATH` — Playwright `storage_state` JSON from a real
   browser login (skips twscrape cookie injection).

Public entry point: `fetch_recent_tweets(...)` — matches `twitter_client.fetch_recent_tweets`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ...config import settings

LogFn = Callable[[str], None]


class PlaywrightNotInstalledError(RuntimeError):
    """Raised when the playwright package or chromium binary is missing."""


class CookiesMissingError(RuntimeError):
    """Raised when we can't find auth cookies or storage_state for X."""


def _log(log: Optional[LogFn], msg: str):
    if log:
        try:
            log(msg)
        except Exception:
            pass
    else:
        print(f"[pw-tw] {msg}")


def _log_twscrape_accounts_overview(db_path: str, log: Optional[LogFn]) -> None:
    """Log twscrape DB path + account rows (never cookie secrets)."""
    ap = os.path.abspath(db_path)
    exists = os.path.isfile(ap)
    _log(log, f"twscrape db resolved path={ap} exists={exists}")
    if not exists:
        _log(log, "twscrape db file missing — run `python -m app.services.agent.setup add_cookies`")
        return
    conn = sqlite3.connect(db_path)
    try:
        try:
            rows = conn.execute(
                "SELECT username, active, cookies FROM accounts ORDER BY active DESC, username"
            ).fetchall()
        except sqlite3.OperationalError as e:
            _log(log, f"twscrape accounts query failed: {e}")
            return
    finally:
        conn.close()

    if not rows:
        _log(log, "twscrape accounts table: (no rows) — run add_cookies")
        return

    n_active = sum(1 for r in rows if r[1])
    _log(log, f"twscrape accounts: {len(rows)} row(s), active_count={n_active}")
    if n_active > 1:
        _log(
            log,
            "WARNING twscrape has multiple active=1 accounts; cookie load uses "
            "`WHERE active=1 LIMIT 1` (SQLite picks an arbitrary row). Deactivate extras.",
        )

    for username, is_active, cookies_raw in rows:
        blob_len = len(cookies_raw or "")
        hint = ""
        raw = cookies_raw
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as e:
                hint = f" cookies_json_invalid={e}"
            else:
                if isinstance(parsed, dict):
                    keys = sorted(parsed.keys())
                    at = parsed.get("auth_token")
                    ct = parsed.get("ct0")
                    at_l = len(str(at)) if at is not None else 0
                    ct_l = len(str(ct)) if ct is not None else 0
                    hint = (
                        f" keys={keys} auth_token_present={bool(at)} len={at_l} "
                        f"ct0_present={bool(ct)} len={ct_l}"
                    )
                else:
                    hint = f" cookies_json_type={type(parsed).__name__}"
        _log(
            log,
            f"  user={username!r} active={bool(is_active)} cookie_blob_chars={blob_len}{hint}",
        )


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


def _resolve_auth_payload(db_path: str, log: Optional[LogFn]) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Return (storage_state_path_or_None, playwright_cookie_list).

    When PLAYWRIGHT_STORAGE_STATE_PATH points at an existing file, twscrape cookies are skipped.
    """
    ss_raw = (settings.PLAYWRIGHT_STORAGE_STATE_PATH or "").strip()
    if ss_raw:
        ap = os.path.abspath(ss_raw)
        if not os.path.isfile(ap):
            raise CookiesMissingError(
                f"PLAYWRIGHT_STORAGE_STATE_PATH file not found: {ap}. "
                "Unset it or create the JSON (see docs/X_TWITTER_PLAYWRIGHT.md)."
            )
        _log(log, f"playwright: auth mode=storage_state path={ap}")
        return ap, []

    _log_twscrape_accounts_overview(db_path, log)
    cookies = _load_cookies(db_path)
    _log(
        log,
        f"playwright: auth mode=twscrape_sqlite expanded {len(cookies)} cookie entries "
        "(auth_token+ct0 × x.com/twitter.com domains)",
    )
    return None, cookies


def _playwright_user_agent() -> str:
    custom = (settings.PLAYWRIGHT_USER_AGENT or "").strip()
    if custom:
        return custom
    if sys.platform == "darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chromium/131.0.0.0 Safari/537.36"
    )


def _resolved_per_account_timeout_s(raw: int) -> int:
    """X.com navigation + hydration routinely exceeds very tight budgets."""
    t = int(raw or 0)
    if t < 30:
        return 45
    return t


def _navigation_timeout_ms(per_account_timeout_s: int, *, relaxed: bool) -> int:
    """page.goto budget; must stay below asyncio.wait_for(per_account_s)."""
    pat = _resolved_per_account_timeout_s(per_account_timeout_s)
    reserve = 18_000 if relaxed else 12_000
    lo = 58_000 if relaxed else 40_000
    hi = 120_000 if relaxed else 110_000
    return max(lo, min(hi, pat * 1000 - reserve))


@dataclass
class _FetchConfig:
    lookback_hours: int
    max_per_account: int
    per_account_timeout_s: int
    navigation_timeout_ms: int
    relaxed: bool = False
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
            if t in ("image", "font"):
                await r.abort()
            else:
                await r.continue_()
        except Exception:
            pass

    # Relaxed backup pass does not throttle resources — fewer brittle hangs on Pi / slow shells.
    if not cfg.relaxed:
        await page.route("**/*", _route)

    hydrate_ms = 7000 if cfg.relaxed else 4000
    tweet_sel_timeout_ms = 25_000 if cfg.relaxed else 18_000

    try:
        async def _goto_profile() -> tuple[str, int | None]:
            """Try progressively heavier wait_until hooks."""
            modes: tuple[str, ...]
            if cfg.relaxed:
                modes = ("commit", "domcontentloaded", "load")
            else:
                modes = ("commit", "domcontentloaded")

            last_err: BaseException | None = None
            for mode in modes:
                try:
                    resp = await page.goto(
                        url,
                        wait_until=mode,  # type: ignore[arg-type]
                        timeout=cfg.navigation_timeout_ms,
                    )
                    status = int(resp.status) if resp is not None else None
                    _log(
                        log,
                        f"  @{handle}: navigation ok wait_until={mode} http_status={status}",
                    )
                    return mode, status
                except BaseException as e:
                    last_err = e
                    _log(
                        log,
                        f"  @{handle}: navigation failed wait_until={mode}: "
                        f"{type(e).__name__}: {e}",
                    )
            assert last_err is not None
            raise last_err

        async def _log_page_identity(stage: str) -> None:
            try:
                cur = page.url
                title = await page.title()
                tclip = (title or "")[:160].replace("\n", " ")
                _log(log, f"  @{handle}: {stage} url={cur!r} title={tclip!r}")
            except Exception as e:
                _log(log, f"  @{handle}: {stage} page identity read failed: {e!r}")

        async def _log_timeline_probe(reason: str) -> None:
            """Best-effort DOM hints for auth / outage / empty timeline (no secrets)."""
            try:
                probe = await page.evaluate(
                    """() => {
                      const b = document.body;
                      const t = b ? b.innerText : '';
                      const low = t.slice(0, 6000).toLowerCase();
                      return {
                        body_chars: t.length,
                        sign_in_link: !!document.querySelector('a[href*="flow/login"]'),
                        log_in_text: low.includes('log in') && low.includes('sign up'),
                        wrong: low.includes('something went wrong'),
                        suspended: low.includes('suspended'),
                        unavailable: low.includes('this account') && low.includes('unavailable'),
                        unusual: low.includes('unusual') || low.includes('automated'),
                        captcha: low.includes('captcha'),
                        retry: low.includes('try again'),
                      };
                    }"""
                )
                _log(log, f"  @{handle}: timeline_probe ({reason}) -> {probe}")
            except Exception as e:
                _log(log, f"  @{handle}: timeline_probe failed: {e!r}")

        async def _do_fetch():
            await _goto_profile()
            await page.wait_for_timeout(hydrate_ms)
            await _log_page_identity("after_hydrate_wait")

            try:
                await page.wait_for_selector(
                    "article[data-testid='tweet']", timeout=tweet_sel_timeout_ms
                )
            except Exception as e:
                _log(
                    log,
                    f"  @{handle}: no tweet articles in DOM within {tweet_sel_timeout_ms / 1000:.0f}s "
                    f"({type(e).__name__}: {e})",
                )
                await _log_timeline_probe("no_tweet_selector")
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

            if not tweets:
                _log(
                    log,
                    f"  @{handle}: timeline loaded but collected 0 tweets in-window "
                    f"(lookback={cfg.lookback_hours}h, max={cfg.max_per_account})",
                )
                await _log_timeline_probe("zero_tweets_collected")

        await asyncio.wait_for(_do_fetch(), timeout=cfg.per_account_timeout_s)
    except asyncio.TimeoutError:
        _log(log, f"TIMEOUT @{handle} after {cfg.per_account_timeout_s}s")
        try:
            _log(log, f"  @{handle}: url at timeout={page.url!r}")
        except Exception:
            pass
    except Exception as e:
        _log(log, f"fetch error @{handle}: {e}")
        try:
            _log(log, f"  @{handle}: url at error={page.url!r}")
        except Exception:
            pass
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return list(tweets.values())[: cfg.max_per_account]


async def _single_playwright_session(
    *,
    handles: list[str],
    lookback_hours: int,
    max_per_account: int,
    per_account_timeout_s: int,
    log: Optional[LogFn],
    headless: bool,
    relaxed_navigation: bool,
    cookies: list[dict[str, Any]],
    storage_state_path: Optional[str],
) -> list[dict[str, Any]]:
    """One browser lifecycle: launch → context → scrape each handle."""
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        raise PlaywrightNotInstalledError(
            f"playwright not installed: {e}. Run `pip install playwright && playwright install chromium`."
        )

    pat = _resolved_per_account_timeout_s(per_account_timeout_s)
    nav_ms = _navigation_timeout_ms(pat, relaxed=relaxed_navigation)
    mode_label = "relaxed_backup" if relaxed_navigation else "primary"

    _log(log, f"playwright: session mode={mode_label} relaxed={relaxed_navigation}")
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
        relaxed=relaxed_navigation,
        headless=headless,
    )

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    _log(log, f"cutoff = {cutoff.isoformat()} (looking back {lookback_hours}h)")

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]
    if settings.PLAYWRIGHT_DISABLE_GPU:
        launch_args.append("--disable-gpu")

    exe = (settings.PLAYWRIGHT_CHROMIUM_EXECUTABLE or "").strip()
    _log(
        log,
        "playwright: launch chromium_executable="
        f"{exe if exe else '(playwright bundled)'} disable_gpu={settings.PLAYWRIGHT_DISABLE_GPU}",
    )

    launch_kw: dict[str, Any] = {"headless": headless, "args": launch_args}
    if exe:
        launch_kw["executable_path"] = exe

    out: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(**launch_kw)
        except Exception as e:
            raise PlaywrightNotInstalledError(
                f"failed to launch chromium: {e}. Run `playwright install chromium` "
                f"or set PLAYWRIGHT_CHROMIUM_EXECUTABLE to your system Chromium."
            )

        try:
            ctx_kw: dict[str, Any] = {
                "user_agent": _playwright_user_agent(),
                "viewport": {"width": 1280, "height": 1000},
                "locale": "en-US",
                "timezone_id": "Etc/UTC",
            }
            if storage_state_path:
                ctx_kw["storage_state"] = storage_state_path

            ctx = await browser.new_context(**ctx_kw)
            ctx.set_default_navigation_timeout(nav_ms)

            if not storage_state_path:
                await ctx.add_cookies(cookies)

            try:
                injected = await ctx.cookies()
                by_dom: dict[str, int] = {}
                for c in injected:
                    d = str(c.get("domain") or "")
                    by_dom[d] = by_dom.get(d, 0) + 1
                x_names = sorted(
                    {
                        str(c.get("name"))
                        for c in injected
                        if "x.com" in str(c.get("domain") or "")
                        or "twitter.com" in str(c.get("domain") or "")
                    }
                )
                has_at = "auth_token" in x_names
                has_ct0 = "ct0" in x_names
                _log(
                    log,
                    f"playwright: browser context holds {len(injected)} cookies "
                    f"by_domain={by_dom}",
                )
                _log(
                    log,
                    f"playwright: session jar auth_token={has_at} ct0={has_ct0} "
                    f"name_sample={x_names[:24]}",
                )
            except Exception as e:
                _log(log, f"playwright: cookie introspection failed: {e!r}")

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


async def fetch_recent_tweets(
    handles: list[str],
    lookback_hours: int,
    max_per_account: int,
    db_path: str,
    per_account_timeout_s: int = 45,
    log: Optional[LogFn] = None,
    headless: bool = True,
    relaxed_navigation: bool = False,
) -> list[dict[str, Any]]:
    """Fetch recent tweets per handle via Playwright.

    When ``PLAYWRIGHT_RELAXED_FALLBACK`` is True (default) and this call uses the primary
    scraper first (``relaxed_navigation=False``), an automatic second browser session runs
    with longer waits + ``load`` navigation if the first returns zero tweets.
    """
    ss_path, cookies = _resolve_auth_payload(db_path, log)

    out = await _single_playwright_session(
        handles=handles,
        lookback_hours=lookback_hours,
        max_per_account=max_per_account,
        per_account_timeout_s=per_account_timeout_s,
        log=log,
        headless=headless,
        relaxed_navigation=relaxed_navigation,
        cookies=cookies,
        storage_state_path=ss_path,
    )

    if (
        len(out) == 0
        and not relaxed_navigation
        and settings.PLAYWRIGHT_RELAXED_FALLBACK
        and handles
    ):
        _log(
            log,
            "playwright: primary session returned 0 tweets — starting RELAXED BACKUP session "
            "(longer waits, load-event navigation, no image/font blocking). "
            "Disable via PLAYWRIGHT_RELAXED_FALLBACK=false if undesired.",
        )
        out = await _single_playwright_session(
            handles=handles,
            lookback_hours=lookback_hours,
            max_per_account=max_per_account,
            per_account_timeout_s=per_account_timeout_s,
            log=log,
            headless=headless,
            relaxed_navigation=True,
            cookies=cookies,
            storage_state_path=ss_path,
        )

    return out
