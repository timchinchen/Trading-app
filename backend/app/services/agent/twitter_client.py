"""Thin async wrapper around twscrape with a persistent handle->user_id cache.

twscrape needs a logged-in (or cookies-authed) throwaway X account, registered via:

    .venv/bin/python -m app.services.agent.setup add_cookies

The account + cookies live in the sqlite file at settings.TWSCRAPE_DB.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ...db import SessionLocal
from ...models import TwitterUserCache


# ---------------------------------------------------------------------------
# twscrape 0.17.0 compatibility patches for X's evolving web bundle.
#
# Two independent failure modes show up as
#   "Unknown error. Account timeouted for 15 minutes ... Err: ..."
#   followed by "No account available for queue <X>, next available at <t+15m>"
# in the backend log, which wedges the runner because the account self-locks.
#
# 1. `xclid.get_scripts_list` splits X's bundle loader JSON. Since Dec 2025 X
#    emits unquoted object keys (malformed JSON per spec). We re-quote them so
#    `json.loads` succeeds.
#    See: https://github.com/vladkens/twscrape/issues/280
#
# 2. `xclid.XClIdGen.create` walks the HTML of `https://x.com/tesla` to build
#    the `x-client-transaction-id` header. When X rewrites the surrounding HTML
#    twscrape raises `IndexError: list index out of range` (e.g. in
#    `parse_anim_arr`). In that case we let the request proceed *without* the
#    header: public GraphQL read queries still work, and we avoid burning an
#    account on a 15-minute lock.
# ---------------------------------------------------------------------------

def _install_twscrape_patches():
    try:
        from twscrape import xclid
        from twscrape import queue_client
    except Exception:
        return

    if getattr(xclid, "__trading_app_patched__", False):
        return

    # Patch 1: robust script-list parser.
    _orig_script_url = xclid.script_url

    def _patched_get_scripts_list(text: str):
        scripts = text.split('e=>e+"."+')[1].split('[e]+"a.js"')[0]
        try:
            data = json.loads(scripts)
        except json.decoder.JSONDecodeError:
            # Quote bare identifier keys: `foo_bar:` or `{foo:` -> `"foo":`.
            fixed = re.sub(
                r'([{,]\s*)([a-zA-Z_$][a-zA-Z0-9_$]*)\s*:',
                r'\1"\2":',
                scripts,
            )
            try:
                data = json.loads(fixed)
            except json.decoder.JSONDecodeError as e:
                raise Exception("Failed to parse scripts") from e
        for k, v in data.items():
            yield _orig_script_url(k, f"{v}a")

    xclid.get_scripts_list = _patched_get_scripts_list

    # Patch 2: swallow IndexError / parse errors in XClIdGen so the request
    # falls through without the optional `x-client-transaction-id` header.
    _orig_store_get = queue_client.XClIdGenStore.get

    class _NullClid:
        def calc(self, method: str, path: str) -> str:
            return ""

    @classmethod
    async def _patched_store_get(cls, username: str, fresh: bool = False):
        try:
            return await _orig_store_get.__func__(cls, username, fresh)
        except Exception:
            # Cache the null gen so we don't keep retrying every call.
            cls.items[username] = _NullClid()  # type: ignore[assignment]
            return cls.items[username]

    queue_client.XClIdGenStore.get = _patched_store_get

    xclid.__trading_app_patched__ = True


_install_twscrape_patches()


# In-memory mirror of the cache, populated per-process for speed.
_MEM_CACHE: dict[str, str | None] = {}
NOT_FOUND_REFRESH_DAYS = 30

LogFn = Callable[[str], None]


class TwitterPoolExhaustedError(RuntimeError):
    """Raised when twscrape has no usable accounts (locked/logged-out/missing)."""


def _log(log: Optional[LogFn], msg: str):
    if log:
        try:
            log(msg)
        except Exception:
            pass
    else:
        print(f"[twitter] {msg}")


def _load_cached(handle: str) -> tuple[bool, str | None]:
    """Returns (is_cached, user_id_or_none). user_id=None means 'known not-found'."""
    if handle in _MEM_CACHE:
        return True, _MEM_CACHE[handle]
    db = SessionLocal()
    try:
        row = db.query(TwitterUserCache).filter(TwitterUserCache.handle == handle).first()
        if not row:
            return False, None
        if row.not_found:
            # refresh monthly - the handle may have been (re)created
            if (datetime.utcnow() - row.resolved_at).days > NOT_FOUND_REFRESH_DAYS:
                return False, None
            _MEM_CACHE[handle] = None
            return True, None
        _MEM_CACHE[handle] = row.user_id
        return True, row.user_id
    finally:
        db.close()


def _save_cached(handle: str, user_id: str | None):
    _MEM_CACHE[handle] = user_id
    db = SessionLocal()
    try:
        row = db.query(TwitterUserCache).filter(TwitterUserCache.handle == handle).first()
        if not row:
            row = TwitterUserCache(handle=handle)
            db.add(row)
        row.user_id = user_id or ""
        row.not_found = 0 if user_id else 1
        row.resolved_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


async def _pool_snapshot(api) -> dict[str, Any]:
    """Read the twscrape account pool; returns a compact snapshot even when the API changes."""
    try:
        pool = api.pool
        rows = await pool.accounts_info()
        total = len(rows)
        active = 0
        locked = 0
        locked_until: Optional[str] = None
        for r in rows:
            if r.get("active"):
                active += 1
            else:
                locked += 1
            lu = r.get("locks") or {}
            # locks is a dict queue_name -> iso-ts
            for ts in lu.values():
                if ts and (locked_until is None or str(ts) > locked_until):
                    locked_until = str(ts)
        return {"total": total, "active": active, "locked": locked, "locked_until": locked_until}
    except Exception as e:
        return {"total": -1, "active": -1, "locked": -1, "error": str(e)}


def _is_pool_exhausted(msg: str) -> bool:
    msg = msg.lower()
    return (
        "no account available" in msg
        or "no accounts available" in msg
        or "account timeouted" in msg
    )


async def _fetch_one(
    api,
    handle: str,
    cutoff: datetime,
    max_per_account: int,
    per_account_timeout_s: int,
    log: Optional[LogFn],
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Fetch recent tweets for a single handle, with a hard per-handle timeout.

    Returns (tweets, fatal_error). fatal_error is set when the pool is exhausted;
    callers should stop iterating handles because every subsequent call will fail.
    """

    async def _inner():
        cached, uid = _load_cached(handle)
        if not cached:
            _log(log, f"resolving @{handle} ...")
            try:
                user = await api.user_by_login(handle)
            except Exception as e:
                err = str(e)
                if _is_pool_exhausted(err):
                    raise TwitterPoolExhaustedError(err)
                _log(log, f"lookup failed @{handle}: {err}")
                return []
            if not user:
                _log(log, f"@{handle} not found - cached")
                _save_cached(handle, None)
                return []
            uid = str(user.id)
            _save_cached(handle, uid)
            _log(log, f"resolved @{handle} -> {uid}")
        elif uid is None:
            _log(log, f"skipping @{handle} (cached as not-found)")
            return []

        out: list[dict[str, Any]] = []
        try:
            count = 0
            async for tw in api.user_tweets(uid, limit=max_per_account):
                ts = tw.date
                if ts and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts and ts < cutoff:
                    break
                out.append({
                    "handle": handle,
                    "tweet_id": str(tw.id),
                    "url": tw.url,
                    "text": tw.rawContent or tw.displayText or "",
                    "created_at": ts.isoformat() if ts else None,
                })
                count += 1
                if count >= max_per_account:
                    break
        except TwitterPoolExhaustedError:
            raise
        except Exception as e:
            err = str(e)
            if _is_pool_exhausted(err):
                raise TwitterPoolExhaustedError(err)
            _log(log, f"fetch failed @{handle}: {err}")
            return out
        return out

    try:
        tweets = await asyncio.wait_for(_inner(), timeout=per_account_timeout_s)
        return tweets, None
    except TwitterPoolExhaustedError as e:
        return [], str(e)
    except asyncio.TimeoutError:
        _log(log, f"TIMEOUT @{handle} after {per_account_timeout_s}s")
        return [], None


