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
}

export interface WatchlistItem {
  id: number
  symbol: string
  feed: 'ws' | 'poll'
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
  fmp_base_url: string
  fmp_api_key_set: boolean
  fmp_api_key_preview: string
  sec_user_agent: string
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
  twitter_accounts: string
  overridden: string[]
}

export type AgentSettingsUpdate = Partial<{
  LLM_PROVIDER: 'ollama' | 'openai'
  OLLAMA_HOST: string
  OLLAMA_MODEL: string
  OPENAI_API_KEY: string
  OPENAI_MODEL: string
  OPENAI_BASE_URL: string
  FMP_API_KEY: string
  FMP_BASE_URL: string
  SEC_USER_AGENT: string
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
  TWITTER_ACCOUNTS: string
}>

export interface LLMModels {
  models: string[]
  error?: string
}
