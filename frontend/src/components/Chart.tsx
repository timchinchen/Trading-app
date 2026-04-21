import { useEffect, useRef } from 'react'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineData,
  UTCTimestamp,
} from 'lightweight-charts'

export function PriceChart({ data }: { data: { time: number; value: number }[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  useEffect(() => {
    const host = ref.current
    if (!host) return
    let chart: IChartApi | null = null
    try {
      chart = createChart(host, {
        layout: { background: { color: '#14141f' }, textColor: '#9d8bb4' },
        grid: {
          vertLines: { color: 'rgba(157,139,180,0.08)' },
          horzLines: { color: 'rgba(157,139,180,0.08)' },
        },
        // clientWidth can be 0 on the very first paint (flex parent
        // hasn't laid out yet). Fall back to a sane default so
        // lightweight-charts doesn't throw on a zero-width canvas.
        width: host.clientWidth || 600,
        height: 320,
      })
      const series = chart.addLineSeries({ color: '#d45d79', lineWidth: 2 })
      chartRef.current = chart
      seriesRef.current = series
    } catch (e) {
      console.error('[PriceChart] failed to init chart', e)
      return
    }

    // Observe container resize so the chart reflows when the sidebar
    // collapses, the window is resized, or the layout settles after
    // first paint. Far more robust than a window resize listener.
    const ro = new ResizeObserver(() => {
      if (!chart || !host) return
      const w = host.clientWidth
      if (w > 0) chart.applyOptions({ width: w })
    })
    ro.observe(host)

    return () => {
      ro.disconnect()
      try {
        chart?.remove()
      } catch {
        /* chart already disposed */
      }
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    try {
      const ld: LineData[] = data.map((d) => ({
        time: d.time as UTCTimestamp,
        value: d.value,
      }))
      series.setData(ld)
    } catch (e) {
      console.error('[PriceChart] setData failed', e)
    }
  }, [data])

  return <div ref={ref} className="w-full min-h-[320px]" />
}
