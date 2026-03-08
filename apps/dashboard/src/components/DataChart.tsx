/**
 * DataChart — auto-selects the best Observable Plot chart from preview data.
 *
 * Chart type heuristics (evaluated in priority order):
 *  1. date/time column + numeric column  → area + line time series
 *  2. categorical column (≤25 unique)    → horizontal bar (sorted, top 20)
 *  3. two numeric columns                → scatter / dot plot
 *  4. single numeric column              → histogram
 *
 * ID-like columns (name matches /^id$|_id$|uid|uuid|guid/i, or col with all
 * unique values in a large dataset) are excluded from analysis.
 */
import * as Plot from '@observablehq/plot'
import { useEffect, useMemo, useRef, useState } from 'react'

export interface PreviewRow {
  [col: string]: unknown
}

interface Props {
  columns: string[]
  rows: PreviewRow[]
}

// ── Palette (matches j-* Tailwind tokens) ────────────────────────────────────

const C = {
  accent:   '#4a9eff',
  amber:    '#f5a623',
  green:    '#2dcc7a',
  dim:      '#5a6478',
  border:   '#1e2430',
  surface:  '#111318',
  surface2: '#181c24',
  bright:   '#edf2f8',
  text:     '#c8d0dc',
}

const PLOT_STYLE = {
  background: 'transparent',
  color: C.dim,
  fontFamily: 'monospace',
  fontSize: '10px',
  overflow: 'visible',
} as const

// ── Column classification ─────────────────────────────────────────────────────

