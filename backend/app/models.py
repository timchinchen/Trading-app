from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    watchlist = relationship("WatchlistItem", back_populates="user", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String, nullable=False, index=True)
    feed = Column(String, nullable=False, default="ws")  # "ws" | "poll"

    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_symbol"),)
    user = relationship("User", back_populates="watchlist")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    alpaca_id = Column(String, index=True)
    symbol = Column(String, nullable=False, index=True)
    qty = Column(Float, nullable=False)
    side = Column(String, nullable=False)         # buy | sell
    type = Column(String, nullable=False)         # market | limit
    limit_price = Column(Float)
    status = Column(String, nullable=False, default="new")
    mode = Column(String, nullable=False)         # paper | live
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Populated once Alpaca fills (wholly or partially). Reconciled on every
    # GET /orders request for rows that still show new/accepted/partially_*.
    filled_avg_price = Column(Float)
    filled_qty = Column(Float)
    filled_at = Column(DateTime)


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    alpaca_id = Column(String, index=True)
    symbol = Column(String, nullable=False, index=True)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    side = Column(String, nullable=False)
    filled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    mode = Column(String, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    finished_at = Column(DateTime)
    mode = Column(String, nullable=False)                  # paper | live
    status = Column(String, nullable=False, default="running")  # running|ok|error|skipped
    tweets_fetched = Column(Integer, default=0)
    accounts_scanned = Column(Integer, default=0)
    trades_proposed = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)
    summary = Column(String)                               # LLM summary / error msg
    logs = Column(String)                                  # freeform newline-delimited debug log
    advice = Column(String)                                # structured portfolio recommendation (advisor LLM)
    intel_brief = Column(String)                           # compact market-intel snapshot captured this run


class AgentSignal(Base):
    __tablename__ = "agent_signals"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), index=True, nullable=False)
    symbol = Column(String, nullable=False, index=True)
    score = Column(Float, nullable=False)                  # -1.0 ... +1.0
    confidence = Column(Float, nullable=False, default=0.0)
    mentions = Column(Integer, default=0)
    rationale = Column(String)                             # aggregated LLM rationale
    sources = Column(String)                               # JSON list of {handle, tweet_id, url, excerpt}


class AgentTrade(Base):
    __tablename__ = "agent_trades"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), index=True, nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), index=True)  # null if proposal only
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    est_price = Column(Float)
    notional = Column(Float)
    action = Column(String, nullable=False)                # proposed | executed | skipped
    reason = Column(String)
    mode = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Swing-trading plan snapshot at the moment this trade was emitted.
    # Persisted so the Agent UI can show setup/stop/target and the trade-
    # management pass on the next run can detect stop-hits without refetching.
    setup_type = Column(String)
    entry_price = Column(Float)
    stop_price = Column(Float)
    target_price = Column(Float)
    risk_reward = Column(Float)


class AgentPositionPlan(Base):
    """Per-symbol swing plan for a currently-open position. One row per symbol
    (latest-wins) so the trade-management pass can answer:
      - has the stop been hit?
      - is the position up enough to move stop to breakeven?
      - is the position past its time stop?
    Written by the runner when a BUY plan is proposed/executed; cleared
    (status='closed') when the position is exited.
    """
    __tablename__ = "agent_position_plans"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True, unique=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), index=True)
    setup_type = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)
    risk_reward = Column(Float, nullable=False)
    opened_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    breakeven_moved = Column(Integer, default=0, nullable=False)  # 0|1
    partial_taken = Column(Integer, default=0, nullable=False)    # 0|1
    # Peak unrealized gain fraction seen so far (e.g. 0.12 = +12%). Updated
    # every run while position is open. Used by the adaptive trailing-stop
    # engine to detect momentum fade: if peak was 0.10 and current is 0.065,
    # the retrace is 35% of peak → trailing exit fires.
    peak_unrealized_plpc = Column(Float, default=0.0, nullable=False)
    status = Column(String, default="open", nullable=False)       # open|closed
    notes = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AppSetting(Base):
    """Runtime-editable key/value overrides on top of .env defaults.

    Anything stored here wins over the corresponding env var. Used by the
    Settings page so the user can switch LLM provider, edit X handles, tune
    budgets, etc. without restarting uvicorn.
    """
    __tablename__ = "app_settings"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TwitterUserCache(Base):
    __tablename__ = "twitter_user_cache"
    handle = Column(String, primary_key=True)          # lowercase
    user_id = Column(String, nullable=False)
    resolved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    not_found = Column(Integer, default=0, nullable=False)  # 1 if X said 'not found'


class DigestEntry(Base):
    """Append-only rolling log of notable events the agent, advisor, order
    pipeline, and scrapers emit. Pruned after ~7 days (compressed into
    DailyDigest rows before deletion) so we keep the raw log small and rely
    on the daily summaries for long-term memory.
    """
    __tablename__ = "digest_entries"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    # agent_run | advisor | trade_exec | swing_setup | regime_flip |
    # intel_highlight | watchlist_delta | settings_change | error
    symbol = Column(String, index=True)      # optional ticker focus
    summary = Column(String, nullable=False) # short human-readable one-liner
    data_json = Column(String)               # optional JSON payload for richer context


class DailyDigest(Base):
    """Compressed daily trading memory. Produced once per trading day at the
    09:30 ET open by the Deep Analysis LLM, covering the last 7 days of
    DigestEntry rows. These rows are kept forever and are what the advisor
    sees as long-term memory on every subsequent run.
    """
    __tablename__ = "daily_digests"
    id = Column(Integer, primary_key=True)
    trade_date = Column(String, nullable=False, unique=True, index=True)  # YYYY-MM-DD (US/Eastern)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    entries_covered = Column(Integer, default=0, nullable=False)
    window_start = Column(DateTime)         # first entry covered (UTC)
    window_end = Column(DateTime)           # last entry covered (UTC)
    model_used = Column(String)             # provider:model string that produced this digest
    text = Column(String, nullable=False)   # the compressed paragraph shown on the dashboard


class AgentTweetAnalysis(Base):
    __tablename__ = "agent_tweet_analyses"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), index=True, nullable=False)
    handle = Column(String, nullable=False, index=True)
    tweet_id = Column(String, nullable=False)
    tweet_url = Column(String)
    tweet_text = Column(String)
    tweet_created_at = Column(String)                  # iso string
    analysis_json = Column(String)                     # raw LLM JSON output
    tickers_count = Column(Integer, default=0)
    is_noise = Column(Integer, default=0)
    error = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
