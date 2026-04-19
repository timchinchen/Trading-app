from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_MODE: Literal["paper", "live"] = "paper"

    ALPACA_PAPER_KEY: str = ""
    ALPACA_PAPER_SECRET: str = ""
    ALPACA_LIVE_KEY: str = ""
    ALPACA_LIVE_SECRET: str = ""

    MARKET_DATA_MODE: Literal["ws", "poll", "mixed"] = "mixed"
    POLL_INTERVAL_SECONDS: int = 5

    JWT_SECRET: str = "change_me"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    # Manual-order fat-finger cap. This is checked in addition to whatever
    # buying power Alpaca reports, so even if the broker would allow a
    # larger order, we reject anything above this cap. Editable at runtime
    # via the Settings UI. Default is deliberately small ($100) so a single
    # accidental click can't place a $5000 order.
    MANUAL_ORDER_MAX_NOTIONAL: float = 100.0

    CORS_ORIGIN: str = "http://localhost:5173"

    DATABASE_URL: str = "sqlite:///./trading.db"

    # ---- Agent ----
    AGENT_ENABLED: bool = False
    AGENT_AUTO_EXECUTE_LIVE: bool = False
    # Seed capital the agent is allowed to deploy in total (treated as a rolling
    # ceiling on the sum of new BUY notional across a calendar week).
    AGENT_BUDGET_USD: float = 200.0
    AGENT_WEEKLY_BUDGET_USD: float = 200.0
    # Per-position sizing band. Signals stronger than the baseline get sized
    # linearly up toward MAX; weaker signals stay at MIN. Anything below MIN
    # is skipped entirely.
    AGENT_MIN_POSITION_USD: float = 20.0
    AGENT_MAX_POSITION_USD: float = 40.0
    # Circuit breakers.
    AGENT_DAILY_LOSS_CAP_USD: float = 20.0
    AGENT_MAX_OPEN_POSITIONS: int = 6
    # Cadence / fetch windows.
    AGENT_CRON_MINUTES: int = 30
    AGENT_MAX_TWEETS_PER_ACCOUNT: int = 20
    AGENT_LOOKBACK_HOURS: int = 24
    AGENT_PER_ACCOUNT_TIMEOUT_S: int = 45
    # Signal thresholds (previously hard-coded in allocator.py).
    # Signals with score or confidence below these are filtered out entirely.
    AGENT_MIN_SCORE: float = 0.30
    AGENT_MIN_CONFIDENCE: float = 0.30
    # Max number of fresh-signal candidates the allocator considers per run.
    AGENT_TOP_N_CANDIDATES: int = 5
    # Max concurrent LLM calls when analysing tweets.
    AGENT_LLM_CONCURRENCY: int = 3
    # Market-intel corroboration: boost applied to a ticker's confidence when
    # the intel sources independently flag it (movers list, TradingView news).
    AGENT_INTEL_BOOST: float = 0.15
    # Take-profit: if a held position is up at least this fraction vs entry,
    # emit a SELL-to-close proposal (e.g. 0.10 = +10%). 0 disables.
    AGENT_TAKE_PROFIT_PCT: float = 0.10
    # Don't re-buy a symbol that was BOUGHT within the last N hours - we're
    # hunting for fresh ideas, not doubling down on the same tickets.
    AGENT_RECENT_TRADE_WINDOW_HOURS: int = 24

    # ---- LLM provider ----
    # "ollama" (default, local) or "openai" (hosted, requires OPENAI_API_KEY).
    # This is the default; the user can override it at runtime from the
    # Settings page (persisted in the AppSetting table).
    LLM_PROVIDER: Literal["ollama", "openai"] = "ollama"

    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # ---- Deep Analysis LLM (advisor / portfolio recommender) ----
    # When enabled, the end-of-run advisor call uses a second, independent LLM
    # slot instead of the Agent LLM above. This is cheap (~1 call per agent run)
    # and lets you pair a free local model for tweet-level analysis with a
    # stronger hosted model for the big-picture summary. When disabled, every
    # DEEP_LLM_* value falls back to the corresponding Agent LLM setting, so
    # nothing changes.
    DEEP_LLM_ENABLED: bool = False
    DEEP_LLM_PROVIDER: Literal["ollama", "openai"] = "openai"
    DEEP_LLM_OLLAMA_HOST: str = ""          # empty => reuse OLLAMA_HOST
    DEEP_LLM_OLLAMA_MODEL: str = ""         # empty => reuse OLLAMA_MODEL
    DEEP_LLM_OPENAI_API_KEY: str = ""       # empty => reuse OPENAI_API_KEY
    DEEP_LLM_OPENAI_MODEL: str = "gpt-4o-mini"
    DEEP_LLM_OPENAI_BASE_URL: str = ""      # empty => reuse OPENAI_BASE_URL

    # ---- Per-ticker enrichment sources ----
    # Financial Modeling Prep (fundamentals: quote, profile, ratios).
    # Free tier is 250 calls/day. Leave empty to disable.
    FMP_API_KEY: str = ""
    FMP_BASE_URL: str = "https://financialmodelingprep.com/api/v3"
    # SEC EDGAR full-text search (free). The SEC requires a User-Agent
    # identifying the caller - put a contact email here.
    SEC_USER_AGENT: str = "TradingApp (personal use) noreply@example.com"
    # Stocktwits session cookies (sentiment + news-articles). Stocktwits is
    # behind Cloudflare - we drive it via Playwright with your logged-in
    # cookies. Paste a Netscape-format blob or a JSON dict of cookies from
    # DevTools. Leave empty to disable the source.
    STOCKTWITS_COOKIES: str = ""

    TWSCRAPE_DB: str = "./twscrape.db"
    TWITTER_ACCOUNTS: str = ""

    @property
    def twitter_accounts_list(self) -> list[str]:
        return [a.strip().lstrip("@") for a in self.TWITTER_ACCOUNTS.split(",") if a.strip()]

    @property
    def alpaca_key(self) -> str:
        return self.ALPACA_LIVE_KEY if self.APP_MODE == "live" else self.ALPACA_PAPER_KEY

    @property
    def alpaca_secret(self) -> str:
        return self.ALPACA_LIVE_SECRET if self.APP_MODE == "live" else self.ALPACA_PAPER_SECRET

    @property
    def is_paper(self) -> bool:
        return self.APP_MODE == "paper"


settings = Settings()
