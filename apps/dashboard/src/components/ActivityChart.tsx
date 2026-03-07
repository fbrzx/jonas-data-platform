/**
 * ActivityChart — inline SVG bar chart for job activity over time.
 *
 * Renders two overlaid bar series (connector runs + transform runs) for the
 * last N days without any external chart library.  Uses the existing Tailwind
 * design tokens via className so it stays on-brand with the rest of the UI.
 */

import type { AuditDayCount } from '../lib/api'

interface Props {
  connectorDays: AuditDayCount[]
  transformDays: AuditDayCount[]
  days?: number
}

const W = 320
const H = 56
const PADDING = { top: 4, right: 4, bottom: 16, left: 0 }
const INNER_W = W - PADDING.left - PADDING.right
const INNER_H = H - PADDING.top - PADDING.bottom

function buildGrid(n: number): string[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date()
    d.setDate(d.getDate() - (n - 1 - i))
    return d.toISOString().slice(0, 10)
  })
}

function mergeSeries(grid: string[], series: AuditDayCount[]): number[] {
  const map = new Map(series.map((d) => [d.day, d.total]))
  return grid.map((day) => map.get(day) ?? 0)
}

export default function ActivityChart({ connectorDays, transformDays, days = 14 }: Props) {
  const grid = buildGrid(days)
  const cVals = mergeSeries(grid, connectorDays)
  const tVals = mergeSeries(grid, transformDays)

  const maxVal = Math.max(1, ...cVals, ...tVals)
  const barW = INNER_W / days
  const gap = Math.max(1, barW * 0.12)
  const halfW = (barW - gap * 3) / 2

  function barHeight(v: number) {
    return Math.max(1, (v / maxVal) * INNER_H)
  }

  // X-axis labels: first + two evenly-spaced interior points + last (true thirds)
  const labelIndices = [
    0,
    Math.round((days - 1) / 3),
    Math.round(2 * (days - 1) / 3),
    days - 1,
  ]

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      aria-label="Activity over time"
      style={{ display: 'block', overflow: 'visible' }}
    >
      {/* Grid line */}
      <line
        x1={PADDING.left} y1={PADDING.top + INNER_H}
        x2={W - PADDING.right} y2={PADDING.top + INNER_H}
        stroke="currentColor" strokeOpacity="0.12" strokeWidth="1"
      />

      {grid.map((day, i) => {
        const x = PADDING.left + i * barW
        const ch = barHeight(cVals[i])
        const th = barHeight(tVals[i])
        const cy = PADDING.top + INNER_H - ch
        const ty = PADDING.top + INNER_H - th

        return (
          <g key={day}>
            {/* Connector bar — amber */}
            <rect
              x={x + gap}
              y={cy}
              width={halfW}
              height={ch}
              fill="#b45309"
              fillOpacity={cVals[i] > 0 ? 0.75 : 0.15}
              rx="1"
            />
            {/* Transform bar — accent blue */}
            <rect
              x={x + gap * 2 + halfW}
              y={ty}
              width={halfW}
              height={th}
              fill="#38bdf8"
              fillOpacity={tVals[i] > 0 ? 0.65 : 0.1}
              rx="1"
            />
          </g>
        )
      })}

      {/* X-axis labels */}
      {labelIndices.map((i) => (
        <text
          key={i}
          x={PADDING.left + i * barW + barW / 2}
          y={H - 1}
          textAnchor="middle"
          fontSize="7"
          fill="currentColor"
          fillOpacity="0.4"
          fontFamily="monospace"
        >
          {grid[i]?.slice(5)}
        </text>
      ))}

      {/* Legend */}
      <rect x={W - 60} y={PADDING.top} width={6} height={6} fill="#b45309" fillOpacity="0.75" rx="1" />
      <text x={W - 51} y={PADDING.top + 6} fontSize="7" fill="currentColor" fillOpacity="0.5" fontFamily="monospace">connector</text>
      <rect x={W - 60} y={PADDING.top + 10} width={6} height={6} fill="#38bdf8" fillOpacity="0.65" rx="1" />
      <text x={W - 51} y={PADDING.top + 16} fontSize="7" fill="currentColor" fillOpacity="0.5" fontFamily="monospace">transform</text>
    </svg>
  )
}