async def fetch_recent_tweets(
    handles: list[str],
    lookback_hours: int,
    max_per_account: int,
    db_path: str,
    per_account_timeout_s: int = 25,
    log: Optional[LogFn] = None,
) -> list[dict[str, Any]]:
    try:
        from twscrape import API
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"twscrape not installed: {e}")

    api = API(db_path)

    snap = await _pool_snapshot(api)
    if snap.get("error"):
        _log(log, f"twscrape pool snapshot failed: {snap['error']}")
    else:
        _log(
            log,
            f"twscrape pool: total={snap['total']} active={snap['active']} "
            f"locked={snap['locked']}"
            + (f" (locked until {snap['locked_until']})" if snap.get("locked_until") else ""),
        )
        if snap.get("total", 0) == 0:
            raise TwitterPoolExhaustedError(
                "no twscrape accounts registered. Run setup add_cookies."
            )
        if snap.get("active", 0) == 0:
            raise TwitterPoolExhaustedError(
                f"all twscrape accounts locked"
                + (f" until {snap['locked_until']}" if snap.get("locked_until") else "")
                + ". Run `twscrape reset_locks` or add another account."
            )

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    _log(log, f"cutoff = {cutoff.isoformat()} (looking back {lookback_hours}h)")

    out: list[dict[str, Any]] = []
    exhausted = False
    for idx, h in enumerate(handles, start=1):
        h_clean = h.strip().lstrip("@").lower()
        if not h_clean:
            continue
        _log(log, f"[{idx}/{len(handles)}] @{h_clean} ...")
        tweets, fatal = await _fetch_one(
            api=api,
            handle=h_clean,
            cutoff=cutoff,
            max_per_account=max_per_account,
            per_account_timeout_s=per_account_timeout_s,
            log=log,
        )
        out.extend(tweets)
        _log(log, f"  @{h_clean}: +{len(tweets)} tweets (running total {len(out)})")
        if fatal:
            # The pool just died mid-run - don't burn through the remaining
            # handles waiting on timeouts for each.
            _log(log, f"pool exhausted mid-run: {fatal}. Stopping early.")
            exhausted = True
            break

    if exhausted and not out:
        raise TwitterPoolExhaustedError(
            "twscrape pool exhausted before any tweets could be fetched."
        )
    return out
