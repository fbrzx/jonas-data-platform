/**
 * ActivityChart — stacked bar chart of connector + transform runs per day.
 * Uses Observable Plot for proper axes, grid, tooltips and dark-theme styling.
 */
import * as Plot from '@observablehq/plot'
import { useEffect, useRef } from 'react'
import type { AuditDayCount } from '../lib/api'

interface Props {
  connectorDays: AuditDayCount[]
  transformDays: AuditDayCount[]
  days?: number
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function buildGrid(n: number): string[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date()
    d.setDate(d.getDate() - (n - 1 - i))
    return d.toISOString().slice(0, 10)
  })
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function ActivityChart({ connectorDays, transformDays, days = 14 }: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const w = ref.current.clientWidth || 680

    const grid = buildGrid(days)
    const cMap = new Map(connectorDays.map((d) => [d.day, d.total]))
    const tMap = new Map(transformDays.map((d) => [d.day, d.total]))

    // Flat data for stacked barY — connectors first (bottom), transforms on top
    const data: { day: string; n: number; series: string }[] = [
      ...grid.map((day) => ({ day, n: cMap.get(day) ?? 0, series: 'connector' })),
      ...grid.map((day) => ({ day, n: tMap.get(day) ?? 0, series: 'transform' })),
    ]

    const maxVal = Math.max(
      1,
      ...grid.map((day) => (cMap.get(day) ?? 0) + (tMap.get(day) ?? 0)),
    )

    let chart: SVGSVGElement | HTMLElement
    try {
      chart = Plot.plot({
        width: w,
        height: 170,
        marginTop: 14,
        marginLeft: 38,
        marginBottom: 34,
        marginRight: 8,
        style: {
          background: 'transparent',
          color: '#5a6478',
          fontFamily: 'monospace',
          fontSize: '10px',
          overflow: 'visible',
        },
        x: {
          label: null,
          tickFormat: (d: string) => d.slice(5),
          tickSpacing: 52,
          tickSize: 3,
          tickPadding: 5,
        },
        y: {
          domain: [0, maxVal],
          grid: true,
          label: 'runs',
          tickFormat: (n: number) => (Number.isInteger(n) ? String(n) : ''),
          tickSize: 0,
          labelOffset: 34,
          labelAnchor: 'top',
          ticks: Math.min(5, maxVal) as number,
        },
        color: {
          domain: ['connector', 'transform'],
          range: ['#f5a623', '#4a9eff'],
        },
        marks: [
          Plot.barY(
            data,
            Plot.stackY({
              x: 'day',
              y: 'n',
              fill: 'series',
              rx: 2,
              order: ['connector', 'transform'],
              title: (d: { day: string; n: number; series: string }) =>
                `${d.day}\n${d.series}: ${d.n} run${d.n !== 1 ? 's' : ''}`,
            }),
          ),
          Plot.ruleY([0], { stroke: '#1e2430', strokeWidth: 1 }),
        ],
      })
    } catch {
      return
    }

    ref.current.innerHTML = ''
    ref.current.append(chart)
    const el = ref.current
    return () => {
      if (el) el.innerHTML = ''
    }
  }, [connectorDays, transformDays, days])

  return (
    <div className="px-4 pt-3 pb-1">
      {/* Legend */}
      <div className="flex items-center gap-5 mb-0.5">
        {([
          { label: 'connectors', color: '#f5a623' },
          { label: 'transforms', color: '#4a9eff' },
        ] as const).map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1.5">
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                background: color,
                display: 'inline-block',
                opacity: 0.9,
              }}
            />
            <span className="font-mono text-[10px] text-j-dim">{label}</span>
          </div>
        ))}
      </div>
      <div ref={ref} className="w-full" />
    </div>
  )
}
