import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAccount, useAgentSettings, useEarningsCalendars, useOrders, usePositions } from '../api/hooks'
import { PriceChart } from '../components/Chart'
import { usePriceStream } from '../hooks/usePriceStream'
import type { EarningsEvent, Order, Position } from '../api/types'

function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={`panel p-6 space-y-4 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-4 flex-wrap">
          {title && (
            <h3 className="text-sm text-muted-foreground uppercase tracking-wider">
              {title}
            </h3>
          )}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

function usd(n: number, opts?: { showPlus?: boolean }) {
  const abs = Math.abs(n)
  const s = abs.toFixed(2)
  if (n < 0) return `-$${s}`
  if (n > 0 && opts?.showPlus) return `+$${s}`
  return `$${s}`
}

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

function orderFillTs(o: Pick<Order, 'filled_at' | 'submitted_at'>) {
  return new Date(o.filled_at ?? o.submitted_at).getTime()
}

function fmtCompactUsd(n?: number | null) {
  if (n == null || !Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function epsSurprisePct(act?: number | null, est?: number | null) {
  if (act == null || est == null || !Number.isFinite(act) || !Number.isFinite(est)) return null
  if (est === 0) return null
  return ((act - est) / Math.abs(est)) * 100
}

type Enriched = Position & {
  costBasis: number
  plPct: number
  weightPct: number
}

type SortKey =
  | 'symbol'
  | 'qty'
  | 'avg_entry_price'
  | 'current_price'
  | 'costBasis'
  | 'market_value'
  | 'weightPct'
  | 'unrealized_pl'
  | 'plPct'

const PALETTE = ['#e66a8a', '#8b78c7', '#5fe0a8', '#ffb86b', '#9d8bb4', '#6ab0e6', '#c197e6']

function AllocationBar({ rows }: { rows: Enriched[] }) {
  const totalMv = rows.reduce((s, r) => s + r.market_value, 0)
  if (totalMv <= 0 || rows.length === 0) return null
  return (
    <div className="space-y-3">
      <div className="flex h-3 rounded-full overflow-hidden border border-border-strong bg-background-soft">
        {rows.map((r, i) => (
          <div
            key={r.symbol}
            title={`${r.symbol} ${((r.market_value / totalMv) * 100).toFixed(1)}%`}
            className="h-full min-w-[3px] transition-all"
            style={{
              width: `${(r.market_value / totalMv) * 100}%`,
              backgroundColor: PALETTE[i % PALETTE.length],
            }}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {rows.map((r, i) => (
          <li key={r.symbol} className="flex items-center gap-1.5">
            <span
              className="inline-block size-2 rounded-sm shrink-0"
              style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
            />
            <span className="text-foreground font-medium">{r.symbol}</span>
            <span className="tabular-nums">{((r.market_value / totalMv) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function LiveSessionSparkline({
  symbol,
  lastPrice,
  lineColor,
}: {
  symbol: string
  lastPrice: number | null
  lineColor: string
}) {
  const [history, setHistory] = useState<{ time: number; value: number }[]>([])

  useEffect(() => {
    setHistory([])
  }, [symbol])

  useEffect(() => {
    if (lastPrice === null || lastPrice === undefined || !Number.isFinite(lastPrice)) return
    const t = Math.floor(Date.now() / 1000)
    setHistory((h) => [...h, { time: t, value: lastPrice }].slice(-200))
  }, [lastPrice, symbol])

  if (history.length < 2) {
    return (
      <div className="h-[120px] flex items-center justify-center text-xs text-muted-foreground border border-border rounded-lg bg-[#14141f]">
        Waiting for live ticks…
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border overflow-hidden bg-muted/10">
      <PriceChart data={history} height={120} lineColor={lineColor} lineWidth={2} />
    </div>
  )
}

function sortIndicator(active: boolean, dir: 'asc' | 'desc') {
  if (!active) return <span className="text-muted-foreground/40">↕</span>
  return <span className="text-primary">{dir === 'asc' ? '↑' : '↓'}</span>
}

export function PortfolioPage() {
  const qc = useQueryClient()
  const accountQuery = useAccount()
  const positionsQuery = usePositions()
  const ordersQuery = useOrders()
  const orders = ordersQuery.data
  const { data: agentSettings } = useAgentSettings()
  const account = accountQuery.data
  const positions = positionsQuery.data ?? []

  const recentSells = useMemo(() => {
    if (!orders?.length) return []
    const cutoff = Date.now() - WEEK_MS
    return orders
      .filter((o) => {
        if (o.side !== 'sell') return false
        if (o.filled_avg_price == null) return false
        const st = (o.status || '').toLowerCase()
        if (st !== 'filled' && st !== 'partially_filled') return false
        return orderFillTs(o) >= cutoff
      })
      .sort((a, b) => orderFillTs(b) - orderFillTs(a))
  }, [orders])

  const earningsSymbols = useMemo(() => {
    const s = new Set<string>()
    positions.forEach((p) => s.add(p.symbol))
    recentSells.forEach((o) => s.add(o.symbol))
    return [...s].slice(0, 24)
  }, [positions, recentSells])

  const fmpReady = !!agentSettings?.fmp_api_key_set
  const { symbols: earningsSymList, results: earningsResults } = useEarningsCalendars(
    fmpReady ? earningsSymbols : [],
  )

  const earningsRows = useMemo(() => {
    const out: { sym: string; ev: EarningsEvent }[] = []
    earningsSymList.forEach((sym, i) => {
      const rows = earningsResults[i]?.data
      if (!rows?.length) return
      rows.slice(0, 5).forEach((ev) => out.push({ sym, ev }))
    })
    out.sort((a, b) => (b.ev.date || '').localeCompare(a.ev.date || ''))
    return out.slice(0, 48)
  }, [earningsSymList, earningsResults])

  const earningsLoading = earningsResults.some((r) => r.isLoading)

  const [sortKey, setSortKey] = useState<SortKey>('symbol')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const symbols = useMemo(() => positions.map((p) => p.symbol), [positions])
  const quotes = usePriceStream(symbols)

  const totalMarketValue = useMemo(
    () => positions.reduce((s, p) => s + p.market_value, 0),
    [positions],
  )

  const enriched: Enriched[] = useMemo(() => {
    return positions.map((p) => {
      const costBasis = p.qty * p.avg_entry_price
      const plPct = costBasis !== 0 ? (p.unrealized_pl / costBasis) * 100 : 0
      const weightPct =
        totalMarketValue > 0 ? (p.market_value / totalMarketValue) * 100 : 0
      return { ...p, costBasis, plPct, weightPct }
    })
  }, [positions, totalMarketValue])

  const sortedRows = useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1
    const rows = [...enriched]
    rows.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (typeof av === 'string' && typeof bv === 'string') {
        return av.localeCompare(bv) * dir
      }
      return ((av as number) - (bv as number)) * dir
    })
    return rows
  }, [enriched, sortKey, sortDir])

  const totals = useMemo(() => {
    const cost = enriched.reduce((s, r) => s + r.costBasis, 0)
    const value = enriched.reduce((s, r) => s + r.market_value, 0)
    const pl = enriched.reduce((s, r) => s + r.unrealized_pl, 0)
    const plPct = cost !== 0 ? (pl / cost) * 100 : 0
    return { cost, value, pl, plPct }
  }, [enriched])

  const lastUpdatedAt = Math.max(
    accountQuery.dataUpdatedAt ?? 0,
    positionsQuery.dataUpdatedAt ?? 0,
    ordersQuery.dataUpdatedAt ?? 0,
  )
  const lastUpdatedLabel =
    lastUpdatedAt > 0 ? new Date(lastUpdatedAt).toLocaleString() : '—'

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'symbol' ? 'asc' : 'desc')
    }
  }

  const thBtn = (key: SortKey, label: string, title?: string) => (
    <th className="px-3 py-3 text-right text-xs text-muted-foreground whitespace-nowrap">
      <button
        type="button"
        title={title}
        onClick={() => toggleSort(key)}
        className="inline-flex items-center gap-1 font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        {label}
        {sortIndicator(sortKey === key, sortDir)}
      </button>
    </th>
  )

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['account'] })
    void qc.invalidateQueries({ queryKey: ['positions'] })
    void qc.invalidateQueries({ queryKey: ['orders'] })
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-transparent bg-clip-text bg-cosmic-text">
            Portfolio
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Portfolio summary — a simple read on what you own, what you paid, and how open
            positions are doing.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>
            Last synced: <span className="text-foreground tabular-nums">{lastUpdatedLabel}</span>
          </span>
          <span className="hidden sm:inline opacity-40">·</span>
          <span className="hidden sm:inline">Auto-refresh ~15s</span>
          <button
            type="button"
            onClick={refresh}
            className="btn-secondary px-3 py-1 rounded-md text-xs"
          >
            Refresh now
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card title="Account snapshot" className="lg:col-span-1">
          {account ? (
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Cash</span>
                <span className="text-xl tabular-nums">${account.cash.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Buying power</span>
                <span className="text-xl tabular-nums">${account.buying_power.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Portfolio value</span>
                <span className="text-xl tabular-nums">${account.portfolio_value.toFixed(2)}</span>
              </div>
              <p className="text-xs text-muted-foreground pt-2 border-t border-border">
                Portfolio value includes cash plus the market value of open positions (from your
                broker snapshot).
              </p>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground py-6 text-center">
              No account data (check broker connection in Diagnostics).
            </div>
          )}
        </Card>

        <Card title="Open positions — totals" className="lg:col-span-2">
          {enriched.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No open positions. When you hold stocks, this strip shows rolled-up cost basis,
              current value, and unrealized profit or loss.
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Cost basis (positions)</div>
                <div className="text-2xl font-semibold tabular-nums">{usd(totals.cost)}</div>
                <p className="text-xs text-muted-foreground mt-1">What you paid in, in total.</p>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Market value (positions)</div>
                <div className="text-2xl font-semibold tabular-nums">{usd(totals.value)}</div>
                <p className="text-xs text-muted-foreground mt-1">What those shares are worth now.</p>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Unrealized P/L (positions)</div>
                <div
                  className={`text-2xl font-semibold tabular-nums ${
                    totals.pl >= 0 ? 'text-success' : 'text-danger'
                  }`}
                >
                  {usd(totals.pl, { showPlus: true })}{' '}
                  <span className="text-lg font-medium">
                    ({totals.plPct >= 0 ? '+' : ''}
                    {totals.plPct.toFixed(2)}%)
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Paper gain/loss while still holding — not taxed until you sell.
                </p>
              </div>
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Recently sold (last 7 days)"
        action={
          <Link className="text-xs text-primary hover:underline" to="/orders">
            All orders →
          </Link>
        }
      >
        <p className="text-xs text-muted-foreground mb-3">
          Filled sells from the past week, including partial fills. When the agent attached this
          order to a trade record, the reason is shown (manual sells usually have no note).
        </p>
        {recentSells.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sells with fills in the last 7 days.</p>
        ) : (
          <div className="table-wrap overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Filled</th>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">Qty</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">Fill px</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">Realized P/L</th>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Status</th>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Agent note</th>
                </tr>
              </thead>
              <tbody>
                {recentSells.map((o) => {
                  const ts = o.filled_at ?? o.submitted_at
                  const rpl = o.realized_pl
                  const rCls =
                    rpl == null ? 'text-muted-foreground' : rpl >= 0 ? 'text-success' : 'text-danger'
                  return (
                    <tr key={o.id} className="border-t border-border hover:bg-muted/20 transition-colors">
                      <td className="px-3 py-3 text-xs text-muted-foreground whitespace-nowrap">
                        {new Date(ts).toLocaleString()}
                      </td>
                      <td className="px-3 py-3 text-sm font-medium">
                        <Link className="text-primary hover:underline" to={`/symbol/${o.symbol}`}>
                          {o.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">{o.filled_qty ?? o.qty}</td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">
                        {o.filled_avg_price != null ? `$${o.filled_avg_price.toFixed(2)}` : '—'}
                      </td>
                      <td className={`px-3 py-3 text-sm text-right tabular-nums font-medium ${rCls}`}>
                        {rpl == null ? '—' : usd(rpl, { showPlus: true })}
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">{o.status}</td>
                      <td className="px-3 py-3 text-xs text-muted-foreground max-w-md">
                        {o.agent_trade_reason ? (
                          <span>
                            {o.agent_trade_reason}
                            {o.agent_trade_run_id != null && (
                              <>
                                {' '}
                                <Link
                                  className="text-primary hover:underline shrink-0"
                                  to="/agent"
                                  title={`Agent run id ${o.agent_trade_run_id}`}
                                >
                                  (run #{o.agent_trade_run_id})
                                </Link>
                              </>
                            )}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Holdings detail"
        action={
          <span className="text-xs text-muted-foreground">
            Click a column header to sort. Numbers use your broker averages.
          </span>
        }
      >
        {sortedRows.length === 0 ? (
          <div className="text-sm text-muted-foreground space-y-2">
            <p>No rows to show yet.</p>
            <p>
              Place trades from a{' '}
              <Link className="text-primary hover:underline" to="/orders">
                symbol page or Orders
              </Link>{' '}
              to build a portfolio here.
            </p>
          </div>
        ) : (
          <div className="table-wrap overflow-x-auto">
            <table className="w-full min-w-[880px]">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">
                    <button
                      type="button"
                      onClick={() => toggleSort('symbol')}
                      className="inline-flex items-center gap-1 font-medium text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Ticker
                      {sortIndicator(sortKey === 'symbol', sortDir)}
                    </button>
                  </th>
                  {thBtn('qty', 'Shares', 'How many shares you hold (fractional allowed).')}
                  {thBtn(
                    'avg_entry_price',
                    'Avg paid / sh',
                    'Volume-weighted average price you paid per share (your cost basis per share).',
                  )}
                  {thBtn(
                    'current_price',
                    'Last / sh',
                    'Latest price per share from your broker for this position.',
                  )}
                  {thBtn(
                    'costBasis',
                    'Cost basis',
                    'Total dollars you put into this line (shares × average entry).',
                  )}
                  {thBtn('market_value', 'Market value', 'What the position is worth at the last price.')}
                  {thBtn(
                    'weightPct',
                    '% of stocks',
                    'Share of your total stock market value (excludes cash-only allocation).',
                  )}
                  {thBtn('unrealized_pl', 'P/L $', 'Unrealized profit or loss in dollars.')}
                  {thBtn('plPct', 'P/L %', 'Unrealized return vs your cost basis.')}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((p) => {
                  const plCls = p.unrealized_pl >= 0 ? 'text-success' : 'text-danger'
                  const q: any = quotes[p.symbol]
                  const live =
                    (typeof q?.last === 'number' ? q.last : null) ??
                    (typeof q?.ask === 'number' ? q.ask : null)
                  return (
                    <tr
                      key={p.symbol}
                      className="border-t border-border hover:bg-muted/20 transition-colors"
                    >
                      <td className="px-3 py-3 text-sm">
                        <Link
                          className="text-primary font-medium hover:underline"
                          to={`/symbol/${p.symbol}`}
                          title={p.company_name || p.symbol}
                        >
                          {p.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">{p.qty}</td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">
                        ${p.avg_entry_price.toFixed(2)}
                      </td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">
                        ${p.current_price.toFixed(2)}
                        {live != null && Number.isFinite(live) && Math.abs(live - p.current_price) > 0.005 && (
                          <span className="block text-[10px] text-muted-foreground">
                            live {live.toFixed(2)}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">
                        ${p.costBasis.toFixed(2)}
                      </td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">
                        ${p.market_value.toFixed(2)}
                      </td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums text-muted-foreground">
                        {p.weightPct.toFixed(1)}%
                      </td>
                      <td className={`px-3 py-3 text-sm text-right tabular-nums font-medium ${plCls}`}>
                        {usd(p.unrealized_pl, { showPlus: true })}
                      </td>
                      <td className={`px-3 py-3 text-sm text-right tabular-nums ${plCls}`}>
                        {p.plPct >= 0 ? '+' : ''}
                        {p.plPct.toFixed(2)}%
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              {sortedRows.length > 0 && (
                <tfoot className="bg-muted/20 border-t-2 border-border-strong">
                  <tr>
                    <td
                      colSpan={5}
                      className="px-3 py-3 text-xs text-muted-foreground text-right font-medium uppercase tracking-wide"
                    >
                      Totals (open positions)
                    </td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums font-semibold">
                      ${totals.value.toFixed(2)}
                    </td>
                    <td className="px-3 py-3 text-sm text-right tabular-nums text-muted-foreground">
                      100%
                    </td>
                    <td
                      className={`px-3 py-3 text-sm text-right tabular-nums font-semibold ${
                        totals.pl >= 0 ? 'text-success' : 'text-danger'
                      }`}
                    >
                      {usd(totals.pl, { showPlus: true })}
                    </td>
                    <td
                      className={`px-3 py-3 text-sm text-right tabular-nums font-semibold ${
                        totals.pl >= 0 ? 'text-success' : 'text-danger'
                      }`}
                    >
                      {totals.plPct >= 0 ? '+' : ''}
                      {totals.plPct.toFixed(2)}%
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </Card>

      {sortedRows.length > 0 && (
        <Card title="Allocation across open positions">
          <AllocationBar rows={sortedRows} />
          <p className="text-xs text-muted-foreground">
            Each segment is that ticker&apos;s fraction of your total stock market value. Cash is
            not included — add cash context from the account snapshot above.
          </p>
        </Card>
      )}

      <Card title="Position spotlight">
        <p className="text-sm text-muted-foreground">
          Live session sparklines (since you opened this page) plus a quick recap. Open the ticker
          for full depth, news, and trading.
        </p>
        {sortedRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing to spotlight yet.</p>
        ) : (
          <div className="space-y-6">
            {sortedRows.map((p) => {
              const q: any = quotes[p.symbol]
              const live =
                (typeof q?.last === 'number' ? q.last : null) ??
                (typeof q?.ask === 'number' ? q.ask : null) ??
                p.current_price
              const lineColor = p.unrealized_pl >= 0 ? '#5fe0a8' : '#e85d75'
              return (
                <div
                  key={p.symbol}
                  className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-stretch border border-border-strong rounded-xl p-4 bg-background-soft/40"
                >
                  <div className="lg:col-span-1 flex lg:flex-col items-center lg:items-start gap-2">
                    <span className="text-lg font-semibold text-primary">{p.symbol}</span>
                    <Link
                      to={`/symbol/${p.symbol}`}
                      className="text-xs text-muted-foreground hover:text-primary hover:underline"
                    >
                      Detail →
                    </Link>
                  </div>
                  <div className="lg:col-span-5 min-w-0">
                    <LiveSessionSparkline
                      symbol={p.symbol}
                      lastPrice={typeof live === 'number' && Number.isFinite(live) ? live : null}
                      lineColor={lineColor}
                    />
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Intraday line from streamed quotes while this page is open — not a full 6M
                      history chart.
                    </p>
                  </div>
                  <div className="lg:col-span-6 text-sm space-y-2 border-t lg:border-t-0 lg:border-l border-border pt-4 lg:pt-0 lg:pl-4">
                    <div className="font-medium text-foreground">
                      {p.company_name || 'Company name unavailable'}
                    </div>
                    <ul className="space-y-1 text-muted-foreground text-xs">
                      <li>
                        <span className="text-foreground/90">Position: </span>
                        {p.qty} sh @ ${p.avg_entry_price.toFixed(2)} avg → last ${p.current_price.toFixed(2)}
                      </li>
                      <li>
                        <span className="text-foreground/90">Cost basis / value: </span>
                        {usd(p.costBasis)} → {usd(p.market_value)}
                      </li>
                      <li>
                        <span className="text-foreground/90">Unrealized P/L: </span>
                        <span className={p.unrealized_pl >= 0 ? 'text-success' : 'text-danger'}>
                          {usd(p.unrealized_pl, { showPlus: true })} ({p.plPct >= 0 ? '+' : ''}
                          {p.plPct.toFixed(2)}%)
                        </span>
                      </li>
                      <li>
                        <span className="text-foreground/90">Weight in stocks: </span>
                        {p.weightPct.toFixed(1)}%
                      </li>
                    </ul>
                    <p className="text-[11px] text-muted-foreground leading-relaxed pt-1">
                      For scheduled earnings dates and EPS estimates vs actuals, see the
                      &quot;Earnings calendar&quot; section below (Financial Modeling Prep). For
                      transcripts and Seeking Alpha commentary, use the external link there —
                      this app does not scrape third-party sites or store Seeking Alpha logins.
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      <Card
        title="Earnings calendar & calls"
        action={
          agentSettings?.fmp_api_key_set ? (
            <span className="text-xs text-success">FMP key set</span>
          ) : (
            <Link className="text-xs text-primary hover:underline" to="/settings">
              Add FMP API key →
            </Link>
          )
        }
      >
        <p className="text-xs text-muted-foreground mb-3">
          Dates and EPS/revenue figures come from{' '}
          <span className="text-foreground/90">Financial Modeling Prep</span> when{' '}
          <code className="text-[11px]">FMP_API_KEY</code> is configured in Settings. We do{' '}
          <span className="text-foreground/90">not</span> scrape Seeking Alpha (their terms forbid
          automated extraction, and login-based scraping is fragile). Use the Seeking Alpha link
          per row for earnings call write-ups and discussions in your browser.
        </p>
        {!agentSettings?.fmp_api_key_set ? (
          <p className="text-sm text-muted-foreground">
            Set a free FMP key in Settings to populate this table. Until then, only the external
            links are available.
          </p>
        ) : earningsLoading ? (
          <p className="text-sm text-muted-foreground">Loading earnings data…</p>
        ) : earningsRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No earnings rows returned (symbol list empty or FMP had no data for these tickers).
          </p>
        ) : (
          <div className="table-wrap overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Date</th>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Time</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">EPS est.</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">EPS act.</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">EPS surprise</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">Rev est.</th>
                  <th className="px-3 py-3 text-right text-xs text-muted-foreground">Rev act.</th>
                  <th className="px-3 py-3 text-left text-xs text-muted-foreground">Seeking Alpha</th>
                </tr>
              </thead>
              <tbody>
                {earningsRows.map(({ sym, ev }, idx) => {
                  const sur = epsSurprisePct(ev.eps_actual, ev.eps_estimate)
                  const surCls =
                    sur == null
                      ? 'text-muted-foreground'
                      : sur >= 0
                        ? 'text-success'
                        : 'text-danger'
                  const saUrl = `https://seekingalpha.com/symbol/${encodeURIComponent(sym)}/earnings`
                  return (
                    <tr key={`${sym}-${ev.date}-${idx}`} className="border-t border-border hover:bg-muted/20">
                      <td className="px-3 py-3 text-xs text-muted-foreground whitespace-nowrap">
                        {ev.date}
                      </td>
                      <td className="px-3 py-3 text-sm font-medium">
                        <Link className="text-primary hover:underline" to={`/symbol/${sym}`}>
                          {sym}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground uppercase">{ev.time ?? '—'}</td>
                      <td className="px-3 py-3 text-xs text-right tabular-nums">
                        {ev.eps_estimate != null ? ev.eps_estimate.toFixed(2) : '—'}
                      </td>
                      <td className="px-3 py-3 text-xs text-right tabular-nums">
                        {ev.eps_actual != null ? ev.eps_actual.toFixed(2) : '—'}
                      </td>
                      <td className={`px-3 py-3 text-xs text-right tabular-nums ${surCls}`}>
                        {sur == null
                          ? '—'
                          : `${sur >= 0 ? '+' : ''}${sur.toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-3 text-xs text-right tabular-nums">
                        {fmtCompactUsd(ev.revenue_estimate)}
                      </td>
                      <td className="px-3 py-3 text-xs text-right tabular-nums">
                        {fmtCompactUsd(ev.revenue_actual)}
                      </td>
                      <td className="px-3 py-3 text-xs">
                        <a
                          href={saUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline"
                        >
                          Open
                        </a>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Quick glossary (for newer traders)">
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
          <div>
            <dt className="text-foreground font-medium">Cost basis</dt>
            <dd className="text-muted-foreground text-xs mt-0.5">
              What you paid for your current shares (average entry × quantity). Your gain/loss is
              measured against this.
            </dd>
          </div>
          <div>
            <dt className="text-foreground font-medium">Unrealized P/L</dt>
            <dd className="text-muted-foreground text-xs mt-0.5">
              Profit or loss if you sold at the last price — still on paper until you close the
              trade.
            </dd>
          </div>
          <div>
            <dt className="text-foreground font-medium">Realized P/L</dt>
            <dd className="text-muted-foreground text-xs mt-0.5">
              Locked in when you sell (tracked on individual fills in Orders). This page focuses on
              open positions.
            </dd>
          </div>
          <div>
            <dt className="text-foreground font-medium">Buying power</dt>
            <dd className="text-muted-foreground text-xs mt-0.5">
              What your broker lets you deploy for new trades — often higher than cash when margin
              is available (paper vs live rules differ).
            </dd>
          </div>
        </dl>
      </Card>
    </div>
  )
}
