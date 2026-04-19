import { useEffect, useMemo, useState } from 'react'
import {
  useAccount,
  useAgentAccountsCache,
  useAgentSettings,
  useAgentStatus,
  useMode,
  useUpdateAgentSettings,
} from '../api/hooks'
import type { AgentSettings, AgentSettingsUpdate } from '../api/types'

function Row({
  label,
  value,
  hint,
}: {
  label: string
  value: React.ReactNode
  hint?: string
}) {
  return (
    <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border last:border-b-0">
      <div className="text-xs text-muted-foreground uppercase tracking-wider">
        {label}
      </div>
      <div>
        <div className="text-sm">{value}</div>
        {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
      </div>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel p-6 space-y-2">
      <h3 className="text-sm text-muted-foreground uppercase tracking-wider mb-2">
        {title}
      </h3>
      {children}
    </section>
  )
}

function OverrideBadge({
  k,
  overridden,
}: {
  k: string
  overridden: string[]
}) {
  const isOverridden = overridden.includes(k)
  return (
    <span
      className={`inline-block ml-2 px-1.5 py-0.5 text-[10px] rounded border ${
        isOverridden
          ? 'border-primary/40 text-primary bg-primary/10'
          : 'border-border text-muted-foreground'
      }`}
      title={
        isOverridden
          ? 'Saved in DB - overrides .env'
          : 'Using .env default - not yet customised'
      }
    >
      {isOverridden ? 'override' : '.env default'}
    </span>
  )
}

// ----- LLM provider section (editable) -----
function LLMProviderCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [provider, setProvider] = useState(s.llm_provider)
  const [ollamaHost, setOllamaHost] = useState(s.ollama_host)
  const [ollamaModel, setOllamaModel] = useState(s.ollama_model)
  const [openaiKey, setOpenaiKey] = useState('') // empty = leave existing
  const [clearOpenaiKey, setClearOpenaiKey] = useState(false)
  const [openaiModel, setOpenaiModel] = useState(s.openai_model)
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState(s.openai_base_url)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  // Re-sync when server data changes (e.g. after another tab saved).
  useEffect(() => {
    setProvider(s.llm_provider)
    setOllamaHost(s.ollama_host)
    setOllamaModel(s.ollama_model)
    setOpenaiModel(s.openai_model)
    setOpenaiBaseUrl(s.openai_base_url)
  }, [s])

  const save = () => {
    const body: AgentSettingsUpdate = {
      LLM_PROVIDER: provider,
      OLLAMA_HOST: ollamaHost,
      OLLAMA_MODEL: ollamaModel,
      OPENAI_MODEL: openaiModel,
      OPENAI_BASE_URL: openaiBaseUrl,
    }
    if (clearOpenaiKey) {
      body.OPENAI_API_KEY = ''
    } else if (openaiKey.trim()) {
      body.OPENAI_API_KEY = openaiKey.trim()
    }
    upd.mutate(body, {
      onSuccess: () => {
        setOpenaiKey('')
        setClearOpenaiKey(false)
        setSavedAt(Date.now())
      },
    })
  }

  return (
    <Card title="LLM provider (editable)">
      <p className="text-xs text-muted-foreground mb-4">
        Switch between local Ollama and hosted OpenAI. Saved here, persisted in the
        SQLite DB, used by the next agent run and the Chat page immediately - no
        restart needed.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          PROVIDER
          <OverrideBadge k="LLM_PROVIDER" overridden={s.overridden} />
        </div>
        <div className="flex items-center gap-2">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as 'ollama' | 'openai')}
            className="px-3 py-2 rounded-md text-sm w-48"
          >
            <option value="ollama">Ollama (local)</option>
            <option value="openai">OpenAI (hosted)</option>
          </select>
          <span className="text-xs text-muted-foreground">
            currently active: <code className="text-primary">{s.llm_provider}</code>
          </span>
        </div>
      </div>

      {provider === 'ollama' && (
        <>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OLLAMA_HOST
              <OverrideBadge k="OLLAMA_HOST" overridden={s.overridden} />
            </div>
            <input
              value={ollamaHost}
              onChange={(e) => setOllamaHost(e.target.value)}
              placeholder="http://localhost:11434"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OLLAMA_MODEL
              <OverrideBadge k="OLLAMA_MODEL" overridden={s.overridden} />
            </div>
            <input
              value={ollamaModel}
              onChange={(e) => setOllamaModel(e.target.value)}
              placeholder="llama3.1:8b"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
        </>
      )}

      {provider === 'openai' && (
        <>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OPENAI_API_KEY
              <OverrideBadge k="OPENAI_API_KEY" overridden={s.overridden} />
            </div>
            <div className="space-y-1">
              <input
                type="password"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder={
                  s.openai_api_key_set
                    ? `current: ${s.openai_api_key_preview} (leave blank to keep)`
                    : 'sk-...'
                }
                className="px-3 py-2 rounded-md text-sm w-full max-w-md font-mono"
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={clearOpenaiKey}
                  onChange={(e) => setClearOpenaiKey(e.target.checked)}
                />
                clear stored key (revert to .env / disable OpenAI)
              </label>
              <div className="text-[11px] text-muted-foreground">
                Stored encrypted-at-rest in your local SQLite DB. Never sent anywhere
                except the chosen API endpoint.
              </div>
            </div>
          </div>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OPENAI_MODEL
              <OverrideBadge k="OPENAI_MODEL" overridden={s.overridden} />
            </div>
            <input
              value={openaiModel}
              onChange={(e) => setOpenaiModel(e.target.value)}
              placeholder="gpt-4o-mini"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OPENAI_BASE_URL
              <OverrideBadge k="OPENAI_BASE_URL" overridden={s.overridden} />
            </div>
            <input
              value={openaiBaseUrl}
              onChange={(e) => setOpenaiBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
        </>
      )}

      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save LLM settings'}
        </button>
        {savedAt && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
        {upd.isError && (
          <span className="text-xs text-destructive">
            failed: {(upd.error as any)?.message ?? 'see console'}
          </span>
        )}
      </div>
    </Card>
  )
}

