"""Runtime-editable settings layer.

Reads `.env` defaults from `config.settings`, then overlays any rows in the
`app_settings` table. Anything in the DB wins, so the user can change provider
keys, follow lists, budget knobs, etc. from the Settings UI without touching
.env or restarting uvicorn.

Usage:
    rs = get_runtime_settings()
    rs.llm_provider          # "ollama" | "openai"
    rs.openai_api_key        # raw secret (do NOT return this from the API)
    rs.twitter_accounts_list # list[str]
"""

from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..config import settings as env_settings
from ..db import SessionLocal
from ..models import AppSetting


# Keys that the Settings UI is allowed to read/write. Anything else is rejected.
EDITABLE_KEYS: dict[str, type] = {
    # LLM
    "LLM_PROVIDER": str,
    "OLLAMA_HOST": str,
    "OLLAMA_MODEL": str,
    "OPENAI_API_KEY": str,
    "OPENAI_MODEL": str,
    "OPENAI_BASE_URL": str,
    # Per-ticker enrichment
    "FMP_API_KEY": str,
    "FMP_BASE_URL": str,
    "SEC_USER_AGENT": str,
    "STOCKTWITS_COOKIES": str,
    # Agent budget / cadence
    "AGENT_ENABLED": bool,
    "AGENT_AUTO_EXECUTE_LIVE": bool,
    "AGENT_BUDGET_USD": float,
    "AGENT_WEEKLY_BUDGET_USD": float,
    "AGENT_MIN_POSITION_USD": float,
    "AGENT_MAX_POSITION_USD": float,
    "AGENT_DAILY_LOSS_CAP_USD": float,
    "AGENT_MAX_OPEN_POSITIONS": int,
    "AGENT_CRON_MINUTES": int,
    "AGENT_INTEL_BOOST": float,
    "AGENT_TAKE_PROFIT_PCT": float,
    "AGENT_RECENT_TRADE_WINDOW_HOURS": int,
    # Twitter
    "TWITTER_ACCOUNTS": str,
}

# Keys whose value should be masked when the API returns the current settings.
SECRET_KEYS = {"OPENAI_API_KEY", "FMP_API_KEY", "STOCKTWITS_COOKIES"}


def _coerce(raw: str, target: type) -> Any:
    if target is bool:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if target is int:
        return int(float(raw))
    if target is float:
        return float(raw)
    return str(raw)


def _load_overrides(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).all()
    return {r.key: r.value for r in rows}


@dataclass
class RuntimeSettings:
    # LLM
    llm_provider: str = "ollama"
    ollama_host: str = ""
    ollama_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    openai_base_url: str = ""
    # Enrichment
    fmp_api_key: str = ""
    fmp_base_url: str = ""
    sec_user_agent: str = ""
    stocktwits_cookies: str = ""
    # Agent
    agent_enabled: bool = False
    agent_auto_execute_live: bool = False
    agent_budget_usd: float = 0.0
    agent_weekly_budget_usd: float = 0.0
    agent_min_position_usd: float = 0.0
    agent_max_position_usd: float = 0.0
    agent_daily_loss_cap_usd: float = 0.0
    agent_max_open_positions: int = 0
    agent_cron_minutes: int = 0
    agent_intel_boost: float = 0.0
    agent_take_profit_pct: float = 0.0
    agent_recent_trade_window_hours: int = 0
    # Twitter
    twitter_accounts: str = ""
    # Bookkeeping: which keys are overridden in the DB (vs env default)
    overridden: set[str] = field(default_factory=set)

    @property
    def twitter_accounts_list(self) -> list[str]:
        return [a.strip().lstrip("@") for a in self.twitter_accounts.split(",") if a.strip()]

    @property
    def llm_model(self) -> str:
        return self.openai_model if self.llm_provider == "openai" else self.ollama_model

    @property
    def llm_host(self) -> str:
        return self.openai_base_url if self.llm_provider == "openai" else self.ollama_host


