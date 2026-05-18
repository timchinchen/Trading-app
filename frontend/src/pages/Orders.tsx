import { Link } from 'react-router-dom'
import { useCancelOrder, useOrders } from '../api/hooks'

const fmtUsd = (v?: number | null) => {
  if (v == null) return '-'
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return '-'
  return `$${n.toFixed(2)}`
}

const fmtPct = (v?: number | null) => {
  if (v == null) return '-'
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return '-'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

export function OrdersPage() {
  const { data: orders } = useOrders()
  const cancel = useCancelOrder()

  return (
    <div className="p-6 space-y-6">
      <section className="panel p-6 space-y-4">
        <h3 className="text-sm text-muted-foreground uppercase tracking-wider">Orders</h3>
        <div className="table-wrap">
          <table className="w-full">
            <thead className="bg-muted/30">
              <tr>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Time</th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Symbol</th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Side</th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Type</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Qty</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Limit</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Fill Px</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Total</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">Current</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">
                  Move since fill
                </th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground">
                  Realized P/L
                </th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground min-w-[200px]">
                  Agent note
                </th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Status</th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Mode</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground"></th>
              </tr>
            </thead>
            <tbody>
              {orders?.map((o) => {
                const pct = o.pct_change
                const pctClass =
                  pct == null
                    ? 'text-muted-foreground'
                    : pct >= 0
                      ? 'text-success'
                      : 'text-danger'
                // For sell orders the P/L sign flips: a rise after a sell is
                // a missed-opportunity cost, not a win. We still show the raw
                // price move but colour it neutrally so the trader can read
                // it unambiguously.
                const sideAwarePctClass = o.side === 'sell'
                  ? 'text-muted-foreground'
                  : pctClass
                const realized = o.realized_pl
                const realizedClass =
                  realized == null
                    ? 'text-muted-foreground'
                    : realized >= 0
                      ? 'text-success'
                      : 'text-danger'

                return (
                  <tr
                    key={o.id}
                    className="border-t border-border hover:bg-muted/20 transition-colors"
                  >
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {new Date(o.submitted_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium">{o.symbol}</td>
                    <td
                      className={`px-4 py-3 text-sm ${
                        o.side === 'buy' ? 'text-success' : 'text-danger'
                      }`}
                    >
                      {o.side}
                    </td>
                    <td className="px-4 py-3 text-sm">{o.type}</td>
                    <td className="px-4 py-3 text-sm text-right">{o.qty}</td>
                    <td className="px-4 py-3 text-sm text-right">
                      {o.limit_price != null ? fmtUsd(o.limit_price) : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-right font-mono">
                      {fmtUsd(o.filled_avg_price)}
                    </td>
                    <td className="px-4 py-3 text-sm text-right font-mono">
                      {fmtUsd(o.total_cost)}
                    </td>
                    <td className="px-4 py-3 text-sm text-right font-mono">
                      {fmtUsd(o.current_price)}
                    </td>
                    <td
                      className={`px-4 py-3 text-sm text-right font-mono ${sideAwarePctClass}`}
                    >
                      {fmtPct(pct)}
                    </td>
                    <td className={`px-4 py-3 text-sm text-right font-mono ${realizedClass}`}>
                      {fmtUsd(realized)}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground align-top max-w-xs">
                      {o.side === 'sell' && o.agent_trade_reason ? (
                        <span className="break-words">
                          {o.agent_trade_reason}
                          {o.agent_trade_run_id != null && (
                            <>
                              {' '}
                              <Link
                                to="/agent"
                                className="text-primary hover:underline whitespace-nowrap"
                                title={`Agent run id ${o.agent_trade_run_id}`}
                              >
                                (run #{o.agent_trade_run_id})
                              </Link>
                            </>
                          )}
                        </span>
                      ) : o.side === 'sell' ? (
                        <span className="text-muted-foreground/70">—</span>
                      ) : (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className="px-2 py-0.5 rounded-md bg-muted/50 border border-border text-xs">
                        {o.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{o.mode}</td>
                    <td className="px-4 py-3 text-sm text-right">
                      {['new', 'accepted', 'pending_new', 'partially_filled'].includes(
                        o.status,
                      ) && (
                        <button
                          className="text-xs text-danger hover:underline"
                          onClick={() => cancel.mutate(o.id)}
                        >
                          cancel
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {(!orders || orders.length === 0) && (
                <tr className="border-t border-border">
                  <td
                    colSpan={15}
                    className="px-4 py-12 text-center text-sm text-muted-foreground"
                  >
                    No orders
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