// ----- Twitter accounts (editable) -----
function TwitterAccountsCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [text, setText] = useState(s.twitter_accounts)
  useEffect(() => setText(s.twitter_accounts), [s.twitter_accounts])

  const handles = useMemo(
    () =>
      text
        .split(/[\s,]+/)
        .map((h) => h.trim().replace(/^@/, ''))
        .filter(Boolean),
    [text],
  )

  const save = () => {
    upd.mutate({ TWITTER_ACCOUNTS: handles.join(',') })
  }

  return (
    <Card title={`Followed X accounts (${handles.length})`}>
      <div className="text-xs text-muted-foreground mb-2">
        Comma- or whitespace-separated list of X handles (no <code>@</code>). Saved
        live - the next agent run picks up the new list.
        <OverrideBadge k="TWITTER_ACCOUNTS" overridden={s.overridden} />
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="PeterLBrandt, LindaRaschke, MarkMinervini"
        className="w-full px-3 py-2 rounded-md text-sm font-mono"
      />
      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save handles'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Agent budget / cadence (editable) -----
function AgentBudgetCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [enabled, setEnabled] = useState(s.agent_enabled)
  const [autoLive, setAutoLive] = useState(s.agent_auto_execute_live)
  const [budget, setBudget] = useState(s.agent_budget_usd)
  const [weekly, setWeekly] = useState(s.agent_weekly_budget_usd)
  const [minPos, setMinPos] = useState(s.agent_min_position_usd)
  const [maxPos, setMaxPos] = useState(s.agent_max_position_usd)
  const [dailyLoss, setDailyLoss] = useState(s.agent_daily_loss_cap_usd)
  const [maxOpen, setMaxOpen] = useState(s.agent_max_open_positions)
  const [cron, setCron] = useState(s.agent_cron_minutes)
  const [intelBoost, setIntelBoost] = useState(s.agent_intel_boost)

  useEffect(() => {
    setEnabled(s.agent_enabled)
    setAutoLive(s.agent_auto_execute_live)
    setBudget(s.agent_budget_usd)
    setWeekly(s.agent_weekly_budget_usd)
    setMinPos(s.agent_min_position_usd)
    setMaxPos(s.agent_max_position_usd)
    setDailyLoss(s.agent_daily_loss_cap_usd)
    setMaxOpen(s.agent_max_open_positions)
    setCron(s.agent_cron_minutes)
    setIntelBoost(s.agent_intel_boost)
  }, [s])

  const save = () => {
    upd.mutate({
      AGENT_ENABLED: enabled,
      AGENT_AUTO_EXECUTE_LIVE: autoLive,
      AGENT_BUDGET_USD: Number(budget),
      AGENT_WEEKLY_BUDGET_USD: Number(weekly),
      AGENT_MIN_POSITION_USD: Number(minPos),
      AGENT_MAX_POSITION_USD: Number(maxPos),
      AGENT_DAILY_LOSS_CAP_USD: Number(dailyLoss),
      AGENT_MAX_OPEN_POSITIONS: Number(maxOpen),
      AGENT_CRON_MINUTES: Number(cron),
      AGENT_INTEL_BOOST: Number(intelBoost),
    })
  }

  const NumInput = ({
    value,
    onChange,
    step = '1',
  }: {
    value: number
    onChange: (n: number) => void
    step?: string
  }) => (
    <input
      type="number"
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-3 py-2 rounded-md text-sm w-32"
    />
  )

  return (
    <Card title="Agent budget & cadence (editable)">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            AGENT_ENABLED
            <OverrideBadge k="AGENT_ENABLED" overridden={s.overridden} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            scheduler runs every cron interval
          </label>
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            AUTO_EXECUTE_LIVE
            <OverrideBadge k="AGENT_AUTO_EXECUTE_LIVE" overridden={s.overridden} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={autoLive}
              onChange={(e) => setAutoLive(e.target.checked)}
            />
            <span className={autoLive ? 'text-destructive font-semibold' : ''}>
              auto-execute in LIVE mode (real money!)
            </span>
          </label>
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            BUDGET_USD
            <OverrideBadge k="AGENT_BUDGET_USD" overridden={s.overridden} />
          </div>
          <NumInput value={budget} onChange={setBudget} step="10" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            WEEKLY_BUDGET_USD
            <OverrideBadge k="AGENT_WEEKLY_BUDGET_USD" overridden={s.overridden} />
          </div>
          <NumInput value={weekly} onChange={setWeekly} step="10" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MIN_POSITION_USD
            <OverrideBadge k="AGENT_MIN_POSITION_USD" overridden={s.overridden} />
          </div>
          <NumInput value={minPos} onChange={setMinPos} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MAX_POSITION_USD
            <OverrideBadge k="AGENT_MAX_POSITION_USD" overridden={s.overridden} />
          </div>
          <NumInput value={maxPos} onChange={setMaxPos} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            DAILY_LOSS_CAP
            <OverrideBadge k="AGENT_DAILY_LOSS_CAP_USD" overridden={s.overridden} />
          </div>
          <NumInput value={dailyLoss} onChange={setDailyLoss} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MAX_OPEN_POSITIONS
            <OverrideBadge k="AGENT_MAX_OPEN_POSITIONS" overridden={s.overridden} />
          </div>
          <NumInput value={maxOpen} onChange={setMaxOpen} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            CRON_MINUTES
            <OverrideBadge k="AGENT_CRON_MINUTES" overridden={s.overridden} />
          </div>
          <NumInput value={cron} onChange={setCron} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            INTEL_BOOST
            <OverrideBadge k="AGENT_INTEL_BOOST" overridden={s.overridden} />
          </div>
          <NumInput value={intelBoost} onChange={setIntelBoost} step="0.05" />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-4">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save agent settings'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved (rescheduler refreshed)</span>
        )}
      </div>
    </Card>
  )
}

