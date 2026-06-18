"""Settings optimization wizard: deterministic drift/conflict checks + LLM tuning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from ..config import settings as env_settings
from .agent import llm as agent_llm
from .settings_store import (
    EDITABLE_KEYS,
    SECRET_KEYS,
    RuntimeSettings,
    _coerce,
    editable_settings_snapshot,
    get_runtime_settings,
)

Goal = Literal["default", "small_account_2_3_week_swing", "conservative"]

OPTIMIZER_SYSTEM = (
    "You are a settings-tuning advisor for a personal swing-trading agent. "
    "You do NOT pick stocks. You align runtime knobs with the operator's goal: "
    "2-3 week swings, small account, coherent exit stack, budgets, and thresholds.\n\n"
    "Respond with a single JSON object only (no markdown fences) with keys:\n"
    '  "summary": string (2-4 sentences),\n'
    '  "conflicts_addressed": array of short strings,\n'
    '  "recommended": object mapping EDITABLE setting KEYS to new values,\n'
    '  "rationale": object mapping each recommended KEY to one sentence why.\n\n'
    "Rules:\n"
    "- Only include keys you want changed in recommended (omit unchanged keys).\n"
    "- Never include API keys, cookies, or secrets.\n"
    "- Align the full exit stack for the stated horizon:\n"
    "  SWING_TIME_STOP_DAYS (engine trading-day proxy) <= "
    "AGENT_PROMPT_TIME_STOP_DAYS (LLM calendar-day guidance) <= "
    "AGENT_MAX_HOLD_DAYS (adaptive hard hold) <= AUTO_SELL_MAX_HOLD_DAYS.\n"
    "- For 2-3 week swings, typical targets: SWING_TIME_STOP_DAYS 12-15, "
    "AGENT_PROMPT_TIME_STOP_DAYS 18-21, AGENT_MAX_HOLD_DAYS 21, "
    "AUTO_SELL_MAX_HOLD_DAYS 28+.\n"
    "- Regime / CAUTION profile: risk multipliers should step down "
    "(AGENT_REGIME_RISK_ON_MULT >= AGENT_REGIME_NEUTRAL_MULT >= "
    "AGENT_REGIME_RISK_OFF_MULT); AGENT_CAUTION_SIZE_MULT <= 1.0; "
    "AGENT_CAUTION_MAX_OPEN_POSITIONS <= AGENT_MAX_OPEN_POSITIONS when set.\n"
    "- Confirm-first gates: prefer AGENT_REQUIRE_REGIME_CONFIRMATION=true and "
    "AGENT_REQUIRE_COMPLETE_DATA_FOR_BUYS=true for conservative goals; "
    "when the data gate is off, incomplete SPY data is mitigated via CAUTION "
    "sizing (AGENT_INCOMPLETE_DATA_SIZE_MULT) — do not pair a disabled gate "
    "with CAUTION_SIZE_MULT near 1.0.\n"
    "- AGENT_RISK_OFF_BLOCK_NEW_BUYS=true is appropriate for conservative "
    "profiles; intraday confirmation (AGENT_USE_INTRADAY_CONFIRMATION) never "
    "hard-blocks and is optional.\n"
    "- Fix conflicts listed in the input before cosmetic tweaks.\n"
    "- Use numeric fractions 0-1 for percent fields stored as decimals in env "
    "(e.g. 0.07 = 7%).\n"
)


@dataclass
class SettingsIssue:
    key: str | None
    severity: Literal["error", "warn", "info"]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "severity": self.severity,
            "message": self.message,
        }


def env_defaults_snapshot() -> dict[str, Any]:
    """Raw .env / config.py defaults for every editable key."""
    out: dict[str, Any] = {}
    for key in EDITABLE_KEYS:
        if key in SECRET_KEYS:
            val = getattr(env_settings, key, "")
            out[key] = "<set>" if val else ""
        else:
            out[key] = getattr(env_settings, key, None)
    return out


def masked_settings_snapshot(rs: RuntimeSettings) -> dict[str, Any]:
    snap = editable_settings_snapshot(rs)
    for key in SECRET_KEYS:
        if key in snap:
            snap[key] = "<set>" if snap.get(key) else ""
    return snap


def detect_conflicts(rs: RuntimeSettings) -> list[SettingsIssue]:
    issues: list[SettingsIssue] = []

    if rs.agent_min_position_usd > rs.agent_max_position_usd:
        issues.append(
            SettingsIssue(
                "AGENT_MIN_POSITION_USD",
                "error",
                f"Min position ${rs.agent_min_position_usd:.0f} exceeds max "
                f"${rs.agent_max_position_usd:.0f}.",
            )
        )

    if rs.agent_weekly_budget_usd > 0 and rs.agent_budget_usd > rs.agent_weekly_budget_usd:
        issues.append(
            SettingsIssue(
                "AGENT_BUDGET_USD",
                "warn",
                f"Daily budget ${rs.agent_budget_usd:.0f} exceeds weekly cap "
                f"${rs.agent_weekly_budget_usd:.0f}.",
            )
        )

    if rs.agent_take_profit_pct > 0 and rs.agent_partial_take_pct >= rs.agent_take_profit_pct:
        issues.append(
            SettingsIssue(
                "AGENT_PARTIAL_TAKE_PCT",
                "warn",
                f"Partial take at {rs.agent_partial_take_pct * 100:.1f}% fires at or before "
                f"take-profit {rs.agent_take_profit_pct * 100:.1f}%.",
            )
        )

    if rs.agent_trail_arm_pct > rs.agent_partial_take_pct:
        issues.append(
            SettingsIssue(
                "AGENT_TRAIL_ARM_PCT",
                "warn",
                f"Trail arm {rs.agent_trail_arm_pct * 100:.1f}% is above partial "
                f"take {rs.agent_partial_take_pct * 100:.1f}%.",
            )
        )

    if rs.auto_sell_max_hold_days < rs.agent_max_hold_days:
        issues.append(
            SettingsIssue(
                "AUTO_SELL_MAX_HOLD_DAYS",
                "warn",
                f"Auto-sell cap {rs.auto_sell_max_hold_days}d is shorter than adaptive "
                f"hard hold {rs.agent_max_hold_days}d — positions may be closed by auto-sell first.",
            )
        )

    if rs.swing_time_stop_days > rs.agent_max_hold_days:
        issues.append(
            SettingsIssue(
                "SWING_TIME_STOP_DAYS",
                "warn",
                f"Swing time-stop {rs.swing_time_stop_days} trading-day proxy exceeds "
                f"calendar hard hold {rs.agent_max_hold_days}d.",
            )
        )

    if rs.agent_prompt_time_stop_days > rs.agent_max_hold_days:
        issues.append(
            SettingsIssue(
                "AGENT_PROMPT_TIME_STOP_DAYS",
                "warn",
                f"Prompt time-stop {rs.agent_prompt_time_stop_days}d exceeds hard hold "
                f"{rs.agent_max_hold_days}d — LLM guidance outlasts the adaptive exit cap.",
            )
        )

    if rs.agent_prompt_time_stop_days > rs.auto_sell_max_hold_days:
        issues.append(
            SettingsIssue(
                "AGENT_PROMPT_TIME_STOP_DAYS",
                "warn",
                f"Prompt time-stop {rs.agent_prompt_time_stop_days}d exceeds auto-sell max "
                f"hold {rs.auto_sell_max_hold_days}d.",
            )
        )

    if rs.agent_prompt_time_stop_days < rs.swing_time_stop_days:
        issues.append(
            SettingsIssue(
                "AGENT_PROMPT_TIME_STOP_DAYS",
                "info",
                f"Prompt time-stop {rs.agent_prompt_time_stop_days}d is shorter than swing "
                f"engine time-stop {rs.swing_time_stop_days}d — LLM may underestimate hold "
                "patience vs the trade-management pass.",
            )
        )

    if rs.swing_partial_pct > rs.agent_partial_take_pct + 0.02:
        issues.append(
            SettingsIssue(
                "SWING_PARTIAL_PCT",
                "info",
                f"Swing partial flag {rs.swing_partial_pct * 100:.1f}% is well above "
                f"agent partial {rs.agent_partial_take_pct * 100:.1f}%.",
            )
        )

    if rs.swing_move_stop_be_pct < rs.swing_partial_pct:
        issues.append(
            SettingsIssue(
                "SWING_MOVE_STOP_BE_PCT",
                "info",
                "Breakeven move threshold is below swing partial — check ordering.",
            )
        )

    if rs.agent_auto_execute_live and (
        rs.agent_min_score < 0.3 or rs.agent_min_confidence < 0.3
    ):
        issues.append(
            SettingsIssue(
                "AGENT_AUTO_EXECUTE_LIVE",
                "warn",
                "Live auto-execute with very low MIN_SCORE or MIN_CONFIDENCE — high churn risk.",
            )
        )

    # Regime / data-gating + CAUTION-tier coherence
    if rs.agent_caution_size_mult > 1.0:
        issues.append(
            SettingsIssue(
                "AGENT_CAUTION_SIZE_MULT",
                "warn",
                f"CAUTION size multiplier {rs.agent_caution_size_mult:.2f} > 1.0 increases "
                "size in CAUTION — it should reduce it (<= 1.0).",
            )
        )

    if rs.agent_caution_min_rr and rs.agent_caution_min_rr < rs.swing_min_rr:
        issues.append(
            SettingsIssue(
                "AGENT_CAUTION_MIN_RR",
                "info",
                f"CAUTION R/R floor {rs.agent_caution_min_rr:.2f} is below the base "
                f"SWING_MIN_RR {rs.swing_min_rr:.2f}, so it never tightens entries.",
            )
        )

    if (
        rs.agent_caution_max_open_positions
        and rs.agent_caution_max_open_positions > rs.agent_max_open_positions
    ):
        issues.append(
            SettingsIssue(
                "AGENT_CAUTION_MAX_OPEN_POSITIONS",
                "warn",
                f"CAUTION open cap {rs.agent_caution_max_open_positions} exceeds the base "
                f"MAX_OPEN_POSITIONS {rs.agent_max_open_positions}; CAUTION should be tighter.",
            )
        )

    if not rs.agent_require_complete_data_for_buys:
        issues.append(
            SettingsIssue(
                "AGENT_REQUIRE_COMPLETE_DATA_FOR_BUYS",
                "warn",
                "Confirm-first data gate is OFF — the agent may buy while SPY bars/volume "
                "are missing or stale.",
            )
        )

    if rs.agent_plan_backfill_stop_pct >= rs.agent_plan_backfill_target_pct:
        issues.append(
            SettingsIssue(
                "AGENT_PLAN_BACKFILL_STOP_PCT",
                "warn",
                f"Backfill stop {rs.agent_plan_backfill_stop_pct * 100:.1f}% >= target "
                f"{rs.agent_plan_backfill_target_pct * 100:.1f}% — backfilled plans have R/R <= 1.",
            )
        )

    if rs.agent_regime_risk_on_mult < rs.agent_regime_neutral_mult:
        issues.append(
            SettingsIssue(
                "AGENT_REGIME_RISK_ON_MULT",
                "warn",
                f"Risk-on multiplier {rs.agent_regime_risk_on_mult:.2f} is below neutral "
                f"{rs.agent_regime_neutral_mult:.2f} — regime sizing should step down.",
            )
        )

    if rs.agent_regime_neutral_mult < rs.agent_regime_risk_off_mult:
        issues.append(
            SettingsIssue(
                "AGENT_REGIME_NEUTRAL_MULT",
                "warn",
                f"Neutral multiplier {rs.agent_regime_neutral_mult:.2f} is below risk-off "
                f"{rs.agent_regime_risk_off_mult:.2f} — regime sizing should step down.",
            )
        )

    if (
        not rs.agent_require_complete_data_for_buys
        and rs.agent_incomplete_data_size_mult > 0.8
    ):
        issues.append(
            SettingsIssue(
                "AGENT_INCOMPLETE_DATA_SIZE_MULT",
                "info",
                "Data-completeness gate is OFF and incomplete-data size mult is high "
                f"({rs.agent_incomplete_data_size_mult:.2f}) — stale SPY data may still "
                "allow near-full sizing via CAUTION mitigation.",
            )
        )

    return issues


def detect_drift(rs: RuntimeSettings) -> list[SettingsIssue]:
    issues: list[SettingsIssue] = []
    current = editable_settings_snapshot(rs)

    for key in sorted(rs.overridden):
        if key in SECRET_KEYS:
            continue
        env_val = getattr(env_settings, key, None)
        try:
            target = EDITABLE_KEYS[key]
            coerced_env = _coerce(str(env_val), target) if env_val is not None else env_val
            coerced_cur = _coerce(str(current[key]), target)
        except Exception:
            coerced_env = env_val
            coerced_cur = current.get(key)
        if coerced_cur == coerced_env:
            issues.append(
                SettingsIssue(
                    key,
                    "info",
                    "DB override matches .env default (stale override row — value may "
                    "revert if .env changes on upgrade).",
                )
            )

    if "AGENT_MAX_HOLD_DAYS" not in rs.overridden:
        issues.append(
            SettingsIssue(
                "AGENT_MAX_HOLD_DAYS",
                "info",
                f"Using .env default ({rs.agent_max_hold_days} calendar days). "
                "Save in Settings → Agent budget → Exit rules to persist an override.",
            )
        )

    if "AGENT_PROMPT_TIME_STOP_DAYS" not in rs.overridden:
        issues.append(
            SettingsIssue(
                "AGENT_PROMPT_TIME_STOP_DAYS",
                "info",
                f"Using .env default ({rs.agent_prompt_time_stop_days} calendar days). "
                "Align with SWING_TIME_STOP_DAYS and Max hold days in Settings → Exit rules.",
            )
        )

    if rs.swing_time_stop_days == 10 and "SWING_TIME_STOP_DAYS" not in rs.overridden:
        issues.append(
            SettingsIssue(
                "SWING_TIME_STOP_DAYS",
                "info",
                "TIME_STOP_DAYS is the v1.2+ default (10). For 2-3 week swings, 12-15 is "
                "typical — click Save swing rules after changing.",
            )
        )

    gap = rs.auto_sell_max_hold_days - rs.agent_max_hold_days
    if gap < 7:
        issues.append(
            SettingsIssue(
                None,
                "info",
                f"Auto-sell max hold ({rs.auto_sell_max_hold_days}d) is only {gap}d above "
                f"adaptive hold ({rs.agent_max_hold_days}d) — consider 21d+ for swing horizon.",
            )
        )

    return issues


def _clamp_recommended_value(key: str, value: Any) -> Any:
    """Clamp known numeric knobs to safe ranges."""
    if key == "AGENT_CRON_MINUTES":
        return max(1, int(float(value)))
    if key in (
        "AGENT_REGIME_RISK_ON_MULT",
        "AGENT_REGIME_NEUTRAL_MULT",
        "AGENT_REGIME_RISK_OFF_MULT",
    ):
        return max(0.1, min(2.0, float(value)))
    if key in (
        "AGENT_TRAIL_ARM_PCT",
        "AGENT_TRAIL_RETRACE_PCT",
        "AGENT_PARTIAL_TAKE_PCT",
        "AGENT_PARTIAL_TAKE_FRACTION",
    ):
        return max(0.0, min(1.0, float(value)))
    if key in ("AGENT_MAX_HOLD_DAYS", "AGENT_PROMPT_TIME_STOP_DAYS"):
        return max(1, int(float(value)))
    if key == "AGENT_WEEKLY_LESSON_MAX_CHARS":
        return max(200, min(4000, int(float(value))))
    if key == "SWING_TIME_STOP_DAYS":
        return max(1, min(60, int(float(value))))
    if key == "AUTO_SELL_MAX_HOLD_DAYS":
        return max(1, min(365, int(float(value))))
    return value


def sanitize_recommendations(
    raw: dict[str, Any],
    current: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (recommended_changes_only, rationale) — secrets and unknown keys dropped."""
    recommended_in = raw.get("recommended") if isinstance(raw.get("recommended"), dict) else {}
    rationale_in = raw.get("rationale") if isinstance(raw.get("rationale"), dict) else {}
    out: dict[str, Any] = {}
    rationale: dict[str, str] = {}

    for key, value in recommended_in.items():
        ku = str(key).upper()
        if ku in SECRET_KEYS or ku not in EDITABLE_KEYS:
            continue
        try:
            coerced = _coerce(str(value), EDITABLE_KEYS[ku])
            coerced = _clamp_recommended_value(ku, coerced)
        except Exception:
            continue
        cur = current.get(ku)
        if cur == coerced:
            continue
        out[ku] = coerced
        rat = rationale_in.get(ku) or rationale_in.get(key)
        if rat:
            rationale[ku] = str(rat)[:500]

    return out, rationale


