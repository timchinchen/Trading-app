import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../store/auth'
import type { Quote } from '../api/types'

export function usePriceStream(symbols: string[]) {
  const token = useAuth((s) => s.token)
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!token || symbols.length === 0) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${location.host}/ws/prices?token=${encodeURIComponent(
      token,
    )}&symbols=${encodeURIComponent(symbols.join(','))}`
    const ws = new WebSocket(url)
    wsRef.current = ws
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'ping') return
        if (msg.symbol) {
          setQuotes((prev) => ({ ...prev, [msg.symbol]: msg }))
        }
      } catch {
        /* ignore */
      }
    }
    return () => ws.close()
  }, [token, symbols.join(',')])

  return quotes
}
