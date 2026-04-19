import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuote } from '../api/hooks'
import { OrderTicket } from '../components/OrderTicket'
import { PriceChart } from '../components/Chart'
import { usePriceStream } from '../hooks/usePriceStream'

export function SymbolPage() {
  const { symbol = '' } = useParams()
  const sym = symbol.toUpperCase()
  const { data: snapshot } = useQuote(sym)
  const stream = usePriceStream([sym])
  const live: any = stream[sym]
  const [history, setHistory] = useState<{ time: number; value: number }[]>([])

  useEffect(() => {
    setHistory([])
  }, [sym])

  useEffect(() => {
    const last = live?.last ?? live?.ask ?? snapshot?.last ?? snapshot?.ask
    if (last) {
      const t = Math.floor(Date.now() / 1000)
      setHistory((h) => {
        const next = [...h, { time: t, value: Number(last) }]
        return next.slice(-300)
      })
    }
  }, [live?.last, live?.ask, snapshot?.last, snapshot?.ask])

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
              bid {display?.bid?.toFixed?.(2) ?? '-'} · ask{' '}
              {display?.ask?.toFixed?.(2) ?? '-'} · last{' '}
              {(display?.last ?? display?.ask)?.toFixed?.(2) ?? '-'}
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
