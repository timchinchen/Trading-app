"""Tests for scheduler interval gating (supports >59 minute cadences)."""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.agent.scheduler import _is_market_session_minute, _is_scheduled_tick


ET = ZoneInfo("America/New_York")


def _dt(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_market_session_window_bounds():
    # Friday
    assert _is_market_session_minute(_dt(2026, 5, 8, 9, 0)) is True
    assert _is_market_session_minute(_dt(2026, 5, 8, 15, 59)) is True
    assert _is_market_session_minute(_dt(2026, 5, 8, 8, 59)) is False
    assert _is_market_session_minute(_dt(2026, 5, 8, 16, 0)) is False


def test_scheduled_tick_every_30_minutes():
    assert _is_scheduled_tick(_dt(2026, 5, 8, 9, 0), 30) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 9, 30), 30) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 10, 0), 30) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 10, 1), 30) is False


def test_scheduled_tick_every_90_minutes():
    # Anchored to 09:00 ET open.
    assert _is_scheduled_tick(_dt(2026, 5, 8, 9, 0), 90) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 10, 30), 90) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 12, 0), 90) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 13, 30), 90) is True
    assert _is_scheduled_tick(_dt(2026, 5, 8, 15, 0), 90) is True
    # Off-cycle minutes should not run.
    assert _is_scheduled_tick(_dt(2026, 5, 8, 11, 0), 90) is False
    assert _is_scheduled_tick(_dt(2026, 5, 8, 15, 30), 90) is False


def test_scheduled_tick_never_runs_weekends():
    # Saturday
    assert _is_scheduled_tick(_dt(2026, 5, 9, 9, 0), 30) is False
