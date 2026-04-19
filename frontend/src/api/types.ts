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
  max_position_usd: number
  daily_loss_cap_usd: number
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
  host: string
  default_model: string
}

export interface LLMModels {
  models: string[]
  error?: string
}
