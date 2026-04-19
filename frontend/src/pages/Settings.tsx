import {
  useAccount,
  useAgentAccountsCache,
  useAgentStatus,
  useMode,
} from '../api/hooks'

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

export function SettingsPage() {
  const { data: mode } = useMode()
  const { data: account } = useAccount()
  const { data: agent } = useAgentStatus()
  const { data: cache } = useAgentAccountsCache()

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
          These values are read from <code className="text-primary">backend/.env</code> at
          startup. Edit that file and restart{' '}
          <code className="text-primary">uvicorn</code> to change them.
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

      <Card title="Agent">
        <Row
          label="AGENT_ENABLED"
          value={
            <span className={agent?.enabled ? 'text-success' : 'text-muted-foreground'}>
              {agent?.enabled ? 'enabled' : 'disabled'}
            </span>
          }
          hint="Whether the scheduled background agent is running."
        />
        <Row
          label="AGENT_AUTO_EXECUTE_LIVE"
          value={
            <span
              className={
                agent?.auto_execute_live
                  ? 'text-destructive font-semibold'
                  : 'text-foreground'
              }
            >
              {agent?.auto_execute_live ? 'true (CAUTION)' : 'false'}
            </span>
          }
          hint={
            agent?.auto_execute_live
              ? 'Agent will auto-execute in LIVE mode. Real money.'
              : 'In live mode the agent only PROPOSES trades; you place them manually.'
          }
        />
        <Row
          label="AGENT_BUDGET_USD"
          value={`$${agent?.budget_usd ?? '-'}`}
          hint="Total capital the agent is allowed to deploy per day."
        />
        <Row
          label="AGENT_MAX_POSITION_USD"
          value={`$${agent?.max_position_usd ?? '-'}`}
          hint="Max notional per individual agent trade."
        />
        <Row
          label="AGENT_DAILY_LOSS_CAP_USD"
          value={`$${agent?.daily_loss_cap_usd ?? '-'}`}
          hint="If realized P/L today drops below -this, the agent stops for the day."
        />
        <Row
          label="AGENT_CRON_MINUTES"
          value={`every ${agent?.cron_minutes ?? '-'} min (Mon-Fri, 09:00-15:59 ET)`}
        />
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
      </Card>

      <Card title="LLM (Ollama)">
        <Row
          label="OLLAMA_HOST"
          value={<code className="text-primary">{agent?.ollama_host ?? '-'}</code>}
          hint="Ollama must be running locally. Start with: ollama serve"
        />
        <Row
          label="OLLAMA_MODEL"
          value={<code className="text-primary">{agent?.ollama_model ?? '-'}</code>}
          hint="Pull with: ollama pull <model>"
        />
      </Card>

      <Card title={`Followed X accounts (${agent?.accounts.length ?? 0})`}>
        <p className="text-xs text-muted-foreground mb-3">
          These handles (from <code className="text-primary">TWITTER_ACCOUNTS</code> in{' '}
          <code className="text-primary">.env</code>) are scraped every run. Handles
          resolved once are cached forever; unresolved ones are retried monthly.
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

      <p className="text-xs text-muted-foreground">
        To change any of the values above, edit{' '}
        <code className="text-primary">backend/.env</code> and restart uvicorn. Followed
        accounts are set via the{' '}
        <code className="text-primary">TWITTER_ACCOUNTS</code> comma-separated list.
      </p>
    </div>
  )
}
