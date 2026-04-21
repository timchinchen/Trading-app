import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../store/auth'
import type { Quote } from '../api/types'

/**
 * usePriceStream
 *
 * Opens a single WS connection to /ws/prices and auto-reconnects with
 * exponential backoff if the socket drops (laptop sleep/wake, network
 * blip, backend restart). Without this, a closed socket freezes every
 * Dashboard price until the page is manually refreshed.
 */
export function usePriceStream(symbols: string[]) {
  const token = useAuth((s) => s.token)
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number>(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUs = useRef<boolean>(false)

  useEffect(() => {
    if (!token || symbols.length === 0) return
    closedByUs.current = false

    const envWs = (import.meta as any).env?.VITE_WS_URL as string | undefined
    const base =
      envWs && envWs.length > 0
        ? envWs.replace(/\/$/, '')
        : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`
    const url = `${base}/ws/prices?token=${encodeURIComponent(
      token,
    )}&symbols=${encodeURIComponent(symbols.join(','))}`

    function connect() {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        // Successful handshake resets the backoff so the next flap starts
        // fresh at 1s instead of picking up from wherever it left off.
        retryRef.current = 0
      }

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

      ws.onclose = () => {
        if (closedByUs.current) return
        // Exponential backoff capped at 30s: 1s, 2s, 4s, 8s, 16s, 30s, 30s...
        const attempt = retryRef.current + 1
        retryRef.current = attempt
        const delay = Math.min(30_000, 1_000 * Math.pow(2, attempt - 1))
        reconnectTimerRef.current = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        // Force close so onclose's reconnect path fires.
        try {
          ws.close()
        } catch {
          /* ignore */
        }
      }
    }

    connect()

    return () => {
      closedByUs.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (wsRef.current) {
        try {
          wsRef.current.close()
        } catch {
          /* ignore */
        }
        wsRef.current = null
      }
      retryRef.current = 0
    }
  }, [token, symbols.join(',')])

  return quotes
}
