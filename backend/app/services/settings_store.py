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
    # LLM (agent / tweet-level)
    "LLM_PROVIDER": str,
    "OLLAMA_HOST": str,
    "OLLAMA_MODEL": str,
    "OPENAI_API_KEY": str,
    "OPENAI_MODEL": str,
    "OPENAI_BASE_URL": str,
    "HUGGINGFACE_API_KEY": str,
    "HUGGINGFACE_MODEL": str,
    "HUGGINGFACE_BASE_URL": str,
    "COHERE_API_KEY": str,
    "COHERE_MODEL": str,
    "COHERE_BASE_URL": str,
    # Deep Analysis LLM (advisor). Empty string = fall back to Agent LLM.
    "DEEP_LLM_ENABLED": bool,
    "DEEP_LLM_PROVIDER": str,
    "DEEP_LLM_OLLAMA_HOST": str,
    "DEEP_LLM_OLLAMA_MODEL": str,
    "DEEP_LLM_OPENAI_API_KEY": str,
    "DEEP_LLM_OPENAI_MODEL": str,
    "DEEP_LLM_OPENAI_BASE_URL": str,
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
    # Agent signal thresholds (previously hard-coded)
    "AGENT_MIN_SCORE": float,
    "AGENT_MIN_CONFIDENCE": float,
    "AGENT_TOP_N_CANDIDATES": int,
    "AGENT_LLM_CONCURRENCY": int,
    # Scraper cadence (previously hard-coded)
    "AGENT_MAX_TWEETS_PER_ACCOUNT": int,
    "AGENT_LOOKBACK_HOURS": int,
    "AGENT_PER_ACCOUNT_TIMEOUT_S": int,
    "POLL_INTERVAL_SECONDS": int,
    # Manual order safety cap
    "MANUAL_ORDER_MAX_NOTIONAL": float,
    # Twitter
    "TWITTER_ACCOUNTS": str,
    # Swing-trading skill
    "SWING_ENABLED": bool,
    "SWING_RISK_PER_TRADE_PCT": float,
    "SWING_MIN_RR": float,
    "SWING_TIME_STOP_DAYS": int,
    "SWING_MOVE_STOP_BE_PCT": float,
    "SWING_PARTIAL_PCT": float,
    # Auto-sell (max-hold window)
    "AUTO_SELL_ENABLED": bool,
    "AUTO_SELL_MAX_HOLD_DAYS": int,
    "SWING_MARKET_FILTER_SYMBOL": str,
    "SWING_MARKET_FILTER_MA": int,
    "SWING_BAR_LOOKBACK_DAYS": int,
}

