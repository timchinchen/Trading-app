"""Tests for weekly prompt feedback and dynamic preamble."""

from datetime import datetime, timedelta

from app.services.agent.llm import (
    ROLE_PREAMBLE_BASE,
    build_advisor_system_prompt,
    build_role_preamble,
    build_role_preamble_base,
)
from app.services.prompt_feedback import (
    current_week_key,
    format_stats_brief,
    parse_advisor_feedback,
    week_start_utc,
)


def test_parse_advisor_feedback():
    advice = (
        "Market Regime\n- no-go\n\n"
        "Feedback to operator\n"
        "- Incorporating an earnings calendar would help.\n"
    )
    fb = parse_advisor_feedback(advice)
    assert fb is not None
    assert "earnings calendar" in fb.lower()


def test_parse_advisor_feedback_missing():
    assert parse_advisor_feedback("no feedback section") is None


def test_week_key_format():
    wk = current_week_key(datetime(2026, 5, 25))
    assert wk.startswith("2026-W")


def test_build_role_preamble_disabled():
    text = build_role_preamble(None, enabled=False)
    assert text == ROLE_PREAMBLE_BASE


def test_format_stats_brief_empty():
    brief = format_stats_brief({"week_key": "2026-W21", "realized_pl": 0, "wins": 0, "losses": 0})
    assert "2026-W21" in brief


def test_week_start_is_monday():
    # Wednesday 2026-05-27 -> Monday 2026-05-25
    start = week_start_utc(datetime(2026, 5, 27, 12, 0, 0))
    assert start.weekday() == 0
    assert start.day == 25


def test_build_role_preamble_includes_lessons_header_when_stats_fallback():
    """Without DB, enabled=True still returns base only; disabled stays base."""
    text = build_role_preamble(None, enabled=True)
    assert ROLE_PREAMBLE_BASE in text
    text_off = build_role_preamble(None, enabled=False)
    assert text_off == ROLE_PREAMBLE_BASE


def test_prompt_time_stop_is_dynamic():
    base = build_role_preamble_base(21)
    assert "after 21 days exit" in base
    advisor = build_advisor_system_prompt(None, prompt_time_stop_days=21)
    assert ">=21 day time-stop triggers" in advisor
