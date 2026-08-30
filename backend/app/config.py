import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


# Kept in lockstep with frontend/src/version.ts (X.Y user-controlled,
# Z droid-controlled - bumped on every droid-authored edit). Reported
# by /health/setup so the Prerequisites panel can show the same version
# badge the Settings page does.
APP_VERSION_BACKEND = "1.4.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_MODE: Literal["paper", "live"] = "paper"

    ALPACA_PAPER_KEY: str = ""
    ALPACA_PAPER_SECRET: str = ""
    ALPACA_LIVE_KEY: str = ""
    ALPACA_LIVE_SECRET: str = ""

    MARKET_DATA_MODE: Literal["ws", "poll", "mixed"] = "mixed"
    POLL_INTERVAL_SECONDS: int = 5
    # Alpaca free-tier IEX WS caps at 30 symbols. Symbols beyond this limit
    # are automatically served via REST polling. Set 0 for unlimited (paid).
    WS_MAX_SYMBOLS: int = 30
    # Hard cap on watchlist size. Prevents unbounded growth from the agent
    # auto-adding symbols every run. 0 = unlimited.
    WATCHLIST_MAX_SYMBOLS: int = 60

    JWT_SECRET: str = "change_me"
    JWT_EXPIRE_MINUTES: int = 60 * 24
    # Public signup gate. Keep true for first-time setup, then disable from
    # Settings once your account is created if the app is internet-exposed.
    REGISTRATION_ENABLED: bool = True

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
    # Hard timeout for a single agent run (seconds). If exceeded, the run is
    # cancelled and marked error so it doesn't sit in "running" forever.
    AGENT_RUN_TIMEOUT_S: int = 1200
    AGENT_MAX_TWEETS_PER_ACCOUNT: int = 20
    AGENT_LOOKBACK_HOURS: int = 24
    AGENT_PER_ACCOUNT_TIMEOUT_S: int = 45
    # Signal thresholds (previously hard-coded in allocator.py).
    # Signals with score or confidence below these are filtered out entirely.
    # Raised from 0.30 → 0.45 / 0.50: only high-conviction signals get capital.
    AGENT_MIN_SCORE: float = 0.45
    AGENT_MIN_CONFIDENCE: float = 0.50
    # Max number of fresh-signal candidates the allocator considers per run.
    # Reduced from 5 → 3: pick fewer, better entries rather than spreading thin.
    AGENT_TOP_N_CANDIDATES: int = 3
    # Max concurrent LLM calls when analysing tweets.
    AGENT_LLM_CONCURRENCY: int = 3
    # Market-intel corroboration: boost applied to a ticker's confidence when
    # the intel sources independently flag it (movers list, TradingView news).
    AGENT_INTEL_BOOST: float = 0.15
    # Take-profit: if a held position is up at least this fraction vs entry,
    # emit a SELL-to-close proposal (e.g. 0.10 = +10%). 0 disables.
    AGENT_TAKE_PROFIT_PCT: float = 0.10
    # Stop-loss: if a held position is *down* at least this fraction vs entry,
    # emit a SELL-to-close proposal (e.g. 0.05 = -5%). 0 disables. Mirrors
    # AGENT_TAKE_PROFIT_PCT on the downside.
    AGENT_STOP_LOSS_PCT: float = 0.05
    # Don't re-buy a symbol that was BOUGHT within the last N hours - we're
    # hunting for fresh ideas, not doubling down on the same tickets.
    AGENT_RECENT_TRADE_WINDOW_HOURS: int = 24
    # When True (default), sell proceeds are subtracted from "used" budget,
    # allowing same-day redeployment. When False, budget tracks gross buys only.
    AGENT_NET_BUDGET_ACCOUNTING: bool = True
    # Append weekly-learned bullets to ROLE_PREAMBLE (never rewrites core rules).
    AGENT_DYNAMIC_PREAMBLE_ENABLED: bool = True
    AGENT_WEEKLY_LESSON_MAX_CHARS: int = 800

    # ---- Source reliability weighting ----
    # JSON object mapping handle -> weight multiplier. Missing handles get 1.0.
    # Clamp [0.5, 2.0]. Example: '{"PeterLBrandt":1.25,"random":0.8}'
    AGENT_HANDLE_WEIGHTS: str = "{}"

    # ---- Deterministic pre-LLM scoring (staged rollout) ----
    # Adds a transparent composite score ahead of allocator/advisor flows.
    # Disabled by default to preserve current behavior.
    AGENT_PRE_LLM_SCORING_ENABLED: bool = False
    # If enabled, overwrite legacy signal["score"] with the deterministic
    # composite mapped to [-1, 1]. Keep False during rollout.
    AGENT_PRE_LLM_SCORING_OVERRIDE_SCORE: bool = False
    AGENT_RS_BENCHMARK_SYMBOL: str = "SPY"
    AGENT_RS_LOOKBACK_DAYS: int = 120
    AGENT_SCORING_WEIGHT_RELATIVE_STRENGTH: float = 0.30
    AGENT_SCORING_WEIGHT_TREND_QUALITY: float = 0.25
    AGENT_SCORING_WEIGHT_VOLUME_EXPANSION: float = 0.20
    AGENT_SCORING_WEIGHT_SENTIMENT: float = 0.15
    AGENT_SCORING_WEIGHT_CATALYST_STRENGTH: float = 0.10

    # ---- Regime-adaptive sizing ----
    # Slot multiplier per regime tier (price vs MA + slope direction).
    AGENT_REGIME_RISK_ON_MULT: float = 1.25   # price > MA, MA rising
    AGENT_REGIME_NEUTRAL_MULT: float = 1.0    # price > MA or MA flat
    AGENT_REGIME_RISK_OFF_MULT: float = 0.5   # price < MA, MA falling
    # When True, block ALL new BUYs in risk_off regime (exits still run).
    AGENT_RISK_OFF_BLOCK_NEW_BUYS: bool = True

    # ---- Regime / data-completeness buy gate ("confirm first, then execute") ----
    # Hard-block new BUYs unless the market regime is GO or CAUTION (never
    # NO-GO). When False, falls back to the legacy "full GO only" gate.
    AGENT_REQUIRE_REGIME_CONFIRMATION: bool = True
    # When True, hard-block new BUYs while the market-filter (SPY) feed is
    # incomplete. When False (default), incomplete data downgrades to CAUTION
    # sizing (half slot, tighter book) instead of stopping. Exits are never
    # blocked.
    AGENT_REQUIRE_COMPLETE_DATA_FOR_BUYS: bool = False
    # Extra slot multiplier applied on top of the regime tier when SPY data is
    # incomplete but buys are still allowed (mitigation mode).
    AGENT_INCOMPLETE_DATA_SIZE_MULT: float = 0.5
    # Treat the SPY series as stale (data incomplete) if the most recent bar is
    # older than this many calendar days. 4 covers a normal long weekend.
    AGENT_REGIME_STALE_BARS_DAYS: int = 4
    # Reduce auto-entry frequency: cap how many *new* BUY positions the agent
    # auto-executes per run. Extra qualifying setups are surfaced as proposals
    # for the operator instead of firing. 0 = unlimited (legacy behaviour).
    AGENT_MAX_NEW_POSITIONS_PER_RUN: int = 2
    # Focus the portfolio in CAUTION regime: tighten the open-position ceiling
    # so the book stays on fewer, higher-conviction names. 0 = reuse
    # AGENT_MAX_OPEN_POSITIONS (no extra tightening).
    AGENT_CAUTION_MAX_OPEN_POSITIONS: int = 3
    # CAUTION-tier execution (turns the advisor's "half size, stricter" language
    # into real sizing). Applied to swing entries when regime tier == caution.
    AGENT_CAUTION_SIZE_MULT: float = 0.5          # 50% size in CAUTION
    AGENT_CAUTION_MIN_RR: float = 3.0             # stricter R/R floor in CAUTION
    # Opt-in: require tweet/intel corroboration for a CAUTION-tier swing entry.
    AGENT_CAUTION_REQUIRE_CORROBORATION: bool = False

    # ---- Plan backfill (cover manual/tweet/legacy positions) ----
    # Synthesize an AgentPositionPlan for any open broker position that lacks
    # one, so the adaptive exit + invalidation engine manages every position
    # instead of falling back to the weaker static TP/SL sweep.
    AGENT_PLAN_BACKFILL_ENABLED: bool = True
    AGENT_PLAN_BACKFILL_STOP_PCT: float = 0.05    # default stop = entry * (1 - 5%)
    AGENT_PLAN_BACKFILL_TARGET_PCT: float = 0.10  # default target = entry * (1 + 10%)

    # ---- Thesis-invalidation exits ("cut losers when the setup breaks") ----
    AGENT_INVALIDATION_EXITS_ENABLED: bool = True
    AGENT_INVALIDATION_SMA_PERIOD: int = 20
    # Soft invalidation: this many consecutive daily closes below the SMA.
    AGENT_INVALIDATION_CONSEC_CLOSES: int = 2
    # Hard invalidation on a single close below the SMA *only* when weakness is
    # confirmed (failed breakout back in range, or a decisive down-day break).
    AGENT_INVALIDATION_FIRST_CLOSE_ON_CONFIRMED: bool = True
    # Min unrealized progress below which a time-stop fires (was hard-coded 0.02).
    SWING_TIME_STOP_MIN_PROGRESS_PCT: float = 0.02

    # ---- Watchlist hygiene ----
    # Which symbols the agent auto-adds to the dashboard watchlist each run.
    #   all      = legacy behaviour (executed/proposed/skipped setups + scans)
    #   proposed = only executed buys, proposed buys, and exit candidates
    #   executed = only symbols the agent actually traded
    AGENT_WATCHLIST_AUTOADD_MODE: Literal["all", "proposed", "executed"] = "all"
    # Don't re-add a symbol auto-removed/added within this cooldown. 0 = off.
    AGENT_WATCHLIST_COOLDOWN_HOURS: int = 0

    # ---- Auto-execution controls ----
    # Allow paper mode to run propose-only (mirrors live). Default True keeps
    # the existing paper auto-execute behaviour.
    AGENT_AUTO_EXECUTE_PAPER: bool = True
    # Skip the same-run second allocation pass that redeploys freed sell
    # proceeds immediately (a churn source). Default False = legacy behaviour.
    AGENT_DISABLE_SAME_RUN_REDEPLOY: bool = False

    # ---- Optional SPY intraday confirmation (Phase 5) ----
    # When True, fetch SPY 1-minute bars and use them ONLY to confirm/downgrade
    # the daily regime (never to hard-block buys). Default False = no change.
    AGENT_USE_INTRADAY_CONFIRMATION: bool = False
    AGENT_INTRADAY_LOOKBACK_MINUTES: int = 390     # one full RTH session

    # ---- Adaptive exit engine ----
    # Arm trailing-retrace logic once unrealized gain reaches this level.
    # Tightened from 0.05 → 0.04: protect gains sooner.
    AGENT_TRAIL_ARM_PCT: float = 0.04         # 4% gain arms trailing
    # Exit if current gain retraces this fraction from peak armed gain.
    # Tightened from 0.35 → 0.30: cut faster when momentum fades.
    AGENT_TRAIL_RETRACE_PCT: float = 0.30     # 30% retrace from peak
    # First partial-TP at this gain; sells PARTIAL_TAKE_FRACTION of position.
    # Tightened from 0.07 → 0.06: bank first partial slightly earlier.
    AGENT_PARTIAL_TAKE_PCT: float = 0.06      # 6%
    AGENT_PARTIAL_TAKE_FRACTION: float = 0.5  # sell 50%
    # Minimum hold before any *non-hard-stop* exit may fire. Six exit paths
    # compete to close every position; without a floor they routinely close a
    # position in the same 30-min cycle it was opened (buy → time/momentum/
    # invalidation exit → re-buy). A hard stop is the only exit allowed to fire
    # inside this window. Set 0 to disable the guard (legacy behaviour).
    AGENT_MIN_HOLD_HOURS: int = 24
    # Hard time-stop: close any position older than this many calendar days.
    # Set to 21 days so default exits align with a 2-3 week swing horizon.
    AGENT_MAX_HOLD_DAYS: int = 21
    # Prompt guidance knob: advisor/preamble language references this as the
    # no-progress time-stop horizon to avoid hard-coded day ranges in prompts.
    AGENT_PROMPT_TIME_STOP_DAYS: int = 21

    # ---- Swing-trading skill (1-2 week horizon) ----
    # Master toggle. When off the agent falls back to the old tweet-sentiment
    # + sizing-by-strength flow.
    SWING_ENABLED: bool = True
    # Risk-based sizing: per-trade dollar risk = SWING_RISK_PER_TRADE_PCT of
    # total capital (AGENT_BUDGET_USD). Shares = risk / (entry - stop).
    SWING_RISK_PER_TRADE_PCT: float = 0.01          # 1%
    # Reject setups whose reward/risk ratio is below this.
    # Raised from 2.0 → 2.5: only take swings with good upside vs defined risk.
    SWING_MIN_RR: float = 2.5
    # Time-stop in trading days. If a position has made no progress by then,
    # the next run emits an EXIT proposal.
    SWING_TIME_STOP_DAYS: int = 10
    # Move stop to breakeven once unrealised P/L hits this fraction.
    # DEPRECATED as a trigger: an absolute +8% breakeven bump against setups
    # that target entry*1.10 converts winners into scratches two points short
    # of target on any normal retrace. The breakeven trigger now uses
    # SWING_MOVE_STOP_BE_TARGET_FRAC (fraction of the distance to target)
    # instead; this value is retained only for backward-compat / display.
    SWING_MOVE_STOP_BE_PCT: float = 0.08
    # Move stop to breakeven once price has covered this fraction of the
    # entry→target distance (0.5 = halfway to target). Scales with each setup's
    # own target instead of a fixed percentage, so a 10%-target trade arms
    # breakeven at +5% and a 6%-target trade at +3%.
    SWING_MOVE_STOP_BE_TARGET_FRAC: float = 0.5
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
    # Backstop auto-sell tightened from 30 → 14 days: for swing trading,
    # a position that hasn't worked in 2 weeks is dead money.
    AUTO_SELL_MAX_HOLD_DAYS: int = 14

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
    # Pick a model the HF router actually exposes on /v1/chat/completions.
    # Mistral-7B-Instruct-v0.3 was removed from the routed list (router
    # responds 400 "not a chat model"). Llama-3.1-8B-Instruct is currently
    # served free via novita / cerebras / nscale / scaleway / featherless.
    HUGGINGFACE_MODEL: str = "meta-llama/Llama-3.1-8B-Instruct"
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
    # Alpha Vantage fundamentals + quote enrichment. Free tier = 25 calls/day.
    # Grab a key at https://www.alphavantage.co/support/#api-key
    ALPHA_VANTAGE_API_KEY: str = ""
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

    # --- Playwright / X scraping (optional; defaults preserve legacy behaviour) ---
    # Absolute or relative path to system Chromium — recommended on Raspberry Pi
    # where Playwright-bundled Chromium may misbehave (e.g. /usr/bin/chromium).
    PLAYWRIGHT_CHROMIUM_EXECUTABLE: str = ""
    # Playwright storage_state JSON — skip twscrape sqlite injection when this file exists.
    # Generate once from a logged-in browser session (see docs/X_TWITTER_PLAYWRIGHT.md).
    PLAYWRIGHT_STORAGE_STATE_PATH: str = ""
    # Recommended True on Pi / headless ARM hosts (--disable-gpu).
    PLAYWRIGHT_DISABLE_GPU: bool = False
    # Override User-Agent (empty => macOS-like on Darwin, Linux aarch64 UA elsewhere).
    PLAYWRIGHT_USER_AGENT: str = ""
    # After primary DOM scrape returns 0 tweets, retry once with relaxed waits / load event.
    # Default False preserves legacy behaviour (single browser session) when unset in .env.
    PLAYWRIGHT_RELAXED_FALLBACK: bool = False

    @property
    def twitter_accounts_list(self) -> list[str]:
        return [a.strip().lstrip("@") for a in self.TWITTER_ACCOUNTS.split(",") if a.strip()]

    @property
    def twscrape_db_abspath(self) -> str:
        """Absolute path to the twscrape SQLite file as resolved from the process cwd.

        Relative ``TWSCRAPE_DB`` values (for example ``./twscrape.db``) depend on the
        current working directory when the backend starts — not on the location of
        ``.env``. Use an absolute path in production if cwd may vary.
        """
        raw = (self.TWSCRAPE_DB or "").strip() or "./twscrape.db"
        return os.path.abspath(os.path.expanduser(raw))

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