# Keys whose value should be masked when the API returns the current settings.
SECRET_KEYS = {
    "OPENAI_API_KEY",
    "HUGGINGFACE_API_KEY",
    "COHERE_API_KEY",
    "FMP_API_KEY",
    "STOCKTWITS_COOKIES",
    "DEEP_LLM_OPENAI_API_KEY",
}


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
    huggingface_api_key: str = ""
    huggingface_model: str = ""
    huggingface_base_url: str = ""
    cohere_api_key: str = ""
    cohere_model: str = ""
    cohere_base_url: str = ""
    # Deep Analysis LLM (advisor). Empty-string slots fall back to the
    # matching Agent LLM value via the deep_llm_* resolver properties.
    deep_llm_enabled: bool = False
    deep_llm_provider: str = ""
    deep_llm_ollama_host: str = ""
    deep_llm_ollama_model: str = ""
    deep_llm_openai_api_key: str = ""
    deep_llm_openai_model: str = ""
    deep_llm_openai_base_url: str = ""
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
    # Signal thresholds (allocator)
    agent_min_score: float = 0.0
    agent_min_confidence: float = 0.0
    agent_top_n_candidates: int = 0
    agent_llm_concurrency: int = 0
    # Scraper cadence
    agent_max_tweets_per_account: int = 0
    agent_lookback_hours: int = 0
    agent_per_account_timeout_s: int = 0
    poll_interval_seconds: int = 0
    # Manual order safety cap
    manual_order_max_notional: float = 0.0
    # Twitter
    twitter_accounts: str = ""
    # Swing-trading skill
    swing_enabled: bool = True
    swing_risk_per_trade_pct: float = 0.01
    swing_min_rr: float = 2.0
    swing_time_stop_days: int = 5
    swing_move_stop_be_pct: float = 0.08
    swing_partial_pct: float = 0.05
    swing_market_filter_symbol: str = "SPY"
    swing_market_filter_ma: int = 50
    swing_bar_lookback_days: int = 120
    # Auto-sell (max-hold window)
    auto_sell_enabled: bool = True
    auto_sell_max_hold_days: int = 30
    # Bookkeeping: which keys are overridden in the DB (vs env default)
    overridden: set[str] = field(default_factory=set)

    @property
    def twitter_accounts_list(self) -> list[str]:
        return [a.strip().lstrip("@") for a in self.twitter_accounts.split(",") if a.strip()]

    @property
    def llm_model(self) -> str:
        p = (self.llm_provider or "ollama").lower()
        if p == "openai":
            return self.openai_model
        if p == "huggingface":
            return self.huggingface_model
        if p == "cohere":
            return self.cohere_model
        return self.ollama_model

    @property
    def llm_host(self) -> str:
        p = (self.llm_provider or "ollama").lower()
        if p == "openai":
            return self.openai_base_url
        if p == "huggingface":
            return self.huggingface_base_url
        if p == "cohere":
            return self.cohere_base_url
        return self.ollama_host

    @property
    def llm_api_key(self) -> str:
        """Effective API key for the active Agent LLM provider (empty for Ollama)."""
        p = (self.llm_provider or "ollama").lower()
        if p == "openai":
            return self.openai_api_key
        if p == "huggingface":
            return self.huggingface_api_key
        if p == "cohere":
            return self.cohere_api_key
        return ""

    # -- Deep Analysis LLM resolvers --------------------------------------- #
    # Each returns the effective value used for the advisor call. When
    # DEEP_LLM_ENABLED is false OR any deep_* slot is blank, we fall back to
    # the corresponding Agent LLM setting so users can override only what
    # they care about (e.g. flip provider=openai while reusing the agent's
    # OPENAI_API_KEY).
    @property
    def advisor_provider(self) -> str:
        if not self.deep_llm_enabled:
            return self.llm_provider
        return (self.deep_llm_provider or self.llm_provider).lower()

    @property
    def advisor_model(self) -> str:
        if not self.deep_llm_enabled:
            return self.llm_model
        prov = self.advisor_provider
        if prov == "openai":
            return self.deep_llm_openai_model or self.openai_model
        return self.deep_llm_ollama_model or self.ollama_model

    @property
    def advisor_host(self) -> str:
        if not self.deep_llm_enabled:
            return self.llm_host
        prov = self.advisor_provider
        if prov == "openai":
            return self.deep_llm_openai_base_url or self.openai_base_url
        return self.deep_llm_ollama_host or self.ollama_host

    @property
    def advisor_api_key(self) -> str:
        if not self.deep_llm_enabled:
            return self.openai_api_key
        prov = self.advisor_provider
        if prov == "openai":
            return self.deep_llm_openai_api_key or self.openai_api_key
        return ""


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
        huggingface_api_key=str(pick("HUGGINGFACE_API_KEY", str)),
        huggingface_model=str(pick("HUGGINGFACE_MODEL", str)),
        huggingface_base_url=str(pick("HUGGINGFACE_BASE_URL", str)),
        cohere_api_key=str(pick("COHERE_API_KEY", str)),
        cohere_model=str(pick("COHERE_MODEL", str)),
        cohere_base_url=str(pick("COHERE_BASE_URL", str)),
        deep_llm_enabled=bool(pick("DEEP_LLM_ENABLED", bool)),
        deep_llm_provider=str(pick("DEEP_LLM_PROVIDER", str)),
        deep_llm_ollama_host=str(pick("DEEP_LLM_OLLAMA_HOST", str)),
        deep_llm_ollama_model=str(pick("DEEP_LLM_OLLAMA_MODEL", str)),
        deep_llm_openai_api_key=str(pick("DEEP_LLM_OPENAI_API_KEY", str)),
        deep_llm_openai_model=str(pick("DEEP_LLM_OPENAI_MODEL", str)),
        deep_llm_openai_base_url=str(pick("DEEP_LLM_OPENAI_BASE_URL", str)),
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
        agent_min_score=float(pick("AGENT_MIN_SCORE", float)),
        agent_min_confidence=float(pick("AGENT_MIN_CONFIDENCE", float)),
        agent_top_n_candidates=int(pick("AGENT_TOP_N_CANDIDATES", int)),
        agent_llm_concurrency=int(pick("AGENT_LLM_CONCURRENCY", int)),
        agent_max_tweets_per_account=int(pick("AGENT_MAX_TWEETS_PER_ACCOUNT", int)),
        agent_lookback_hours=int(pick("AGENT_LOOKBACK_HOURS", int)),
        agent_per_account_timeout_s=int(pick("AGENT_PER_ACCOUNT_TIMEOUT_S", int)),
        poll_interval_seconds=int(pick("POLL_INTERVAL_SECONDS", int)),
        manual_order_max_notional=float(pick("MANUAL_ORDER_MAX_NOTIONAL", float)),
        twitter_accounts=str(pick("TWITTER_ACCOUNTS", str)),
        swing_enabled=bool(pick("SWING_ENABLED", bool)),
        swing_risk_per_trade_pct=float(pick("SWING_RISK_PER_TRADE_PCT", float)),
        swing_min_rr=float(pick("SWING_MIN_RR", float)),
        swing_time_stop_days=int(pick("SWING_TIME_STOP_DAYS", int)),
        swing_move_stop_be_pct=float(pick("SWING_MOVE_STOP_BE_PCT", float)),
        swing_partial_pct=float(pick("SWING_PARTIAL_PCT", float)),
        swing_market_filter_symbol=str(pick("SWING_MARKET_FILTER_SYMBOL", str)),
        swing_market_filter_ma=int(pick("SWING_MARKET_FILTER_MA", int)),
        swing_bar_lookback_days=int(pick("SWING_BAR_LOOKBACK_DAYS", int)),
        auto_sell_enabled=bool(pick("AUTO_SELL_ENABLED", bool)),
        auto_sell_max_hold_days=int(pick("AUTO_SELL_MAX_HOLD_DAYS", int)),
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
        "huggingface_model": rs.huggingface_model,
        "huggingface_base_url": rs.huggingface_base_url,
        "huggingface_api_key_set": bool(rs.huggingface_api_key),
        "huggingface_api_key_preview": (
            (rs.huggingface_api_key[:6] + "..." + rs.huggingface_api_key[-4:])
            if len(rs.huggingface_api_key) >= 12
            else ("set" if rs.huggingface_api_key else "")
        ),
        "cohere_model": rs.cohere_model,
        "cohere_base_url": rs.cohere_base_url,
        "cohere_api_key_set": bool(rs.cohere_api_key),
        "cohere_api_key_preview": (
            (rs.cohere_api_key[:6] + "..." + rs.cohere_api_key[-4:])
            if len(rs.cohere_api_key) >= 12
            else ("set" if rs.cohere_api_key else "")
        ),
        "deep_llm_enabled": rs.deep_llm_enabled,
        "deep_llm_provider": rs.deep_llm_provider,
        "deep_llm_ollama_host": rs.deep_llm_ollama_host,
        "deep_llm_ollama_model": rs.deep_llm_ollama_model,
        "deep_llm_openai_model": rs.deep_llm_openai_model,
        "deep_llm_openai_base_url": rs.deep_llm_openai_base_url,
        "deep_llm_openai_api_key_set": bool(rs.deep_llm_openai_api_key),
        "deep_llm_openai_api_key_preview": (
            (rs.deep_llm_openai_api_key[:6] + "..." + rs.deep_llm_openai_api_key[-4:])
            if len(rs.deep_llm_openai_api_key) >= 12
            else ("set" if rs.deep_llm_openai_api_key else "")
        ),
        # What the advisor will actually use on the next run (post-fallback).
        "advisor_effective_provider": rs.advisor_provider,
        "advisor_effective_model": rs.advisor_model,
        "advisor_effective_host": rs.advisor_host,
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
        "agent_min_score": rs.agent_min_score,
        "agent_min_confidence": rs.agent_min_confidence,
        "agent_top_n_candidates": rs.agent_top_n_candidates,
        "agent_llm_concurrency": rs.agent_llm_concurrency,
        "agent_max_tweets_per_account": rs.agent_max_tweets_per_account,
        "agent_lookback_hours": rs.agent_lookback_hours,
        "agent_per_account_timeout_s": rs.agent_per_account_timeout_s,
        "poll_interval_seconds": rs.poll_interval_seconds,
        "manual_order_max_notional": rs.manual_order_max_notional,
        "twitter_accounts": rs.twitter_accounts,
        "swing_enabled": rs.swing_enabled,
        "swing_risk_per_trade_pct": rs.swing_risk_per_trade_pct,
        "swing_min_rr": rs.swing_min_rr,
        "swing_time_stop_days": rs.swing_time_stop_days,
        "swing_move_stop_be_pct": rs.swing_move_stop_be_pct,
        "swing_partial_pct": rs.swing_partial_pct,
        "swing_market_filter_symbol": rs.swing_market_filter_symbol,
        "swing_market_filter_ma": rs.swing_market_filter_ma,
        "swing_bar_lookback_days": rs.swing_bar_lookback_days,
        "auto_sell_enabled": rs.auto_sell_enabled,
        "auto_sell_max_hold_days": rs.auto_sell_max_hold_days,
        "overridden": sorted(rs.overridden),
    }
    return out


def keys() -> Iterable[str]:
    return EDITABLE_KEYS.keys()
