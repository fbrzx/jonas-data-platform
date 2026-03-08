import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { getToken, getActiveTenantId } from '../lib/api'
import DataChart from '../components/DataChart'

// ── Types ─────────────────────────────────────────────────────────────────────

interface TableInfo {
  schema: string
  table: string
  layer: string
}

interface QueryResult {
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  duration_ms: number
  truncated: boolean
}

// ── Layer badge ───────────────────────────────────────────────────────────────

const LAYER_COLOR: Record<string, string> = {
  bronze: 'text-j-amber  border-j-amber  bg-j-amber-dim',
  silver: 'text-j-accent border-j-accent bg-j-accent-dim',
  gold:   'text-j-bright border-j-bright bg-j-surface2',
}

function LayerBadge({ layer }: { layer: string }) {
  return (
    <span className={`px-1.5 py-0.5 rounded font-mono text-[9px] border ${LAYER_COLOR[layer] ?? 'text-j-dim border-j-border'}`}>
      {layer}
    </span>
  )
}

// ── Example queries ───────────────────────────────────────────────────────────

const EXAMPLES = [
  { label: 'List tables',         sql: "SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2" },
  { label: 'Browse bronze',       sql: 'SELECT * FROM bronze.orders LIMIT 20' },
  { label: 'Browse silver',       sql: 'SELECT * FROM silver.orders_cleaned LIMIT 20' },
  { label: 'Count by layer',      sql: "SELECT table_schema AS layer, COUNT(*) AS tables FROM information_schema.tables GROUP BY 1 ORDER BY 1" },
]

// ── Result table ──────────────────────────────────────────────────────────────

