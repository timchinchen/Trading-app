from app.services.agent.scheduler import _DEFAULT_AGENT_CRON_MINUTES, _safe_cron_step_minutes
from app.services.settings_store import (
    _AGENT_CRON_MINUTES_DEFAULT,
    _safe_agent_cron_minutes,
)


def test_safe_cron_step_minutes_accepts_positive_values():
    assert _safe_cron_step_minutes(1) == 1
    assert _safe_cron_step_minutes(59) == 59
    assert _safe_cron_step_minutes(90) == 90
    assert _safe_cron_step_minutes("30") == 30


def test_safe_cron_step_minutes_falls_back_on_invalid_values():
    assert _safe_cron_step_minutes(0) == _DEFAULT_AGENT_CRON_MINUTES
    assert _safe_cron_step_minutes("oops") == _DEFAULT_AGENT_CRON_MINUTES


def test_safe_agent_cron_minutes_accepts_positive_values():
    assert _safe_agent_cron_minutes(1, source="test") == 1
    assert _safe_agent_cron_minutes(59, source="test") == 59
    assert _safe_agent_cron_minutes(90, source="test") == 90
    assert _safe_agent_cron_minutes("15", source="test") == 15


def test_safe_agent_cron_minutes_falls_back_on_invalid_values():
    assert _safe_agent_cron_minutes(0, source="test") == _AGENT_CRON_MINUTES_DEFAULT
    assert _safe_agent_cron_minutes("bad", source="test") == _AGENT_CRON_MINUTES_DEFAULT
