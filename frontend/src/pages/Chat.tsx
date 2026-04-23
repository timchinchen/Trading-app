import { useEffect, useRef, useState } from 'react'
import { Markdown } from '../components/Markdown'

// Persist chat state across navigation in sessionStorage so a round-trip to
// the Dashboard or Settings doesn't wipe the conversation. Clears when the
// browser tab is closed (which is the right behaviour for a private app).
const SS_KEY = 'chat_state'

function loadSession(): {
  messages: ChatMessage[]
  input: string
  includeContext: boolean
} {
  try {
    const raw = sessionStorage.getItem(SS_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return { messages: [], input: '', includeContext: false }
}

function saveSession(state: {
  messages: ChatMessage[]
  input: string
  includeContext: boolean
}) {
  try {
    sessionStorage.setItem(SS_KEY, JSON.stringify(state))
  } catch {}
}
import {
  useAccount,
  useAgentRuns,
  useAgentStatus,
  useChat,
  useDigest,
  useLLMInfo,
  useLLMModels,
  usePositions,
} from '../api/hooks'
import type {
  Account,
  AgentRun,
  AgentStatus,
  ChatMessage,
  DailyDigest,
  Position,
} from '../api/types'

const DEFAULT_SYSTEM =
  'You are a helpful assistant embedded in a personal stocks trading app. ' +
  'Keep answers concise. When users ask about markets, be balanced and note uncertainty. ' +
  'Do not invent data you do not have.'

// ---------------------------------------------------------------------------
// Context builder
// Assembles a lean, structured text block prepended to the system prompt when
// the user enables "include context". Deliberately excludes raw logs and tweet
// noise - only high-signal summaries are included.
// ---------------------------------------------------------------------------
function buildContext({
  account,
  positions,
  agentStatus,
  runs,
  digests,
}: {
  account: Account | undefined
  positions: Position[] | undefined
  agentStatus: AgentStatus | undefined
  runs: AgentRun[] | undefined
  digests: DailyDigest[] | undefined
}): string {
  const lines: string[] = []
  const today = new Date().toLocaleDateString('en-AU', {
    weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
  })
  lines.push(`=== TRADING APP CONTEXT (${today}) ===`)

  // 1. Account snapshot
  if (account) {
    lines.push('')
    lines.push('--- ACCOUNT ---')
    lines.push(`Mode: ${account.mode.toUpperCase()}`)
    lines.push(`Cash: $${account.cash.toFixed(2)}`)
    lines.push(`Buying power: $${account.buying_power.toFixed(2)}`)
    lines.push(`Portfolio value: $${account.portfolio_value.toFixed(2)}`)
  }

  // 2. Agent settings (TP, SL, budget, mode)
  if (agentStatus) {
    lines.push('')
    lines.push('--- AGENT SETTINGS ---')
    lines.push(`Agent enabled: ${agentStatus.enabled}`)
    lines.push(`Budget: $${agentStatus.budget_usd}`)
    lines.push(`Max open positions: ${agentStatus.max_open_positions}`)
    lines.push(`Auto-sell (max hold): ${agentStatus.auto_sell_max_hold_days} days`)
    if (agentStatus.next_run_at)
      lines.push(`Next run: ${new Date(agentStatus.next_run_at).toLocaleString()}`)
  }

  // 3. Open positions
  if (positions && positions.length > 0) {
    lines.push('')
    lines.push('--- OPEN POSITIONS ---')
    for (const p of positions) {
      const plPct =
        p.avg_entry_price > 0
          ? (((p.current_price - p.avg_entry_price) / p.avg_entry_price) * 100).toFixed(2)
          : '?'
      const name = p.company_name ? ` (${p.company_name})` : ''
      lines.push(
        `${p.symbol}${name}: qty=${p.qty} avg=$${p.avg_entry_price.toFixed(2)} ` +
        `last=$${p.current_price.toFixed(2)} P/L=$${p.unrealized_pl.toFixed(2)} (${plPct}%)`
      )
    }
  } else if (positions) {
    lines.push('')
    lines.push('--- OPEN POSITIONS ---')
    lines.push('No open positions.')
  }

  // 4. Trading digests (weekly/daily summaries)
  if (digests && digests.length > 0) {
    lines.push('')
    lines.push('--- TRADING DIGESTS (most recent first) ---')
    for (const d of digests) {
      lines.push(`[${d.trade_date}] ${d.text.trim()}`)
    }
  }

  // 5. Last 20 agent run summaries
  const recentRuns = (runs ?? [])
    .filter((r) => r.summary || r.advice)
    .slice(0, 20)
  if (recentRuns.length > 0) {
    lines.push('')
    lines.push('--- RECENT AGENT RUNS (latest first) ---')
    for (const r of recentRuns) {
      const ts = new Date(r.started_at).toLocaleString()
      const exec = `${r.trades_executed} executed / ${r.trades_proposed} proposed`
      if (r.advice) lines.push(`[${ts}] ${exec} | Advice: ${r.advice.trim()}`)
      else if (r.summary) lines.push(`[${ts}] ${exec} | ${r.summary.trim()}`)
    }
  }

  lines.push('')
  lines.push('=== END CONTEXT ===')
  return lines.join('\n')
}

export function ChatPage() {
  const { data: info } = useLLMInfo()
  const { data: modelsData } = useLLMModels()
  const chat = useChat()

  // Context data — fetched lazily once the user enables the checkbox.
  const { data: account } = useAccount()
  const { data: positions } = usePositions()
  const { data: agentStatus } = useAgentStatus()
  const { data: runs } = useAgentRuns()
  const { data: digest } = useDigest()

  // Seed from sessionStorage so navigation away and back doesn't wipe the
  // conversation. useState lazy initialisers run once on mount only.
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadSession().messages)
  const [input, setInput] = useState<string>(() => loadSession().input)
  const [includeContext, setIncludeContext] = useState<boolean>(() => loadSession().includeContext)
  const [system, setSystem] = useState(DEFAULT_SYSTEM)
  const [model, setModel] = useState<string>('')
  const [temperature, setTemperature] = useState(0.3)
  const [showSettings, setShowSettings] = useState(false)

  // Keep sessionStorage in sync whenever these values change.
  useEffect(() => {
    saveSession({ messages, input, includeContext })
  }, [messages, input, includeContext])

  const listRef = useRef<HTMLDivElement | null>(null)

  // Reset the selected model whenever the active provider changes. Without
  // this, switching Settings -> Provider from (say) Cohere to Hugging Face
  // leaves the old "command-r-08-2024" pinned here, which the HF router
  // rejects with a 400.
  useEffect(() => {
    if (info?.default_model) setModel(info.default_model)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info?.provider, info?.default_model])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages, chat.isPending])

  const send = () => {
    const text = input.trim()
    if (!text || chat.isPending) return
    const next: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(next)
    setInput('')

    // Build effective system prompt — append context block when enabled.
    let effectiveSystem = system
    if (includeContext) {
      const ctx = buildContext({
        account,
        positions,
        agentStatus,
        runs,
        digests: digest?.history ?? (digest?.latest ? [digest.latest] : undefined),
      })
      effectiveSystem = `${system}\n\n${ctx}`
    }

    chat.mutate(
      {
        messages: next,
        system: effectiveSystem,
        model: model || undefined,
        temperature,
      },
      {
        onSuccess: (res) => {
          setMessages((m) => [...m, { role: 'assistant', content: res.content }])
        },
        onError: (err: any) => {
          const msg =
            err?.response?.data?.detail ?? err?.message ?? 'Chat request failed.'
          setMessages((m) => [
            ...m,
            { role: 'assistant', content: `[error] ${msg}` },
          ])
        },
      },
    )
  }

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const clear = () => {
    setMessages([])
    setInput('')
    saveSession({ messages: [], input: '', includeContext })
  }
  const models = modelsData?.models ?? []

  return (
    <div className="p-6 max-w-4xl mx-auto flex flex-col h-[calc(100vh-110px)]">
      <section className="panel p-4 mb-4">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-sm text-muted-foreground uppercase tracking-wider">
            Chat
          </h2>
          <span className="text-xs text-muted-foreground">
            {info ? `${info.host}` : 'loading...'}
          </span>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="bg-input-bg border border-border rounded-md px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            {model && !models.includes(model) && (
              <option value={model}>{model} (default)</option>
            )}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
            {models.length === 0 && !model && <option value="">(no models)</option>}
          </select>
          {modelsData?.error && (
            <span
              className="text-xs text-destructive"
              title={modelsData.error}
            >
              models unavailable
            </span>
          )}
          <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground hover:text-foreground transition-colors">
            <input
              type="checkbox"
              checked={includeContext}
              onChange={(e) => setIncludeContext(e.target.checked)}
              className="accent-primary"
            />
            include context
            {includeContext && (
              <span className="text-primary text-[10px]">
                (portfolio · digests · agent)
              </span>
            )}
          </label>
          <button
            onClick={() => setShowSettings((v) => !v)}
            className="text-xs px-3 py-1.5 rounded-md bg-muted/60 border border-border text-foreground hover:bg-muted transition-colors"
          >
            {showSettings ? 'hide settings' : 'settings'}
          </button>
          <button
            onClick={clear}
            className="ml-auto text-xs px-3 py-1.5 rounded-md bg-muted/60 border border-border text-foreground hover:bg-muted transition-colors"
          >
            clear
          </button>
        </div>
        {showSettings && (
          <div className="mt-4 space-y-4 pt-4 border-t border-border">
            <div className="grid grid-cols-1 md:grid-cols-[1fr_220px] gap-4">
              <div>
                <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
                  System prompt
                </div>
                <textarea
                  value={system}
                  onChange={(e) => setSystem(e.target.value)}
                  rows={3}
                  className="w-full bg-input-bg border border-border rounded-lg p-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <div>
                <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
                  Temperature
                </div>
                <div className="text-sm text-foreground mb-2">{temperature.toFixed(2)}</div>
                <input
                  type="range"
                  min={0}
                  max={1.5}
                  step={0.05}
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full"
                  style={{ accentColor: 'var(--primary)' }}
                />
              </div>
            </div>
            {includeContext && (
              <div>
                <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
                  Context preview (sent with every message)
                </div>
                <pre className="bg-input-bg border border-border rounded-lg p-3 text-[11px] text-muted-foreground whitespace-pre-wrap max-h-48 overflow-auto leading-relaxed">
                  {buildContext({
                    account,
                    positions,
                    agentStatus,
                    runs,
                    digests: digest?.history ?? (digest?.latest ? [digest.latest] : undefined),
                  })}
                </pre>
              </div>
            )}
          </div>
        )}
      </section>

      <div
        ref={listRef}
        className="flex-1 panel p-4 overflow-auto space-y-3"
      >
        {messages.length === 0 && (
          <div className="text-muted-foreground text-sm">
            Start a conversation.{' '}
            {info?.provider === 'ollama' && (
              <>The assistant runs locally via Ollama at {info.host}.</>
            )}
            {info?.provider === 'openai' && (
              <>Using OpenAI ({info.default_model}) at {info.host}.</>
            )}
            {info?.provider === 'huggingface' && (
              <>
                Using Hugging Face ({info.default_model}) via the free-tier
                router at {info.host}.
              </>
            )}
            {info?.provider === 'cohere' && (
              <>Using Cohere ({info.default_model}) at {info.host}.</>
            )}
            {!info && <>Connecting to the configured LLM provider...</>}
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm whitespace-pre-wrap border ${
                m.role === 'user'
                  ? 'text-primary-foreground border-primary/50 shadow-[0_8px_24px_-12px_rgba(230,106,138,0.6)]'
                  : m.role === 'system'
                    ? 'bg-muted text-muted-foreground italic border-border-strong'
                    : 'bg-card-elevated text-foreground border-border-strong'
              }`}
              style={
                m.role === 'user'
                  ? {
                      backgroundImage:
                        'linear-gradient(180deg, #f17da0 0%, #e66a8a 50%, #c94e70 100%)',
                    }
                  : undefined
              }
            >
              <div
                className={`text-[10px] uppercase tracking-wider mb-1 ${
                  m.role === 'user' ? 'text-white/70' : 'text-muted-foreground'
                }`}
              >
                {m.role}
              </div>
              {m.role === 'assistant'
                ? <Markdown>{m.content}</Markdown>
                : <span className="whitespace-pre-wrap">{m.content}</span>
              }
            </div>
          </div>
        ))}
        {chat.isPending && (
          <div className="flex justify-start">
            <div className="bg-muted/60 text-muted-foreground rounded-xl px-4 py-2.5 text-sm italic border border-border">
              thinking...
            </div>
          </div>
        )}
      </div>

      <div className="mt-4 flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          rows={2}
          placeholder="Type a message and press Enter to send (Shift+Enter for newline)"
          className="flex-1 bg-input-bg border border-border rounded-lg p-3 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
        <button
          onClick={send}
          disabled={chat.isPending || !input.trim()}
          className="btn-primary px-6 rounded-lg self-stretch"
        >
          Send
        </button>
      </div>
    </div>
  )
}
