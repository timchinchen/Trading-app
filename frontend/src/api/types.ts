export interface Mode {
  mode: 'paper' | 'live'
  market_data_mode: 'ws' | 'poll' | 'mixed'
  max_order_notional: number
}

export interface Account {
  cash: number
  buying_power: number
  portfolio_value: number
  currency: string
  mode: string
}

export interface Position {
  symbol: string
  qty: number
  avg_entry_price: number
  market_value: number
  unrealized_pl: number
  current_price: number
}

export interface Order {
  id: number
  alpaca_id?: string | null
  symbol: string
  qty: number
  side: 'buy' | 'sell'
  type: 'market' | 'limit'
  limit_price?: number | null
  status: string
  mode: string
  submitted_at: string
  // Populated once the order is accepted / filled by Alpaca.
  filled_avg_price?: number | null
  filled_qty?: number | null
  filled_at?: string | null
  total_cost?: number | null
  current_price?: number | null
  pct_change?: number | null
}

export interface WatchlistItem {
  id: number
  symbol: string
  feed: 'ws' | 'poll'
  open?: number | null
  prev_close?: number | null
  day_high?: number | null
  day_low?: number | null
}

export interface Quote {
  symbol: string
  bid?: number | null
  ask?: number | null
  last?: number | null
  ts?: string
}

export interface AgentStatus {
  enabled: boolean
  mode: string
  auto_execute_live: boolean
  budget_usd: number
  weekly_budget_usd: number
  min_position_usd: number
  max_position_usd: number
  daily_loss_cap_usd: number
  max_open_positions: number
  cron_minutes: number
  accounts: string[]
  ollama_host: string
  ollama_model: string
  last_run_id: number | null
  last_run_started_at: string | null
  last_run_status: string | null
  next_run_at: string | null
  auto_sell_enabled: boolean
  auto_sell_max_hold_days: number
  next_auto_sell_at: string | null
}

export interface AgentRun {
  id: number
  started_at: string
  finished_at?: string | null
  mode: string
  status: string
  tweets_fetched: number
  accounts_scanned: number
  trades_proposed: number
  trades_executed: number
  summary?: string | null
  logs?: string | null
  advice?: string | null
  intel_brief?: string | null
}

export interface AgentSignal {
  id: number
  run_id: number
  symbol: string
  score: number
  confidence: number
  mentions: number
  rationale?: string | null
  sources?: string | null
}

export interface AgentTrade {
  id: number
  run_id: number
  order_id?: number | null
  symbol: string
  side: string
  qty: number
  est_price?: number | null
  notional?: number | null
  action: string
  reason?: string | null
  mode: string
  created_at: string
  // Swing-skill plan snapshot (null for legacy tweet-only proposals).
  setup_type?: string | null
  entry_price?: number | null
  stop_price?: number | null
  target_price?: number | null
  risk_reward?: number | null
}

export interface AgentAccountCache {
  handle: string
  user_id?: string | null
  resolved_at?: string | null
  not_found: boolean
  in_config: boolean
}

