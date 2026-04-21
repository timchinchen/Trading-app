from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


# Kept in lockstep with frontend/src/version.ts (X.Y user-controlled,
# Z droid-controlled - bumped on every droid-authored edit). Reported
# by /health/setup so the Prerequisites panel can show the same version
# badge the Settings page does.
APP_VERSION_BACKEND = "1.0.4"


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

    # ---- Swing-trading skill (1-2 week horizon) ----
    # Master toggle. When off the agent falls back to the old tweet-sentiment
    # + sizing-by-strength flow.
    SWING_ENABLED: bool = True
    # Risk-based sizing: per-trade dollar risk = SWING_RISK_PER_TRADE_PCT of
    # total capital (AGENT_BUDGET_USD). Shares = risk / (entry - stop).
    SWING_RISK_PER_TRADE_PCT: float = 0.01          # 1%
    # Reject setups whose reward/risk ratio is below this.
    SWING_MIN_RR: float = 2.0
    # Time-stop in trading days. If a position has made no progress by then,
    # the next run emits an EXIT proposal.
    SWING_TIME_STOP_DAYS: int = 5
    # Move stop to breakeven once unrealised P/L hits this fraction.
    SWING_MOVE_STOP_BE_PCT: float = 0.08
    # Flag partial profit-take at this gain (no auto-sell; advisor surface it).
    SWING_PARTIAL_PCT: float = 0.05
    # Market regime filter symbol and MA window. If price < MA or MA slope
    # is falling we block ALL new BUYs for the run.
    SWING_MARKET_FILTER_SYMBOL: str = "SPY"
    SWING_MARKET_FILTER_MA: int = 50
    # Bar lookback for technical scan (daily bars).
    SWING_BAR_LOOKBACK_DAYS: int = 120

    # ---- Auto-sell (max-hold window) ----
    # Daily scan that closes any open position held longer than the cap.
    # Pure risk-hygiene control: if we've been in a name for a month and
    # nothing exciting has happened, cut it and redeploy the cash. Runs at
    # 09:45 US/Eastern on weekdays; paper mode auto-executes, live mode
    # proposes unless AGENT_AUTO_EXECUTE_LIVE is also on.
    AUTO_SELL_ENABLED: bool = True
    AUTO_SELL_MAX_HOLD_DAYS: int = 30

    # ---- LLM provider ----
    # One of: "ollama" (default, local), "openai" (hosted, requires key),
    # "huggingface" (HF Inference API, free serverless tier), or "cohere"
    # (Cohere chat API, free trial tier). Switch at runtime from Settings.
    LLM_PROVIDER: Literal["ollama", "openai", "huggingface", "cohere"] = "ollama"

    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # Hugging Face Inference Providers (free tier). Uses the OpenAI-compatible
    # router at router.huggingface.co/v1 (the legacy api-inference.huggingface.co
    # serverless endpoint was retired in early 2026). Pick a chat-tuned
    # Instruct model. First call after idle can cold-start ~20s;
    # _chat() retries once on the "model is loading" 503.
    HUGGINGFACE_API_KEY: str = ""
    HUGGINGFACE_MODEL: str = "mistralai/Mistral-7B-Instruct-v0.3"
    HUGGINGFACE_BASE_URL: str = "https://router.huggingface.co/v1"

    # Cohere chat API (free trial tier: 1000 calls/month, 20/min).
    # command-r-08-2024 is the cheapest useful chat model. The rate limit
    # is fine for the once-per-run Deep Analysis LLM (advisor), but hits
    # the 20/min ceiling if used as the Agent LLM (20-60 tweet calls/run).
    COHERE_API_KEY: str = ""
    COHERE_MODEL: str = "command-r-08-2024"
    COHERE_BASE_URL: str = "https://api.cohere.com/v1"

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
