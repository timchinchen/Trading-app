import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuote } from '../api/hooks'
import { OrderTicket } from '../components/OrderTicket'
import { PriceChart } from '../components/Chart'
import { usePriceStream } from '../hooks/usePriceStream'

function fmt(n: unknown): string {
  const v = typeof n === 'string' ? parseFloat(n) : (n as number | null | undefined)
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return v.toFixed(2)
}

export function SymbolPage() {
  const { symbol = '' } = useParams()
  const sym = symbol.toUpperCase()
  const { data: snapshot } = useQuote(sym)
  // Freeze the symbol array so usePriceStream's effect doesn't tear
  // down + reopen the WS on every parent re-render.
  const symList = useMemo(() => [sym], [sym])
  const stream = usePriceStream(symList)
  const live: any = stream[sym]
  const [history, setHistory] = useState<{ time: number; value: number }[]>([])

  useEffect(() => {
    setHistory([])
  }, [sym])

  const lastPrice = live?.last ?? live?.ask ?? snapshot?.last ?? snapshot?.ask
  useEffect(() => {
    if (lastPrice === null || lastPrice === undefined) return
    const v = typeof lastPrice === 'string' ? parseFloat(lastPrice) : lastPrice
    if (!Number.isFinite(v)) return
    const t = Math.floor(Date.now() / 1000)
    setHistory((h) => {
      const next = [...h, { time: t, value: v }]
      return next.slice(-300)
    })
  }, [lastPrice])

  const display = live ?? snapshot

  return (
    <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
      <section className="panel p-6 lg:col-span-2">
        <div className="flex items-end justify-between mb-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-transparent bg-clip-text bg-cosmic-text">
              {sym}
            </h1>
            <div className="text-xs text-muted-foreground mt-1">
              bid {fmt(display?.bid)} · ask {fmt(display?.ask)} · last{' '}
              {fmt(display?.last ?? display?.ask)}
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-border overflow-hidden bg-muted/10">
          <PriceChart data={history} />
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          Chart shows live tick history since opening this page.
        </p>
      </section>
      <div>
        <OrderTicket symbol={sym} />
      </div>
    </div>
  )
}