/** Skip columns that are clearly identifiers, URLs, or JSON blobs. */
function isUnplottable(col: string, values: unknown[]): boolean {
  // ID-like column name
  if (/^(id|.*_id|uid|uuid|guid|pk|key|hash|token|slug|url|href|link)$/i.test(col)) return true
  const sample = values.filter((v) => v !== null && v !== undefined && v !== '').slice(0, 5)
  if (!sample.length) return true
  // URL values
  if (sample.every((v) => /^https?:\/\//.test(String(v)))) return true
  // JSON array / object values
  if (sample.every((v) => { const s = String(v).trim(); return s.startsWith('[') || s.startsWith('{') })) return true
  // Very long string values (free text)
  if (sample.every((v) => String(v).length > 80)) return true
  return false
}

/**
 * A column is numeric if at least 70% of non-null values parse as numbers.
 * This tolerates "unknown" / "N/A" sentinel strings mixed into numeric data.
 */
function isNumeric(values: unknown[]): boolean {
  const sample = values.filter((v) => v !== null && v !== undefined && v !== '').slice(0, 30)
  if (!sample.length) return false
  const numCount = sample.filter((v) => !isNaN(Number(v))).length
  return numCount / sample.length >= 0.7
}

/**
 * A column is date-like only if the column name explicitly signals it
 * (whole-word match or suffix), or if values look like ISO-ish date strings.
 * Deliberately avoids matching substrings like "at" in "rotation".
 */
function isDateLike(col: string, values: unknown[]): boolean {
  if (/\b(date|time|timestamp)\b/i.test(col)) return true
  if (/(_at|_on|_date|_time)$/i.test(col)) return true
  if (/^(created|updated|started|ended|deleted|modified)_/i.test(col)) return true
  // Value heuristic: must contain a 4-digit year to be considered a date
  const sample = values.filter(Boolean).slice(0, 5)
  return (
    sample.length > 0 &&
    sample.every((v) => {
      const s = String(v)
      if (!/\d{4}/.test(s)) return false
      const d = Date.parse(s)
      return !isNaN(d) && d > 946684800000 // after year 2000
    })
  )
}

/**
 * A column is categorical if it has few enough unique values AND
 * values aren't all unique (which would make it an ID / free-text column).
 */
function isCategorical(values: unknown[], threshold = 25): boolean {
  const nonNull = values.filter((v) => v !== null && v !== undefined && v !== '')
  const uniq = new Set(nonNull.map(String))
  // Reject if cardinality == total (all-unique → ID or free text)
  if (uniq.size === nonNull.length && nonNull.length > 5) return false
  return uniq.size >= 2 && uniq.size <= threshold
}

// ── Helpers ──────────────────────────────────────────────────────────────────

type ChartType = 'time-series' | 'bar' | 'scatter' | 'histogram' | 'none'

/** Well-known label columns that work as bar chart axes even if all values are unique. */
function isLabelCol(col: string): boolean {
  return /^(name|label|title|description|category|type|status|kind|tag|group|region|country|city)$/i.test(col)
}

function chooseChart(
  columns: string[],
  colValues: Record<string, unknown[]>,
): { type: ChartType; x: string; y: string; y2?: string } {
  const usable = columns.filter((c) => !isUnplottable(c, colValues[c]))
  const dateCols   = usable.filter((c) => isDateLike(c, colValues[c]))
  const numericCols = usable.filter(
    (c) => !dateCols.includes(c) && isNumeric(colValues[c]),
  )
  // Label cols: semantically meaningful strings (name/title/…) — always good bar axis
  const labelCols = usable.filter(
    (c) => !dateCols.includes(c) && !numericCols.includes(c) && isLabelCol(c),
  )
  // Categorical cols: low-cardinality non-label strings
  const catCols = usable.filter(
    (c) =>
      !dateCols.includes(c) &&
      !numericCols.includes(c) &&
      !labelCols.includes(c) &&
      isCategorical(colValues[c]),
  )
  const allLabelCols = [...labelCols, ...catCols]

  if (dateCols.length && numericCols.length)
    return { type: 'time-series', x: dateCols[0], y: numericCols[0] }
  if (allLabelCols.length && numericCols.length) {
    const labelCol = allLabelCols[0]
    // Pick the most interesting numeric col (prefer count/sum over raw IDs)
    const metricCol = numericCols.find((c) => !/^(count|n|total)$/i.test(c)) ?? numericCols[0]
    return { type: 'bar', x: metricCol, y: labelCol }
  }
  if (numericCols.length >= 2)
    return { type: 'scatter', x: numericCols[0], y: numericCols[1], y2: allLabelCols[0] }
  if (numericCols.length === 1)
    return { type: 'histogram', x: numericCols[0], y: '' }

  return { type: 'none', x: '', y: '' }
}

const CHART_LABEL: Record<ChartType, string> = {
  'time-series': 'time series',
  bar:           'bar chart',
  scatter:       'scatter',
  histogram:     'histogram',
  none:          '',
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DataChart({ columns, rows }: Props) {
  const ref   = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  // Compute chart choice synchronously so the ref-div can be mounted on the first render
  const colValues = useMemo(
    () => Object.fromEntries(columns.map((c) => [c, rows.map((r) => r[c])])),
    [columns, rows],
  )
  const choice = useMemo(() => chooseChart(columns, colValues), [columns, colValues])

  useEffect(() => {
    setError(null)
    if (!ref.current || !rows.length || choice.type === 'none') return

    const { type, x, y, y2 } = choice

    const w = ref.current.clientWidth || 600

    // Cast row values: numbers become Number, dates become Date
    const numericCols = columns.filter(
      (c) => !isUnplottable(c, colValues[c]) && isNumeric(colValues[c]),
    )
    const dateCols = columns.filter(
      (c) => !isUnplottable(c, colValues[c]) && isDateLike(c, colValues[c]),
    )

    const data = rows.map((r) => {
      const row: Record<string, unknown> = { ...r }
      for (const c of numericCols) row[c] = Number(row[c])
      for (const c of dateCols)    row[c] = new Date(String(row[c]))
      return row
    })

    let chart: SVGSVGElement | HTMLElement

    try {
      if (type === 'time-series') {
        chart = Plot.plot({
          width: w,
          height: 220,
          marginLeft: 50,
          marginBottom: 42,
          marginRight: 8,
          marginTop: 12,
          style: PLOT_STYLE,
          x: {
            label: x,
            tickFormat: (d: Date) =>
              d.toLocaleDateString('en', { month: 'short', day: 'numeric' }),
            tickSpacing: 80,
            tickSize: 3,
          },
          y: { label: y, grid: true, tickSize: 0 },
          marks: [
            Plot.areaY(data, {
              x,
              y,
              fill: C.accent,
              fillOpacity: 0.12,
              curve: 'monotone-x',
            }),
            Plot.lineY(data, {
              x,
              y,
              stroke: C.accent,
              strokeWidth: 2,
              curve: 'monotone-x',
            }),
            Plot.dotY(data, {
              x,
              y,
              fill: C.accent,
              r: 3,
              stroke: C.surface,
              strokeWidth: 1.5,
            }),
            Plot.ruleY([0], { stroke: C.border }),
          ],
        })
      } else if (type === 'bar') {
        const sorted = [...data]
          .sort((a, b) => Number(b[x]) - Number(a[x]))
          .slice(0, 20)
        chart = Plot.plot({
          width: w,
          height: Math.max(180, sorted.length * 24 + 60),
          marginLeft: 130,
          marginBottom: 40,
          marginRight: 24,
          marginTop: 12,
          style: PLOT_STYLE,
          x: { label: x, grid: true, tickSize: 0 },
          y: { label: null },
          marks: [
            Plot.barX(sorted, {
              x,
              y,
              fill: C.amber,
              fillOpacity: 0.85,
              rx: 2,
              sort: { y: 'x', reverse: true },
              title: (d: Record<string, unknown>) => `${d[y]}: ${d[x]}`,
            }),
            Plot.ruleX([0], { stroke: C.border }),
          ],
        })
      } else if (type === 'scatter') {
        chart = Plot.plot({
          width: w,
          height: 240,
          marginLeft: 54,
          marginBottom: 42,
          marginRight: 12,
          marginTop: 12,
          style: PLOT_STYLE,
          x: { label: x, grid: true, tickSize: 0 },
          y: { label: y, grid: true, tickSize: 0 },
          color: y2
            ? { legend: true, scheme: 'Observable10' }
            : undefined,
          marks: [
            Plot.dot(data, {
              x,
              y,
              fill: y2 ? y2 : C.accent,
              r: 4,
              fillOpacity: 0.75,
              stroke: y2 ? undefined : C.surface,
              strokeWidth: y2 ? 0 : 1,
              title: (d: Record<string, unknown>) =>
                `${x}: ${d[x]}\n${y}: ${d[y]}`,
            }),
          ],
        })
      } else {
        // histogram
        chart = Plot.plot({
          width: w,
          height: 200,
          marginLeft: 50,
          marginBottom: 40,
          marginRight: 8,
          marginTop: 12,
          style: PLOT_STYLE,
          color: { range: [C.accent] },
          x: { label: x, tickSize: 3 },
          y: { label: 'count', grid: true, tickSize: 0 },
          marks: [
            Plot.rectY(data, Plot.binX({ y: 'count' }, { x })),
            Plot.ruleY([0], { stroke: C.border }),
          ],
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'chart error')
      return
    }

    ref.current.innerHTML = ''
    ref.current.append(chart)
    const el = ref.current
    return () => {
      if (el) el.innerHTML = ''
    }
  }, [columns, rows, choice, colValues])

  if (!rows.length) return null

  if (error) {
    return (
      <p className="font-mono text-[10px] text-j-red italic px-2 py-2">
        chart error — {error}
      </p>
    )
  }

  if (choice.type === 'none') {
    return (
      <p className="font-mono text-[10px] text-j-dim italic px-2 py-2">
        no numeric or date columns — chart unavailable
      </p>
    )
  }

  return (
    <div>
      <div className="flex items-center gap-2 px-0.5 mb-0.5">
        <span className="font-mono text-[9px] tracking-[0.12em] uppercase text-j-dim border border-j-border rounded px-1.5 py-0.5">
          {CHART_LABEL[choice.type]}
        </span>
        <span className="font-mono text-[9px] text-j-border">
          {rows.length} row{rows.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div ref={ref} className="w-full overflow-x-auto" />
    </div>
  )
}
