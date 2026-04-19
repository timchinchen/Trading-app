import { useCancelOrder, useOrders } from '../api/hooks'

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
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Status</th>
                <th className="px-4 py-3 text-left text-xs text-muted-foreground">Mode</th>
                <th className="px-4 py-3 text-right text-xs text-muted-foreground"></th>
              </tr>
            </thead>
            <tbody>
              {orders?.map((o) => (
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
                  <td className="px-4 py-3 text-sm text-right">{o.limit_price ?? '-'}</td>
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
              ))}
              {(!orders || orders.length === 0) && (
                <tr className="border-t border-border">
                  <td
                    colSpan={9}
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
