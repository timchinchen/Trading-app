"""Unit tests for settings optimization wizard (deterministic rules)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.settings_store import RuntimeSettings
from app.services.settings_optimizer import (
    detect_conflicts,
    detect_drift,
    sanitize_recommendations,
    parse_optimizer_response,
)


def _rs(**kwargs) -> RuntimeSettings:
    base = RuntimeSettings()
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_detect_conflicts_min_exceeds_max():
    rs = _rs(agent_min_position_usd=150, agent_max_position_usd=100)
    issues = detect_conflicts(rs)
    assert any(i.severity == "error" and i.key == "AGENT_MIN_POSITION_USD" for i in issues)


def test_detect_conflicts_auto_sell_shorter_than_hold():
    rs = _rs(auto_sell_max_hold_days=10, agent_max_hold_days=14)
    issues = detect_conflicts(rs)
    assert any(i.key == "AUTO_SELL_MAX_HOLD_DAYS" for i in issues)


def test_sanitize_drops_secrets_and_unchanged():
    current = {
        "SWING_TIME_STOP_DAYS": 10,
        "AGENT_BUDGET_USD": 200.0,
        "OPENAI_API_KEY": "sk-secret",
    }
    raw = {
        "recommended": {
            "SWING_TIME_STOP_DAYS": 15,
            "AGENT_BUDGET_USD": 200,
            "OPENAI_API_KEY": "hacked",
            "NOT_A_KEY": 1,
        },
        "rationale": {"SWING_TIME_STOP_DAYS": "Align 2-3 week horizon"},
    }
    rec, rat = sanitize_recommendations(raw, current)
    assert rec == {"SWING_TIME_STOP_DAYS": 15}
    assert "OPENAI_API_KEY" not in rec
    assert "NOT_A_KEY" not in rec
    assert rat["SWING_TIME_STOP_DAYS"] == "Align 2-3 week horizon"


def test_parse_optimizer_response():
    raw = '{"summary": "ok", "recommended": {"SWING_TIME_STOP_DAYS": 12}}'
    parsed = parse_optimizer_response(raw)
    assert parsed is not None
    assert parsed.get("summary") == "ok"


def test_detect_drift_hidden_max_hold():
    rs = _rs(agent_max_hold_days=7, overridden=set())
    issues = detect_drift(rs)
    assert any(i.key == "AGENT_MAX_HOLD_DAYS" for i in issues)