export function SettingsPage() {
  const { data: mode } = useMode()
  const { data: account } = useAccount()
  const { data: agent } = useAgentStatus()
  const { data: cache } = useAgentAccountsCache()
  const { data: agentSettings } = useAgentSettings()

  const fmtDt = (s?: string | null) => (s ? new Date(s).toLocaleString() : '-')
  const isLive = mode?.mode === 'live'

  const resolved = cache?.filter((c) => c.user_id && !c.not_found) || []
  const notFound = cache?.filter((c) => c.not_found) || []
  const pending = cache?.filter((c) => !c.user_id && !c.not_found && c.in_config) || []
  const orphaned = cache?.filter((c) => !c.in_config) || []

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-semibold">Settings & Configuration</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Defaults come from <code className="text-primary">backend/.env</code> at
          startup. Anything you change in the editable cards below is persisted in
          the SQLite database and overrides the env file - no restart required.
          Broker keys and <code className="text-primary">APP_MODE</code> still live in{' '}
          <code className="text-primary">.env</code> for safety.
        </p>
      </div>

      <Card title="Runtime mode">
        <Row
          label="APP_MODE"
          value={
            <span
              className={`font-semibold ${
                isLive ? 'text-destructive' : 'text-success'
              }`}
            >
              {mode?.mode ?? '...'}
            </span>
          }
          hint={
            isLive
              ? 'LIVE - orders go to Alpaca and use real money.'
              : 'PAPER - simulated trades, no real money.'
          }
        />
        <Row
          label="MARKET_DATA_MODE"
          value={mode?.market_data_mode ?? '...'}
          hint='"ws" all-websocket, "poll" all-REST, "mixed" = per-symbol (default).'
        />
        <Row
          label="MAX_ORDER_NOTIONAL"
          value={`$${mode?.max_order_notional?.toFixed?.(2) ?? '-'}`}
          hint="Hard server-side cap applied to EVERY order (including agent + manual)."
        />
      </Card>

      <Card title="Broker account (Alpaca)">
        {account ? (
          <>
            <Row label="Broker mode" value={account.mode} />
            <Row label="Currency" value={account.currency} />
            <Row label="Cash" value={`$${account.cash.toFixed(2)}`} />
            <Row label="Buying power" value={`$${account.buying_power.toFixed(2)}`} />
            <Row
              label="Portfolio value"
              value={`$${account.portfolio_value.toFixed(2)}`}
            />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            No broker data. Check{' '}
            <code className="text-primary">ALPACA_PAPER_KEY</code> /{' '}
            <code className="text-primary">ALPACA_PAPER_SECRET</code> in{' '}
            <code className="text-primary">.env</code>.
          </p>
        )}
      </Card>

      {agentSettings ? (
        <>
          <LLMProviderCard s={agentSettings} />
          <AgentBudgetCard s={agentSettings} />
          <TwitterAccountsCard s={agentSettings} />
        </>
      ) : (
        <Card title="LLM + agent settings">
          <p className="text-sm text-muted-foreground">Loading editable settings...</p>
        </Card>
      )}

      <Card title="Agent status">
        <Row
          label="Last run"
          value={
            <span
              className={
                agent?.last_run_status === 'ok'
                  ? 'text-success'
                  : agent?.last_run_status === 'error'
                    ? 'text-destructive'
                    : 'text-muted-foreground'
              }
            >
              {agent?.last_run_status ?? 'never'}
              {agent?.last_run_started_at
                ? ` @ ${fmtDt(agent.last_run_started_at)}`
                : ''}
            </span>
          }
        />
        <Row label="Next run" value={fmtDt(agent?.next_run_at)} />
        <Row
          label="Active LLM"
          value={
            <code className="text-primary">
              {agent?.ollama_model} @ {agent?.ollama_host}
            </code>
          }
          hint="Resolved from your provider override above."
        />
      </Card>

      <Card title={`Resolution status (${agent?.accounts.length ?? 0} handles)`}>
        <p className="text-xs text-muted-foreground mb-3">
          Cached resolution status for the handles above. Resolved IDs persist
          forever; unresolved handles are retried monthly.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Resolved ({resolved.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[320px] overflow-auto pr-2">
              {resolved.map((c) => (
                <li key={c.handle} className="flex justify-between gap-2">
                  <a
                    href={`https://x.com/${c.handle}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-success hover:underline"
                  >
                    @{c.handle}
                  </a>
                  <span className="text-muted-foreground">id {c.user_id}</span>
                </li>
              ))}
              {resolved.length === 0 && (
                <li className="text-muted-foreground italic">
                  none yet (agent hasn't resolved any)
                </li>
              )}
            </ul>
          </div>

          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Pending / not resolved ({pending.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[320px] overflow-auto pr-2">
              {pending.map((c) => (
                <li key={c.handle}>
                  <a
                    href={`https://x.com/${c.handle}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground hover:underline"
                  >
                    @{c.handle}
                  </a>
                </li>
              ))}
              {pending.length === 0 && (
                <li className="text-muted-foreground italic">all resolved</li>
              )}
            </ul>
          </div>

          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Not found on X ({notFound.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[200px] overflow-auto pr-2">
              {notFound.map((c) => (
                <li key={c.handle} className="flex justify-between gap-2">
                  <span className="text-destructive">@{c.handle}</span>
                  <span className="text-muted-foreground">{fmtDt(c.resolved_at)}</span>
                </li>
              ))}
              {notFound.length === 0 && (
                <li className="text-muted-foreground italic">none</li>
              )}
            </ul>
          </div>

          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Cached but removed from config ({orphaned.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[200px] overflow-auto pr-2">
              {orphaned.map((c) => (
                <li key={c.handle} className="text-muted-foreground">
                  @{c.handle} ({c.not_found ? 'not-found' : 'resolved'})
                </li>
              ))}
              {orphaned.length === 0 && (
                <li className="text-muted-foreground italic">none</li>
              )}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  )
}