export interface AgentTweetAnalysis {
  id: number
  run_id: number
  handle: string
  tweet_id: string
  tweet_url?: string | null
  tweet_text?: string | null
  tweet_created_at?: string | null
  analysis_json?: string | null
  tickers_count: number
  is_noise: boolean
  error?: string | null
  created_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ChatResponse {
  role: string
  content: string
  model: string
  duration_ms: number
}

export interface LLMInfo {
  provider: 'ollama' | 'openai'
  host: string
  default_model: string
}

export interface AgentSettings {
  llm_provider: 'ollama' | 'openai'
  ollama_host: string
  ollama_model: string
  openai_model: string
  openai_base_url: string
  openai_api_key_set: boolean
  openai_api_key_preview: string
  deep_llm_enabled: boolean
  deep_llm_provider: 'ollama' | 'openai' | ''
  deep_llm_ollama_host: string
  deep_llm_ollama_model: string
  deep_llm_openai_model: string
  deep_llm_openai_base_url: string
  deep_llm_openai_api_key_set: boolean
  deep_llm_openai_api_key_preview: string
  advisor_effective_provider: string
  advisor_effective_model: string
  advisor_effective_host: string
  fmp_base_url: string
  fmp_api_key_set: boolean
  fmp_api_key_preview: string
  sec_user_agent: string
  stocktwits_cookies_set: boolean
  stocktwits_cookies_preview: string
  agent_enabled: boolean
  agent_auto_execute_live: boolean
  agent_budget_usd: number
  agent_weekly_budget_usd: number
  agent_min_position_usd: number
  agent_max_position_usd: number
  agent_daily_loss_cap_usd: number
  agent_max_open_positions: number
  agent_cron_minutes: number
  agent_intel_boost: number
  agent_take_profit_pct: number
  agent_recent_trade_window_hours: number
  agent_min_score: number
  agent_min_confidence: number
  agent_top_n_candidates: number
  agent_llm_concurrency: number
  agent_max_tweets_per_account: number
  agent_lookback_hours: number
  agent_per_account_timeout_s: number
  poll_interval_seconds: number
  manual_order_max_notional: number
  twitter_accounts: string
  swing_enabled: boolean
  swing_risk_per_trade_pct: number
  swing_min_rr: number
  swing_time_stop_days: number
  swing_move_stop_be_pct: number
  swing_partial_pct: number
  swing_market_filter_symbol: string
  swing_market_filter_ma: number
  swing_bar_lookback_days: number
  auto_sell_enabled: boolean
  auto_sell_max_hold_days: number
  overridden: string[]
}

export type AgentSettingsUpdate = Partial<{
  LLM_PROVIDER: 'ollama' | 'openai'
  OLLAMA_HOST: string
  OLLAMA_MODEL: string
  OPENAI_API_KEY: string
  OPENAI_MODEL: string
  OPENAI_BASE_URL: string
  DEEP_LLM_ENABLED: boolean
  DEEP_LLM_PROVIDER: 'ollama' | 'openai'
  DEEP_LLM_OLLAMA_HOST: string
  DEEP_LLM_OLLAMA_MODEL: string
  DEEP_LLM_OPENAI_API_KEY: string
  DEEP_LLM_OPENAI_MODEL: string
  DEEP_LLM_OPENAI_BASE_URL: string
  FMP_API_KEY: string
  FMP_BASE_URL: string
  SEC_USER_AGENT: string
  STOCKTWITS_COOKIES: string
  AGENT_ENABLED: boolean
  AGENT_AUTO_EXECUTE_LIVE: boolean
  AGENT_BUDGET_USD: number
  AGENT_WEEKLY_BUDGET_USD: number
  AGENT_MIN_POSITION_USD: number
  AGENT_MAX_POSITION_USD: number
  AGENT_DAILY_LOSS_CAP_USD: number
  AGENT_MAX_OPEN_POSITIONS: number
  AGENT_CRON_MINUTES: number
  AGENT_INTEL_BOOST: number
  AGENT_TAKE_PROFIT_PCT: number
  AGENT_RECENT_TRADE_WINDOW_HOURS: number
  AGENT_MIN_SCORE: number
  AGENT_MIN_CONFIDENCE: number
  AGENT_TOP_N_CANDIDATES: number
  AGENT_LLM_CONCURRENCY: number
  AGENT_MAX_TWEETS_PER_ACCOUNT: number
  AGENT_LOOKBACK_HOURS: number
  AGENT_PER_ACCOUNT_TIMEOUT_S: number
  POLL_INTERVAL_SECONDS: number
  MANUAL_ORDER_MAX_NOTIONAL: number
  TWITTER_ACCOUNTS: string
  SWING_ENABLED: boolean
  SWING_RISK_PER_TRADE_PCT: number
  SWING_MIN_RR: number
  SWING_TIME_STOP_DAYS: number
  SWING_MOVE_STOP_BE_PCT: number
  SWING_PARTIAL_PCT: number
  SWING_MARKET_FILTER_SYMBOL: string
  SWING_MARKET_FILTER_MA: number
  SWING_BAR_LOOKBACK_DAYS: number
  AUTO_SELL_ENABLED: boolean
  AUTO_SELL_MAX_HOLD_DAYS: number
}>

export interface LLMModels {
  models: string[]
  error?: string
}

export interface DigestEntry {
  id: number
  created_at: string
  kind: string
  symbol?: string | null
  summary: string
  data_json?: string | null
}

export interface DailyDigest {
  id: number
  trade_date: string
  generated_at: string
  entries_covered: number
  window_start?: string | null
  window_end?: string | null
  model_used?: string | null
  text: string
}

export interface DigestSummary {
  latest: DailyDigest | null
  history: DailyDigest[]
  recent_entries: DigestEntry[]
  next_compression_at?: string | null
}