def get_runtime_settings(db: Session | None = None) -> RuntimeSettings:
    """Resolve the effective runtime settings = env defaults + DB overrides."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        overrides = _load_overrides(db)  # type: ignore[arg-type]
    finally:
        if own_session:
            db.close()  # type: ignore[union-attr]

    def pick(key: str, target: type) -> Any:
        if key in overrides and overrides[key] != "":
            try:
                return _coerce(overrides[key], target)
            except Exception:
                pass  # fall through to env default
        return getattr(env_settings, key)

    rs = RuntimeSettings(
        llm_provider=str(pick("LLM_PROVIDER", str)),
        ollama_host=str(pick("OLLAMA_HOST", str)),
        ollama_model=str(pick("OLLAMA_MODEL", str)),
        openai_api_key=str(pick("OPENAI_API_KEY", str)),
        openai_model=str(pick("OPENAI_MODEL", str)),
        openai_base_url=str(pick("OPENAI_BASE_URL", str)),
        fmp_api_key=str(pick("FMP_API_KEY", str)),
        fmp_base_url=str(pick("FMP_BASE_URL", str)),
        sec_user_agent=str(pick("SEC_USER_AGENT", str)),
        stocktwits_cookies=str(pick("STOCKTWITS_COOKIES", str)),
        agent_enabled=bool(pick("AGENT_ENABLED", bool)),
        agent_auto_execute_live=bool(pick("AGENT_AUTO_EXECUTE_LIVE", bool)),
        agent_budget_usd=float(pick("AGENT_BUDGET_USD", float)),
        agent_weekly_budget_usd=float(pick("AGENT_WEEKLY_BUDGET_USD", float)),
        agent_min_position_usd=float(pick("AGENT_MIN_POSITION_USD", float)),
        agent_max_position_usd=float(pick("AGENT_MAX_POSITION_USD", float)),
        agent_daily_loss_cap_usd=float(pick("AGENT_DAILY_LOSS_CAP_USD", float)),
        agent_max_open_positions=int(pick("AGENT_MAX_OPEN_POSITIONS", int)),
        agent_cron_minutes=int(pick("AGENT_CRON_MINUTES", int)),
        agent_intel_boost=float(pick("AGENT_INTEL_BOOST", float)),
        agent_take_profit_pct=float(pick("AGENT_TAKE_PROFIT_PCT", float)),
        agent_recent_trade_window_hours=int(pick("AGENT_RECENT_TRADE_WINDOW_HOURS", int)),
        twitter_accounts=str(pick("TWITTER_ACCOUNTS", str)),
        overridden={k for k, v in overrides.items() if v != ""},
    )
    return rs


def update_settings(db: Session, updates: dict[str, Any]) -> RuntimeSettings:
    """Persist a set of key/value overrides. Unknown or empty-string values are
    treated as 'unset' (the row is removed and we fall back to .env)."""
    for raw_key, raw_value in updates.items():
        key = raw_key.upper()
        if key not in EDITABLE_KEYS:
            continue
        # Empty / None means "clear the override, use env default"
        if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if row:
                db.delete(row)
            continue
        # Stringify whatever we got (we always store as TEXT)
        if isinstance(raw_value, bool):
            value_s = "true" if raw_value else "false"
        else:
            value_s = str(raw_value)
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value_s
        else:
            db.add(AppSetting(key=key, value=value_s))
    db.commit()
    return get_runtime_settings(db)


def public_view(rs: RuntimeSettings) -> dict[str, Any]:
    """Render a runtime-settings object for the API (mask secrets)."""
    out: dict[str, Any] = {
        "llm_provider": rs.llm_provider,
        "ollama_host": rs.ollama_host,
        "ollama_model": rs.ollama_model,
        "openai_model": rs.openai_model,
        "openai_base_url": rs.openai_base_url,
        "openai_api_key_set": bool(rs.openai_api_key),
        "openai_api_key_preview": (
            (rs.openai_api_key[:6] + "..." + rs.openai_api_key[-4:])
            if len(rs.openai_api_key) >= 12
            else ("set" if rs.openai_api_key else "")
        ),
        "fmp_base_url": rs.fmp_base_url,
        "fmp_api_key_set": bool(rs.fmp_api_key),
        "fmp_api_key_preview": (
            (rs.fmp_api_key[:6] + "..." + rs.fmp_api_key[-4:])
            if len(rs.fmp_api_key) >= 12
            else ("set" if rs.fmp_api_key else "")
        ),
        "sec_user_agent": rs.sec_user_agent,
        "stocktwits_cookies_set": bool(rs.stocktwits_cookies),
        "stocktwits_cookies_preview": (
            f"{len(rs.stocktwits_cookies)} chars stored"
            if rs.stocktwits_cookies
            else ""
        ),
        "agent_enabled": rs.agent_enabled,
        "agent_auto_execute_live": rs.agent_auto_execute_live,
        "agent_budget_usd": rs.agent_budget_usd,
        "agent_weekly_budget_usd": rs.agent_weekly_budget_usd,
        "agent_min_position_usd": rs.agent_min_position_usd,
        "agent_max_position_usd": rs.agent_max_position_usd,
        "agent_daily_loss_cap_usd": rs.agent_daily_loss_cap_usd,
        "agent_max_open_positions": rs.agent_max_open_positions,
        "agent_cron_minutes": rs.agent_cron_minutes,
        "agent_intel_boost": rs.agent_intel_boost,
        "agent_take_profit_pct": rs.agent_take_profit_pct,
        "agent_recent_trade_window_hours": rs.agent_recent_trade_window_hours,
        "twitter_accounts": rs.twitter_accounts,
        "overridden": sorted(rs.overridden),
    }
    return out


def keys() -> Iterable[str]:
    return EDITABLE_KEYS.keys()
