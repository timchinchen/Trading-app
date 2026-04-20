from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    mode: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    class Config:
        from_attributes = True


class WatchlistItemIn(BaseModel):
    symbol: str
    feed: Literal["ws", "poll"] = "ws"


class WatchlistItemOut(BaseModel):
    id: int
    symbol: str
    feed: str
    open: Optional[float] = None
    prev_close: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    class Config:
        from_attributes = True


class OrderIn(BaseModel):
    symbol: str
    qty: float = Field(gt=0)
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"] = "market"
    limit_price: Optional[float] = None


class OrderOut(BaseModel):
    id: int
    alpaca_id: Optional[str]
    symbol: str
    qty: float
    side: str
    type: str
    limit_price: Optional[float]
    status: str
    mode: str
    submitted_at: datetime
    # Fill info reconciled from Alpaca (null until accepted+filled).
    filled_avg_price: Optional[float] = None
    filled_qty: Optional[float] = None
    filled_at: Optional[datetime] = None
    total_cost: Optional[float] = None       # filled_avg_price * filled_qty
    # Live-ish enrichment (sourced from the shared snapshot cache so the
    # Orders tab doesn't cost extra Alpaca round-trips).
    current_price: Optional[float] = None
    pct_change: Optional[float] = None       # (current - fill) / fill * 100
    class Config:
        from_attributes = True


class AccountOut(BaseModel):
    cash: float
    buying_power: float
    portfolio_value: float
    currency: str
    mode: str


class PositionOut(BaseModel):
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float
    current_price: float


class QuoteOut(BaseModel):
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    ts: Optional[datetime] = None


class ModeOut(BaseModel):
    mode: str
    market_data_mode: str
    max_order_notional: float


class AgentStatusOut(BaseModel):
    enabled: bool
    mode: str
    auto_execute_live: bool
    budget_usd: float
    weekly_budget_usd: float
    min_position_usd: float
    max_position_usd: float
    daily_loss_cap_usd: float
    max_open_positions: int
    cron_minutes: int
    accounts: list[str]
    ollama_host: str
    ollama_model: str
    last_run_id: Optional[int] = None
    last_run_started_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    next_run_at: Optional[datetime] = None


class AgentRunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    mode: str
    status: str
    tweets_fetched: int
    accounts_scanned: int
    trades_proposed: int
    trades_executed: int
    summary: Optional[str]
    logs: Optional[str] = None
    advice: Optional[str] = None
    intel_brief: Optional[str] = None
    class Config:
        from_attributes = True


class AgentSignalOut(BaseModel):
    id: int
    run_id: int
    symbol: str
    score: float
    confidence: float
    mentions: int
    rationale: Optional[str]
    sources: Optional[str]
    class Config:
        from_attributes = True


class AgentTradeOut(BaseModel):
    id: int
    run_id: int
    order_id: Optional[int]
    symbol: str
    side: str
    qty: float
    est_price: Optional[float]
    notional: Optional[float]
    action: str
    reason: Optional[str]
    mode: str
    created_at: datetime
    class Config:
        from_attributes = True


class AgentAccountsIn(BaseModel):
    accounts: list[str]


class AgentAccountCacheOut(BaseModel):
    handle: str
    user_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
    not_found: bool = False
    in_config: bool = True


class AgentTweetAnalysisOut(BaseModel):
    id: int
    run_id: int
    handle: str
    tweet_id: str
    tweet_url: Optional[str]
    tweet_text: Optional[str]
    tweet_created_at: Optional[str]
    analysis_json: Optional[str]
    tickers_count: int
    is_noise: bool
    error: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True


class ChatMessage(BaseModel):
    role: str        # "user" | "assistant" | "system"
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage]
    system: Optional[str] = None
    model: Optional[str] = None   # override default
    temperature: float = 0.2


class ChatOut(BaseModel):
    role: str
    content: str
    model: str
    duration_ms: int
