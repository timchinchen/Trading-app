import { useMemo, useState } from 'react'
import {
  useAgentRunNow,
  useAgentRunSignals,
  useAgentRunTrades,
  useAgentRunTweets,
  useAgentRuns,
  useAgentStatus,
} from '../api/hooks'
import type { AgentTweetAnalysis } from '../api/types'

type Tab = 'logs' | 'tweets' | 'signals' | 'trades'

function parseAnalysis(raw?: string | null): any | null {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function Pill({
  children,
  tone = 'muted',
}: {
  children: React.ReactNode
  tone?: 'muted' | 'primary' | 'success' | 'danger' | 'secondary'
}) {
  const toneCls =
    tone === 'primary'
      ? 'bg-primary/20 text-primary border-primary/30'
      : tone === 'success'
        ? 'bg-success/15 text-success border-success/30'
        : tone === 'danger'
          ? 'bg-destructive/15 text-destructive border-destructive/30'
          : tone === 'secondary'
            ? 'bg-secondary/20 text-secondary-foreground border-secondary/30'
            : 'bg-muted/40 text-muted-foreground border-border'
  return (
    <span className={`px-2 py-0.5 rounded-md text-xs border ${toneCls}`}>{children}</span>
  )
}

function TweetRow({ t }: { t: AgentTweetAnalysis }) {
  const [open, setOpen] = useState(false)
  const a = useMemo(() => parseAnalysis(t.analysis_json), [t.analysis_json])
  const tickers: any[] = a?.tickers ?? []
  return (
    <>
      <tr
        className="border-t border-border align-top cursor-pointer hover:bg-muted/20 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">
          {t.tweet_created_at
            ? new Date(t.tweet_created_at).toLocaleString()
            : '-'}
        </td>
        <td className="px-3 py-2 text-xs">@{t.handle}</td>
        <td className="px-3 py-2 text-xs max-w-[420px]">
          <div className="truncate" title={t.tweet_text ?? ''}>
            {t.tweet_text ?? ''}
          </div>
        </td>
        <td className="px-3 py-2 text-xs">{t.tickers_count}</td>
        <td className="px-3 py-2 text-xs">
          {t.is_noise ? (
            <Pill>noise</Pill>
          ) : t.error ? (
            <Pill tone="danger">error</Pill>
          ) : (
            <Pill tone="success">ok</Pill>
          )}
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">
          {open ? 'hide' : 'show'}
        </td>
      </tr>
      {open && (
        <tr className="bg-card-elevated/50">
          <td colSpan={6} className="p-4 text-xs border-t border-border">
            <div className="flex gap-4 flex-wrap mb-2">
              {t.tweet_url && (
                <a
                  href={t.tweet_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary hover:underline"
                >
                  open tweet
                </a>
              )}
              <span className="text-muted-foreground">id: {t.tweet_id}</span>
            </div>
            <div className="mb-3 whitespace-pre-wrap text-foreground">{t.tweet_text}</div>
            {t.error && (
              <div className="text-destructive mb-3">error: {t.error}</div>
            )}
            {tickers.length > 0 && (
              <div className="overflow-hidden rounded-md border border-border mb-3">
                <table className="w-full">
                  <thead className="bg-muted/30">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Symbol</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Sentiment</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Conviction</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Action</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tickers.map((tk, i) => (
                      <tr key={i} className="border-t border-border">
                        <td className="px-3 py-2 font-medium">{tk.symbol}</td>
                        <td className="px-3 py-2">{tk.sentiment}</td>
                        <td className="px-3 py-2">
                          {tk.conviction?.toFixed?.(2) ?? tk.conviction}
                        </td>
                        <td className="px-3 py-2">{tk.action}</td>
                        <td className="px-3 py-2 text-muted-foreground">{tk.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <details>
              <summary className="text-muted-foreground cursor-pointer">
                raw analysis
              </summary>
              <pre className="text-[11px] text-muted-foreground overflow-auto mt-2 bg-card-elevated border border-border rounded-md p-3 font-mono">
                {t.analysis_json}
              </pre>
            </details>
          </td>
        </tr>
      )}
    </>
  )
}

export function AgentPage() {
  const { data: status } = useAgentStatus()
  const { data: runs } = useAgentRuns()
  const [selected, setSelected] = useState<number | null>(null)
  const activeRunId = selected ?? runs?.[0]?.id ?? null
  const activeRun = useMemo(
    () => runs?.find((r) => r.id === activeRunId) ?? null,
    [runs, activeRunId],
  )
  const { data: signals } = useAgentRunSignals(activeRunId)
  const { data: trades } = useAgentRunTrades(activeRunId)
  const { data: tweets } = useAgentRunTweets(activeRunId)
  const runNow = useAgentRunNow()
  const [tab, setTab] = useState<Tab>('logs')

  const fmtDt = (s?: string | null) => (s ? new Date(s).toLocaleString() : '-')

  const tabBtn = (t: Tab, label: string, count?: number) => (
    <button
      onClick={() => setTab(t)}
      className={`px-3 py-1.5 rounded-md text-sm transition-all ${
        tab === t
          ? 'bg-primary/20 text-primary shadow-[inset_0_0_0_1px_rgba(230,106,138,0.55)]'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
      }`}
    >
      {label}
      {typeof count === 'number' && (
        <span className="ml-1 text-xs text-muted-foreground">({count})</span>
      )}
    </button>
  )

  return (
    <div className="p-6 space-y-6">
      <section className="panel p-6">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-sm text-muted-foreground uppercase tracking-wider">Agent</h2>
          <Pill tone={status?.enabled ? 'success' : 'muted'}>
            {status?.enabled ? 'enabled' : 'disabled'}
          </Pill>
          <Pill tone="secondary">mode: {status?.mode}</Pill>
          <button
            onClick={() => runNow.mutate()}
            disabled={runNow.isPending}
            className="btn-primary ml-auto px-4 py-2 rounded-lg"
          >
            {runNow.isPending ? 'Running...' : 'Run now'}
          </button>
        </div>
        {status && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
            <div className="bg-background-soft border border-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Seed</div>
              <div className="text-sm font-medium text-foreground">${status.budget_usd}</div>
            </div>
            <div className="bg-background-soft border border-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Weekly cap</div>
              <div className="text-sm font-medium text-foreground">${status.weekly_budget_usd}</div>
            </div>
            <div className="bg-background-soft border border-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Slot</div>
              <div className="text-sm font-medium text-foreground">
                ${status.min_position_usd}–${status.max_position_usd}
              </div>
            </div>
            <div className="bg-background-soft border border-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Max open</div>
              <div className="text-sm font-medium text-foreground">{status.max_open_positions}</div>
            </div>
            <div className="bg-background-soft border border-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Daily loss cap</div>
              <div className="text-sm font-medium text-foreground">${status.daily_loss_cap_usd}</div>
            </div>
            <div className="bg-background-soft border border-border rounded-lg px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Cron</div>
              <div className="text-sm font-medium text-foreground">{status.cron_minutes}m</div>
            </div>
          </div>
        )}
        {status && (
          <div className="text-xs text-muted-foreground mt-3">
            Next run: {fmtDt(status.next_run_at)} · Last run status:{' '}
            {status.last_run_status ?? '-'} · Accounts: {status.accounts.length} · LLM:{' '}
            {status.ollama_model} @ {status.ollama_host}
          </div>
        )}
      </section>

      {activeRun?.advice && (
        <section className="panel p-6 shadow-[inset_0_0_0_1px_rgba(230,106,138,0.45),0_0_24px_rgba(230,106,138,0.08)]">
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm uppercase tracking-wider text-primary">Portfolio recommendation</h3>
            <Pill tone="primary">Run #{activeRun.id}</Pill>
            <span className="text-xs text-muted-foreground">{fmtDt(activeRun.finished_at ?? activeRun.started_at)}</span>
          </div>
          <pre className="text-sm text-foreground whitespace-pre-wrap font-sans leading-relaxed">
            {activeRun.advice}
          </pre>
          {activeRun.intel_brief && (
            <details className="mt-4">
              <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
                market intel snapshot
              </summary>
              <pre className="text-[11px] text-muted-foreground whitespace-pre-wrap mt-2 bg-card-elevated border border-border rounded-md p-3 font-mono">
                {activeRun.intel_brief}
              </pre>
            </details>
          )}
        </section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="panel p-6 space-y-3">
          <h3 className="text-sm text-muted-foreground uppercase tracking-wider">Runs</h3>
          <div className="space-y-2 max-h-[70vh] overflow-auto">
            {runs?.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelected(r.id)}
                className={`w-full text-left px-3 py-2 rounded-lg border transition-all ${
                  activeRunId === r.id
                    ? 'bg-primary/15 border-primary/50 text-foreground shadow-[inset_0_0_0_1px_rgba(230,106,138,0.35)]'
                    : 'bg-background-soft border-border-strong hover:bg-card-elevated hover:border-border-strong'
                }`}
              >
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium">#{r.id}</span>
                  <Pill
                    tone={
                      r.status === 'ok'
                        ? 'success'
                        : r.status === 'error'
                          ? 'danger'
                          : 'muted'
                    }
                  >
                    {r.status}
                  </Pill>
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {fmtDt(r.started_at)}
                </div>
                <div className="text-xs text-muted-foreground">
                  tweets: {r.tweets_fetched} · exec: {r.trades_executed}/
                  {r.trades_proposed}
                </div>
              </button>
            ))}
            {(!runs || runs.length === 0) && (
              <div className="text-muted-foreground text-sm">
                No runs yet. Click "Run now".
              </div>
            )}
          </div>
        </section>

        <section className="panel p-6 lg:col-span-2 space-y-4">
          <div className="flex items-center gap-2 flex-wrap border-b border-border pb-3">
            <h3 className="text-sm text-muted-foreground uppercase tracking-wider">
              Run #{activeRunId ?? '-'}
            </h3>
            {activeRun && (
              <span className="text-xs text-muted-foreground">
                {fmtDt(activeRun.started_at)} → {fmtDt(activeRun.finished_at)} · mode=
                {activeRun.mode} · accounts={activeRun.accounts_scanned} · tweets=
                {activeRun.tweets_fetched}
              </span>
            )}
            <div className="ml-auto flex items-center gap-1 p-1 bg-background-soft border border-border rounded-lg">
              {tabBtn('logs', 'Logs')}
              {tabBtn('tweets', 'Tweets', tweets?.length)}
              {tabBtn('signals', 'Signals', signals?.length)}
              {tabBtn('trades', 'Trades', trades?.length)}
            </div>
          </div>

          {tab === 'logs' && (
            <div>
              {activeRun?.summary && (
                <div className="text-xs text-foreground mb-3">
                  <span className="text-muted-foreground">summary: </span>
                  {activeRun.summary}
                </div>
              )}
              <pre className="text-[11px] bg-card-elevated border border-border rounded-lg p-4 overflow-auto max-h-[65vh] whitespace-pre-wrap text-foreground font-mono leading-relaxed">
                {activeRun?.logs ?? '(no logs)'}
              </pre>
            </div>
          )}

          {tab === 'tweets' && (
            <div className="table-wrap">
              <div className="overflow-auto max-h-[70vh]">
                <table className="w-full">
                  <thead className="bg-muted/30 sticky top-0 z-10">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Time</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Handle</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Tweet</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Tickers</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground">Status</th>
                      <th className="px-3 py-2 text-left text-xs text-muted-foreground"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {tweets?.map((t) => <TweetRow key={t.id} t={t} />)}
                    {(!tweets || tweets.length === 0) && (
                      <tr className="border-t border-border">
                        <td
                          colSpan={6}
                          className="px-4 py-8 text-center text-sm text-muted-foreground"
                        >
                          No tweet analyses recorded for this run.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === 'signals' && (
            <div className="table-wrap">
              <table className="w-full">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Score</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Conf</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Mentions</th>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {signals?.map((s) => (
                    <tr key={s.id} className="border-t border-border align-top">
                      <td className="px-4 py-3 text-sm font-medium">{s.symbol}</td>
                      <td
                        className={`px-4 py-3 text-sm text-right ${
                          s.score > 0
                            ? 'text-success'
                            : s.score < 0
                              ? 'text-danger'
                              : ''
                        }`}
                      >
                        {s.score.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-sm text-right">
                        {s.confidence.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-sm text-right">{s.mentions}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {s.rationale}
                      </td>
                    </tr>
                  ))}
                  {(!signals || signals.length === 0) && (
                    <tr className="border-t border-border">
                      <td
                        colSpan={5}
                        className="px-4 py-8 text-center text-sm text-muted-foreground"
                      >
                        No signals
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {tab === 'trades' && (
            <div className="table-wrap">
              <table className="w-full">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Time</th>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Side</th>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Setup</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Entry / Stop / Tgt</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">R/R</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Qty</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Notional</th>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Action</th>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {trades?.map((t) => (
                    <tr key={t.id} className="border-t border-border">
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {fmtDt(t.created_at)}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium">{t.symbol}</td>
                      <td
                        className={`px-4 py-3 text-sm ${
                          t.side === 'buy' ? 'text-success' : 'text-danger'
                        }`}
                      >
                        {t.side}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {t.setup_type ? (
                          <span className="px-1.5 py-0.5 rounded border border-primary/40 text-primary bg-primary/10">
                            {t.setup_type.replace(/_/g, ' ')}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-right font-mono text-muted-foreground">
                        {t.entry_price != null
                          ? `$${t.entry_price.toFixed(2)} / $${t.stop_price?.toFixed(2) ?? '-'} / $${t.target_price?.toFixed(2) ?? '-'}`
                          : '-'}
                      </td>
                      <td className="px-4 py-3 text-xs text-right font-mono">
                        {t.risk_reward != null ? `${t.risk_reward.toFixed(2)}:1` : '-'}
                      </td>
                      <td className="px-4 py-3 text-sm text-right">{t.qty}</td>
                      <td className="px-4 py-3 text-sm text-right">
                        ${t.notional?.toFixed(2) ?? '-'}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <Pill
                          tone={
                            t.action === 'executed'
                              ? 'success'
                              : t.action === 'proposed'
                                ? 'primary'
                                : 'muted'
                          }
                        >
                          {t.action}
                        </Pill>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {t.reason}
                      </td>
                    </tr>
                  ))}
                  {(!trades || trades.length === 0) && (
                    <tr className="border-t border-border">
                      <td
                        colSpan={10}
                        className="px-4 py-8 text-center text-sm text-muted-foreground"
                      >
                        No trades
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
