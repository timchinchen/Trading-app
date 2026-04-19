import { useMode } from '../api/hooks'

export function ModeBanner() {
  const { data } = useMode()
  if (!data) return null
  const isLive = data.mode === 'live'
  return (
    <div
      className={`relative px-6 py-2.5 flex items-center justify-between text-white overflow-hidden ${
        isLive
          ? 'bg-gradient-to-r from-rose-800 via-red-600 to-rose-500'
          : 'bg-cosmic-banner'
      }`}
    >
      <div className="flex items-center gap-4">
        <span className="font-semibold tracking-wide text-sm">
          {isLive
            ? 'LIVE MODE — real orders will be placed with Alpaca'
            : 'PAPER MODE — simulated trades, no real money'}
        </span>
        <span className="text-white/80 text-xs">
          market data: {data.market_data_mode} · max order: ${data.max_order_notional}
        </span>
      </div>
    </div>
  )
}