function ResultTable({ result }: { result: QueryResult }) {
  const [viewMode, setViewMode] = useState<'table' | 'chart'>('table')

  return (
    <div className="flex flex-col gap-3 min-h-0">
      {/* Toolbar */}
      <div className="flex items-center gap-3 shrink-0">
        <span className="font-mono text-[10px] text-j-dim">
          {result.row_count} row{result.row_count !== 1 ? 's' : ''}
          {result.truncated ? ' (truncated to 500)' : ''}
          {' · '}{result.duration_ms.toFixed(1)} ms
        </span>
        <div className="flex gap-1 ml-auto">
          {(['table', 'chart'] as const).map(mode => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`px-2 py-0.5 rounded font-mono text-[10px] border transition-colors ${
                viewMode === mode
                  ? 'bg-j-accent-dim text-j-accent border-j-accent'
                  : 'text-j-dim border-j-border hover:text-j-text hover:border-j-dim'
              }`}
            >
              {mode === 'table' ? '⊞ table' : '▲ chart'}
            </button>
          ))}
        </div>
      </div>

      {viewMode === 'table' ? (
        <div className="overflow-auto flex-1 border border-j-border rounded">
          <table className="w-full font-mono text-[11px] border-collapse">
            <thead className="sticky top-0 bg-j-surface2 z-10">
              <tr>
                {result.columns.map(col => (
                  <th key={col} className="px-3 py-2 text-left text-j-dim font-medium border-b border-j-border whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i} className="border-b border-j-border/40 hover:bg-j-surface2 transition-colors">
                  {result.columns.map(col => (
                    <td key={col} className="px-3 py-1.5 text-j-text whitespace-nowrap max-w-xs truncate">
                      {row[col] === null || row[col] === undefined
                        ? <span className="text-j-border italic">null</span>
                        : String(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex-1 overflow-hidden border border-j-border rounded p-3 bg-j-surface">
          <DataChart columns={result.columns} rows={result.rows} />
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function QueryWorkbenchPage() {
  const [sql, setSql] = useState('SELECT * FROM gold.metrics LIMIT 20')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const gutterRef = useRef<HTMLDivElement>(null)

  const { data: tables = [] } = useQuery<TableInfo[]>({
    queryKey: ['query-tables'],
    queryFn: () => {
      const tid = getActiveTenantId()
      return fetch('/api/v1/query/tables', {
        headers: {
          Authorization: `Bearer ${getToken()}`,
          ...(tid ? { 'X-Tenant-ID': tid } : {}),
        },
      }).then(async r => {
        if (!r.ok) return []
        return r.json() as Promise<TableInfo[]>
      })
    },
    staleTime: 60_000,
  })

  const mutation = useMutation({
    mutationFn: (sqlQuery: string) => {
      const tid = getActiveTenantId()
      return fetch('/api/v1/query', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
          ...(tid ? { 'X-Tenant-ID': tid } : {}),
        },
        body: JSON.stringify({ sql: sqlQuery }),
      }).then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({ detail: r.statusText })) as { detail?: string }
          throw new Error(body.detail ?? `HTTP ${r.status}`)
        }
        return r.json() as Promise<QueryResult>
      })
    },
    onSuccess: (data) => {
      setResult(data)
      setError(null)
    },
    onError: (err: Error) => {
      setError(err.message)
      setResult(null)
    },
  })

  const runQuery = useCallback(() => {
    const trimmed = sql.trim()
    if (!trimmed) return
    mutation.mutate(trimmed)
  }, [sql, mutation])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      runQuery()
    }
    // Tab → insert 2 spaces
    if (e.key === 'Tab') {
      e.preventDefault()
      const el = e.currentTarget
      const start = el.selectionStart
      const end = el.selectionEnd
      const newVal = sql.slice(0, start) + '  ' + sql.slice(end)
      setSql(newVal)
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = start + 2
      })
    }
  }

  const insertTable = (schema: string, table: string) => {
    const insert = `${schema}.${table}`
    setSql(prev => prev ? `${prev}\n-- ${insert}` : `SELECT * FROM ${insert} LIMIT 20`)
    textareaRef.current?.focus()
  }

  // Group tables by layer
  const byLayer = tables.reduce<Record<string, TableInfo[]>>((acc, t) => {
    const key = t.layer ?? 'other'
    ;(acc[key] ??= []).push(t)
    return acc
  }, {})

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Sidebar: table browser ───────────────────────────────────────── */}
      <aside className="w-52 shrink-0 border-r border-j-border bg-j-surface flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-j-border shrink-0">
          <div className="font-mono text-[10px] text-j-dim tracking-[0.16em] uppercase">Tables</div>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {(['bronze', 'silver', 'gold'] as const).map(layer => {
            const layerTables = byLayer[layer] ?? []
            if (!layerTables.length) return null
            return (
              <div key={layer} className="mb-3">
                <div className="px-4 py-1 flex items-center gap-2">
                  <LayerBadge layer={layer} />
                </div>
                {layerTables.map(t => (
                  <button
                    key={`${t.schema}.${t.table}`}
                    onClick={() => insertTable(t.schema, t.table)}
                    className="w-full text-left px-4 py-1 font-mono text-[10px] text-j-dim hover:text-j-text hover:bg-j-surface2 transition-colors truncate"
                    title={`${t.schema}.${t.table}`}
                  >
                    {t.table}
                  </button>
                ))}
              </div>
            )
          })}
          {tables.length === 0 && (
            <div className="px-4 py-2 font-mono text-[10px] text-j-border italic">No tables found</div>
          )}
        </div>

        {/* Examples */}
        <div className="border-t border-j-border shrink-0">
          <div className="px-4 py-2 font-mono text-[10px] text-j-dim tracking-[0.16em] uppercase">Examples</div>
          {EXAMPLES.map(ex => (
            <button
              key={ex.label}
              onClick={() => setSql(ex.sql)}
              className="w-full text-left px-4 py-1.5 font-mono text-[10px] text-j-dim hover:text-j-accent hover:bg-j-accent-dim transition-colors truncate"
              title={ex.sql}
            >
              {ex.label}
            </button>
          ))}
        </div>
      </aside>

      {/* ── Main area ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* Editor */}
        <div className="shrink-0 border-b border-j-border bg-j-bg">
          <div className="flex items-center gap-2 px-4 py-2 border-b border-j-border/40">
            <span className="font-mono text-[10px] text-j-dim tracking-[0.16em] uppercase flex-1">SQL Editor</span>
            <span className="font-mono text-[9px] text-j-border">Ctrl+Enter to run · Tab for indent</span>
            <button
              onClick={runQuery}
              disabled={mutation.isPending}
              className="px-3 py-1 rounded font-mono text-[10px] font-medium bg-j-accent text-j-bg hover:opacity-90 disabled:opacity-40 transition-opacity flex items-center gap-1.5"
            >
              {mutation.isPending ? (
                <>
                  <span className="inline-block w-2.5 h-2.5 border border-j-bg/40 border-t-transparent rounded-full animate-spin" />
                  Running…
                </>
              ) : '▶ Run'}
            </button>
          </div>
          <div className="flex">
            <div
              ref={gutterRef}
              aria-hidden="true"
              className="select-none text-right font-mono text-[12px] leading-relaxed text-j-border/50 border-r border-j-border/30 overflow-hidden shrink-0 px-3 py-3 h-36 bg-transparent"
            >
              {sql.split('\n').map((_, i) => (
                <div key={i}>{i + 1}</div>
              ))}
            </div>
            <textarea
              ref={textareaRef}
              value={sql}
              onChange={e => setSql(e.target.value)}
              onKeyDown={handleKeyDown}
              onScroll={(e) => { if (gutterRef.current) gutterRef.current.scrollTop = e.currentTarget.scrollTop }}
              spellCheck={false}
              className="flex-1 h-36 pl-4 pr-4 py-3 font-mono text-[12px] text-j-text bg-transparent resize-none outline-none placeholder-j-border"
              placeholder="SELECT * FROM silver.orders_cleaned LIMIT 20"
            />
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 flex flex-col overflow-hidden p-4 gap-3 min-h-0">
          {error && (
            <div className="shrink-0 px-4 py-3 rounded border border-j-red/40 bg-j-red/10 font-mono text-[11px] text-j-red">
              {error}
            </div>
          )}
          {result && <ResultTable result={result} />}
          {!result && !error && !mutation.isPending && (
            <div className="flex-1 flex items-center justify-center">
              <p className="font-mono text-[11px] text-j-border">Run a query to see results</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
