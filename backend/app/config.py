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

    MAX_ORDER_NOTIONAL: float = 5000.0

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