def parse_optimizer_response(raw: str) -> dict[str, Any] | None:
    parsed = agent_llm._extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    if "recommended" not in parsed and "summary" not in parsed:
        return None
    return parsed


def build_optimizer_user_prompt(
    *,
    rs: RuntimeSettings,
    conflicts: list[SettingsIssue],
    drift: list[SettingsIssue],
    assumptions: list[dict[str, Any]],
    goal: Goal,
    trading_context: str = "",
    weekly_stats: str = "",
) -> str:
    goal_lines = {
        "default": "Goal: balanced defaults for 1-2 week swings.",
        "small_account_2_3_week_swing": (
            "Goal: small account (~$200-$500), 2-3 week swing horizon, "
            "tight risk, aligned exit stack."
        ),
        "conservative": (
            "Goal: conservative — higher thresholds, smaller slots, "
            "avoid aggressive live auto-execute."
        ),
    }
    masked = masked_settings_snapshot(rs)
    env_defs = env_defaults_snapshot()
    for k in SECRET_KEYS:
        if k in env_defs and env_defs[k] != "":
            env_defs[k] = "<set>"

    payload = {
        "goal": goal_lines.get(goal, goal_lines["default"]),
        "app_mode": env_settings.APP_MODE,
        "overridden_keys": sorted(rs.overridden),
        "conflicts": [c.to_dict() for c in conflicts],
        "drift": [d.to_dict() for d in drift],
        "effective_settings": masked,
        "env_defaults": env_defs,
        "logic_assumptions": assumptions,
    }
    parts = [
        json.dumps(payload, default=str)[:12000],
    ]
    if weekly_stats:
        parts.append(f"\n--- RECENT WEEK STATS ---\n{weekly_stats[:2000]}")
    if trading_context:
        parts.append(f"\n--- TRADING CONTEXT ---\n{trading_context[:8000]}")
    return "\n".join(parts)


