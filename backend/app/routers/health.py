"""Unauthenticated setup-health endpoint for the login-page Prerequisites panel.

Returns a flat matrix of {ok, detail} probes so a fresh deployment can see at
a glance which prerequisites are green / amber / red. All checks are safe:
they only make read-only calls (GET /v2/account, GET /api/tags, SELECT 1),
and nothing in the response contains raw secrets - only booleans plus short
human-readable diagnostics.

This endpoint deliberately sits on the public surface (no get_current_user
dependency) because the Login page hits it before the user has a token.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from ..config import APP_VERSION_BACKEND, settings
from ..db import SessionLocal
from ..services.settings_store import get_runtime_settings

router = APIRouter(tags=["health"])

_PROBE_TIMEOUT_S = 2.0


def _ok(detail: str = "") -> dict[str, Any]:
    return {"ok": True, "detail": detail}


def _fail(detail: str) -> dict[str, Any]:
    return {"ok": False, "detail": detail}


def _check_db() -> dict[str, Any]:
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return _ok("sqlite reachable")
        finally:
            db.close()
    except Exception as e:
        return _fail(f"db error: {e.__class__.__name__}: {e}")


def _check_alpaca() -> dict[str, Any]:
    key = settings.alpaca_key
    secret = settings.alpaca_secret
    if not key or not secret:
        return _fail(f"no {settings.APP_MODE} Alpaca key in .env")
    base = (
        "https://paper-api.alpaca.markets"
        if settings.is_paper
        else "https://api.alpaca.markets"
    )
    try:
        r = httpx.get(
            f"{base}/v2/account",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=_PROBE_TIMEOUT_S,
        )
        if r.status_code == 200:
            j = r.json()
            acct = j.get("account_number") or j.get("id") or ""
            bp = j.get("buying_power")
            return _ok(f"{settings.APP_MODE} account {acct[:10]} · BP {bp}")
        return _fail(f"alpaca http {r.status_code}")
    except Exception as e:
        return _fail(f"alpaca unreachable: {e.__class__.__name__}")


def _check_ollama() -> dict[str, Any]:
    # Always hit the raw Ollama host (not rs.llm_host - that resolves to
    # OpenAI's base URL when LLM_PROVIDER=openai, giving a confusing 404).
    try:
        rs = get_runtime_settings()
        host = rs.ollama_host or settings.OLLAMA_HOST
    except Exception:
        host = settings.OLLAMA_HOST
    try:
        r = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=_PROBE_TIMEOUT_S)
        if r.status_code == 200:
            tags = r.json().get("models") or []
            return _ok(f"{host} · {len(tags)} models")
        return _fail(f"ollama http {r.status_code} at {host}")
    except Exception:
        return _fail(f"not reachable at {host} (optional)")


def _check_openai_key() -> dict[str, Any]:
    try:
        rs = get_runtime_settings()
        set_ = bool(rs.openai_api_key) or bool(rs.deep_llm_openai_api_key)
    except Exception:
        set_ = bool(settings.OPENAI_API_KEY) or bool(settings.DEEP_LLM_OPENAI_API_KEY)
    # We do NOT call the OpenAI API here - that would cost money per page
    # load. Key-present is enough to flip the pill green.
    return {"ok": set_, "detail": "key set" if set_ else "not set (optional)"}


def _check_jwt() -> dict[str, Any]:
    v = (settings.JWT_SECRET or "").strip()
    bad = v in ("", "change_me", "change_me_to_a_long_random_string")
    if bad:
        return _fail("JWT_SECRET is empty or still the default")
    if len(v) < 16:
        return _fail("JWT_SECRET is shorter than 16 chars")
    return _ok("strong secret set")


def _check_playwright() -> dict[str, Any]:
    # Cheap: just look for the chromium binary pins that `playwright install
    # chromium` drops under ~/Library/Caches/ms-playwright (mac) or
    # ~/.cache/ms-playwright (linux). Avoids importing playwright every page
    # load.
    candidates = [
        os.path.expanduser("~/Library/Caches/ms-playwright"),
        os.path.expanduser("~/.cache/ms-playwright"),
        "/ms-playwright",
    ]
    for c in candidates:
        if os.path.isdir(c) and any(
            n.startswith("chromium") for n in os.listdir(c)
        ):
            return _ok(f"chromium present at {c}")
    return _fail("chromium not installed (run: playwright install chromium)")


def _check_optional_key(flag_getter) -> dict[str, Any]:
    try:
        ok = bool(flag_getter())
    except Exception:
        ok = False
    return {"ok": ok, "detail": "set" if ok else "not set (optional)"}


def _run_with_timeout(fn, timeout_s: float = _PROBE_TIMEOUT_S) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FutTimeout:
            return _fail(f"timeout after {timeout_s}s")
        except Exception as e:
            return _fail(f"{e.__class__.__name__}: {e}")


@router.get("/health/setup")
def setup_health() -> dict[str, Any]:
    """Flat health matrix for the login-screen Prerequisites panel.

    No auth - this endpoint is deliberately public because the operator
    needs it before they have credentials. Returns only booleans and
    non-secret diagnostic strings.
    """
    # The runtime-settings read is cheap; grab it once for the optional
    # third-party flags.
    try:
        rs = get_runtime_settings()
        fmp_ok = bool(rs.fmp_api_key)
        st_ok = bool(rs.stocktwits_cookies)
    except Exception:
        fmp_ok = bool(settings.FMP_API_KEY)
        st_ok = bool(settings.STOCKTWITS_COOKIES)

    return {
        "backend": {"ok": True, "detail": f"v{APP_VERSION_BACKEND}"},
        "mode": {"ok": True, "detail": settings.APP_MODE},
        "db": _run_with_timeout(_check_db),
        "jwt_secret": _check_jwt(),
        "alpaca": _run_with_timeout(_check_alpaca),
        "ollama": _run_with_timeout(_check_ollama),
        "openai": _check_openai_key(),
        "playwright": _check_playwright(),
        "fmp": {"ok": fmp_ok, "detail": "key set" if fmp_ok else "not set (optional)"},
        "stocktwits": {
            "ok": st_ok,
            "detail": "cookies set" if st_ok else "not set (optional)",
        },
    }
