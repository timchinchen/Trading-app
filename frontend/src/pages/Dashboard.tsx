import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useAccount,
  useAddWatch,
  usePositions,
  useRemoveWatch,
  useUpdateFeed,
  useWatchlist,
} from '../api/hooks'
import { usePriceStream } from '../hooks/usePriceStream'

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
        <div className="flex items-center justify-between">
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

export function DashboardPage() {
  const { data: account } = useAccount()
  const { data: positions } = usePositions()
  const { data: watchlist } = useWatchlist()
  const addWatch = useAddWatch()
  const removeWatch = useRemoveWatch()
  const updateFeed = useUpdateFeed()
  const [newSym, setNewSym] = useState('')
  const [newFeed, setNewFeed] = useState<'ws' | 'poll'>('ws')

  const symbols = watchlist?.map((w) => w.symbol) || []
  const quotes = usePriceStream(symbols)

  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Account">
          {account ? (
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Cash</span>
                <span className="text-xl">${account.cash.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Buying power</span>
                <span className="text-xl">${account.buying_power.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">Portfolio value</span>
                <span className="text-xl">${account.portfolio_value.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-border">
                <span className="text-sm text-muted-foreground">Currency</span>
                <span className="text-sm">{account.currency}</span>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
              No data (check Alpaca creds)
            </div>
          )}
        </Card>

        <Card title="Positions">
          {positions && positions.length > 0 ? (
            <div className="table-wrap">
              <table className="w-full">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Qty</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Avg</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">Last</th>
                    <th className="px-4 py-3 text-right text-xs text-muted-foreground">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr
                      key={p.symbol}
                      className="border-t border-border hover:bg-muted/20 transition-colors"
                    >
                      <td className="px-4 py-3 text-sm">
                        <Link
                          className="text-primary hover:underline"
                          to={`/symbol/${p.symbol}`}
                        >
                          {p.symbol}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-sm text-right">{p.qty}</td>
                      <td className="px-4 py-3 text-sm text-right">
                        ${p.avg_entry_price.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-sm text-right">
                        ${p.current_price.toFixed(2)}
                      </td>
                      <td
                        className={`px-4 py-3 text-sm text-right ${
                          p.unrealized_pl >= 0 ? 'text-success' : 'text-danger'
                        }`}
                      >
                        ${p.unrealized_pl.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
              No open positions
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Watchlist (live)"
        action={
          <div className="flex gap-2">
            <input
              value={newSym}
              onChange={(e) => setNewSym(e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="bg-input-bg border border-border text-foreground placeholder:text-muted-foreground px-3 py-1.5 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 w-24"
            />
            <select
              value={newFeed}
              onChange={(e) => setNewFeed(e.target.value as any)}
              className="bg-input-bg border border-border text-foreground px-3 py-1.5 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="ws">WebSocket</option>
              <option value="poll">Polling</option>
            </select>
            <button
              onClick={() => {
                if (newSym) {
                  addWatch.mutate({ symbol: newSym, feed: newFeed })
                  setNewSym('')
                }
              }}
              className="btn-primary px-4 py-1.5 text-sm rounded-md"
            >
              Add
            </button>
          </div>
        }
      >
        <div className="table-wrap">
          <table className="w-full">
            <thead className="bg-muted/30">
              <tr>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Feed</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Open</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Prev Close</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Bid</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Ask</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">% Chg</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Source</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground"></th>
              </tr>
            </thead>
            <tbody>
              {watchlist?.map((w) => {
                const q: any = quotes[w.symbol]
                const last =
                  (typeof q?.last === 'number' ? q.last : null) ??
                  (typeof q?.ask === 'number' ? q.ask : null)
                const prevClose =
                  typeof w.prev_close === 'number' ? w.prev_close : null
                const pct =
                  last !== null && prevClose && prevClose !== 0
                    ? ((last - prevClose) / prevClose) * 100
                    : null
                const pctCls =
                  pct === null
                    ? 'text-muted-foreground'
                    : pct >= 0
                      ? 'text-success'
                      : 'text-destructive'
                return (
                  <tr
                    key={w.symbol}
                    className="border-t border-border hover:bg-muted/20 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm">
                      <Link
                        className="text-primary hover:underline"
                        to={`/symbol/${w.symbol}`}
                      >
                        {w.symbol}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <select
                        value={w.feed}
                        onChange={(e) =>
                          updateFeed.mutate({
                            symbol: w.symbol,
                            feed: e.target.value as any,
                          })
                        }
                        className="bg-input-bg border border-border text-foreground px-2 py-1 rounded-md text-xs"
                      >
                        <option value="ws">WS</option>
                        <option value="poll">Poll</option>
                      </select>
                    </td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums">
                      {typeof w.open === 'number' ? w.open.toFixed(2) : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums">
                      {typeof w.prev_close === 'number'
                        ? w.prev_close.toFixed(2)
                        : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums">
                      {q?.bid?.toFixed?.(2) ?? '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums">
                      {q?.ask?.toFixed?.(2) ?? '-'}
                    </td>
                    <td
                      className={`px-4 py-3 text-sm text-right tabular-nums ${pctCls}`}
                    >
                      {pct === null
                        ? '-'
                        : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`}
                    </td>
                    <td className="px-4 py-3 text-xs text-right text-muted-foreground">
                      {q?.source ?? ''}
                    </td>
                    <td className="px-4 py-3 text-sm text-right">
                      <button
                        onClick={() => removeWatch.mutate(w.symbol)}
                        className="text-xs text-primary hover:underline"
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                )
              })}
              {(!watchlist || watchlist.length === 0) && (
                <tr className="border-t border-border">
                  <td
                    colSpan={9}
                    className="px-4 py-8 text-center text-sm text-muted-foreground"
                  >
                    Watchlist empty — add a symbol to start streaming.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