async def run_settings_optimize(
    db: Session,
    broker: Any,
    *,
    goal: Goal = "default",
    assumptions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Full optimize pass: rules + advisor LLM."""
    from .trading_context import build_trading_context_text
    from .prompt_feedback import compute_weekly_stats, format_stats_brief

    rs = get_runtime_settings(db)
    conflicts = detect_conflicts(rs)
    drift = detect_drift(rs)
    current = editable_settings_snapshot(rs)

    trading_context = ""
    weekly_stats = ""
    try:
        trading_context = build_trading_context_text(
            db, broker, digests_limit=3, runs_limit=10
        )
    except Exception as e:
        trading_context = f"(context unavailable: {e})"
    try:
        weekly_stats = format_stats_brief(
            compute_weekly_stats(db, env_settings.APP_MODE)
        )
    except Exception:
        pass

    if assumptions is None:
        assumptions = []

    user_prompt = build_optimizer_user_prompt(
        rs=rs,
        conflicts=conflicts,
        drift=drift,
        assumptions=assumptions,
        goal=goal,
        trading_context=trading_context,
        weekly_stats=weekly_stats,
    )

    model_used = f"{rs.advisor_provider}:{rs.advisor_model}"
    summary = ""
    recommended: dict[str, Any] = {}
    rationale: dict[str, str] = {}
    llm_error: str | None = None
    conflicts_addressed: list[str] = []

    try:
        raw = await agent_llm._chat(
            provider=rs.advisor_provider,
            host=rs.advisor_host,
            model=rs.advisor_model,
            api_key=rs.advisor_api_key,
            system=OPTIMIZER_SYSTEM,
            user=user_prompt,
            json_mode=True,
            temperature=0.2,
            timeout=180,
        )
        parsed = parse_optimizer_response(raw or "")
        if parsed:
            summary = str(parsed.get("summary") or "").strip()
            ca = parsed.get("conflicts_addressed")
            if isinstance(ca, list):
                conflicts_addressed = [str(x)[:200] for x in ca[:20]]
            recommended, rationale = sanitize_recommendations(parsed, current)
        else:
            llm_error = "Could not parse optimizer JSON from the advisor model."
    except Exception as e:
        llm_error = str(e)

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "goal": goal,
        "model_used": model_used,
        "conflicts": [c.to_dict() for c in conflicts],
        "drift": [d.to_dict() for d in drift],
        "summary": summary,
        "conflicts_addressed": conflicts_addressed,
        "recommended": recommended,
        "rationale": rationale,
        "current": {k: current[k] for k in recommended},
        "llm_error": llm_error,
        "apply_allowed": bool(recommended) and llm_error is None,
    }
