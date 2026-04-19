import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, LineData, UTCTimestamp } from 'lightweight-charts'

export function PriceChart({ data }: { data: { time: number; value: number }[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, {
      layout: { background: { color: '#14141f' }, textColor: '#9d8bb4' },
      grid: {
        vertLines: { color: 'rgba(157,139,180,0.08)' },
        horzLines: { color: 'rgba(157,139,180,0.08)' },
      },
      width: ref.current.clientWidth,
      height: 320,
    })
    const series = chart.addLineSeries({ color: '#d45d79', lineWidth: 2 })
    chartRef.current = chart
    seriesRef.current = series
    const onResize = () => chart.applyOptions({ width: ref.current!.clientWidth })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current) return
    const ld: LineData[] = data.map((d) => ({
      time: d.time as UTCTimestamp,
      value: d.value,
    }))
    seriesRef.current.setData(ld)
  }, [data])

  return <div ref={ref} className="w-full" />
}
