import { useEffect, useState } from 'react'
import { useMode, usePlaceOrder, usePositions } from '../api/hooks'

// Format a share qty for display in the "Sell all" hint. Alpaca returns
// fractional shares (e.g. 0.2667) so we keep up to 6 dp, trimming
// trailing zeros to avoid "1.000000".
function fmtQty(q: number): string {
  if (!Number.isFinite(q) || q <= 0) return '0'
  const s = q.toFixed(6)
  return s.replace(/\.?0+$/, '')
}

export function OrderTicket({ symbol }: { symbol: string }) {
  const [qty, setQty] = useState<number>(1)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [type, setType] = useState<'market' | 'limit'>('market')
  const [limit, setLimit] = useState<string>('')
  const [userEditedQty, setUserEditedQty] = useState(false)
  const { data: mode } = useMode()
  const { data: positions } = usePositions()
  const place = usePlaceOrder()

  // Current held qty for this symbol (0 if not held). Alpaca uses signed
  // qty; we only offer "sell all" for long positions here.
  const heldQty =
    positions?.find((p) => p.symbol.toUpperCase() === symbol.toUpperCase())
      ?.qty ?? 0
  const hasLong = heldQty > 0

  // Auto-prefill the sell qty with the full held position the first time
  // the user flips to Sell (or when the page loads already on Sell, e.g.
  // after side changes). If the user has manually edited the qty we
  // don't clobber it.
  useEffect(() => {
    if (side !== 'sell') return
    if (!hasLong) return
    if (userEditedQty) return
    setQty(heldQty)
  }, [side, hasLong, heldQty, userEditedQty])

  const submit = async () => {
    const isLive = mode?.mode === 'live'
    const confirmText = isLive
      ? `LIVE order: ${side.toUpperCase()} ${qty} ${symbol} (${type}${
          type === 'limit' ? ` @ ${limit}` : ''
        }). This will use REAL money. Continue?`
      : `Paper order: ${side.toUpperCase()} ${qty} ${symbol} (${type}${
          type === 'limit' ? ` @ ${limit}` : ''
        }). Continue?`
    if (!window.confirm(confirmText)) return
    try {
      await place.mutateAsync({
        symbol,
        qty,
        side,
        type,
        limit_price: type === 'limit' ? Number(limit) : undefined,
      })
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Order failed')
    }
  }

  return (
    <div className="panel p-6 space-y-4">
      <h3 className="text-sm text-muted-foreground uppercase tracking-wider">
        Order ticket
      </h3>
      <div className="flex gap-2 p-1 bg-muted/40 rounded-lg">
        <button
          onClick={() => {
            setSide('buy')
            setUserEditedQty(false)
          }}
          className={`flex-1 py-2 rounded-md text-sm transition-all ${
            side === 'buy'
              ? 'bg-success/20 text-success shadow-[inset_0_0_0_1px_rgba(61,220,151,0.35)]'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          Buy
        </button>
        <button
          onClick={() => {
            setSide('sell')
            setUserEditedQty(false)
          }}
          className={`flex-1 py-2 rounded-md text-sm transition-all ${
            side === 'sell'
              ? 'bg-destructive/20 text-destructive shadow-[inset_0_0_0_1px_rgba(232,93,117,0.35)]'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          Sell
        </button>
      </div>
      <div className="space-y-2">
        <label className="text-xs text-muted-foreground">Order type</label>
        <select
          value={type}
          onChange={(e) => setType(e.target.value as any)}
          className="w-full bg-input-bg border border-border text-foreground px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="market">Market</option>
          <option value="limit">Limit</option>
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs text-muted-foreground">Qty</label>
            {side === 'sell' && hasLong && (
              <button
                type="button"
                onClick={() => {
                  setQty(heldQty)
                  setUserEditedQty(false)
                }}
                className="text-[10px] text-primary hover:underline uppercase tracking-wider"
                title={`Sell all ${fmtQty(heldQty)} shares`}
              >
                Sell all ({fmtQty(heldQty)})
              </button>
            )}
          </div>
          <input
            type="number"
            min={0}
            step="any"
            value={qty}
            onChange={(e) => {
              setQty(Number(e.target.value))
              setUserEditedQty(true)
            }}
            className="w-full bg-input-bg border border-border text-foreground px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          {side === 'sell' && !hasLong && (
            <div className="text-[10px] text-muted-foreground">
              No open long position in {symbol}.
            </div>
          )}
        </div>
        {type === 'limit' && (
          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Limit</label>
            <input
              type="number"
              step="any"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className="w-full bg-input-bg border border-border text-foreground placeholder:text-muted-foreground px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              placeholder="Price"
            />
          </div>
        )}
      </div>
      <button
        onClick={submit}
        disabled={place.isPending}
        className="btn-primary w-full py-2.5 rounded-lg"
      >
        {place.isPending ? 'Submitting...' : `Submit ${side.toUpperCase()} ${symbol}`}
      </button>
    </div>
  )
}
