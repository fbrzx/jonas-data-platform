import { useQuery } from '@tanstack/react-query'
import { api, type Integration } from '../lib/api'

const STATUS: Record<string, { dot: string; text: string; bg: string; border: string }> = {
  active:   { dot: 'bg-j-green',  text: 'text-j-green',  bg: 'bg-j-green-dim',  border: 'border-j-green'  },
  inactive: { dot: 'bg-j-dim',    text: 'text-j-dim',    bg: 'bg-j-surface2',   border: 'border-j-border' },
  error:    { dot: 'bg-j-red',    text: 'text-j-red',    bg: 'bg-j-red-dim',    border: 'border-j-red'    },
}

const TYPE_GLYPH: Record<string, string> = {
  webhook:    '⬡',
  batch_csv:  '⊞',
  batch_json: '⊟',
  scheduled:  '◷',
}

const TYPE_COLOR: Record<string, string> = {
  webhook:    'text-j-purple',
  batch_csv:  'text-j-accent',
  batch_json: 'text-j-amber',
  scheduled:  'text-j-green',
}

function IntegrationCard({ integration }: { integration: Integration }) {
  const s = STATUS[integration.status] ?? STATUS.inactive
  const glyph = TYPE_GLYPH[integration.source_type] ?? '◉'
  const glyphColor = TYPE_COLOR[integration.source_type] ?? 'text-j-dim'

  let configKeys: string[] = []
  try { configKeys = Object.keys(JSON.parse(integration.config || '{}')) } catch { /* */ }

  return (
    <div className="border border-j-border rounded bg-j-surface overflow-hidden hover:border-j-border-b transition-colors">
      {/* Card header */}
      <div className="px-4 pt-4 pb-3 border-b border-j-border flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className={`font-mono text-2xl leading-none mt-0.5 ${glyphColor}`}>{glyph}</span>
          <div>
            <div className="font-mono text-j-bright font-medium">{integration.name}</div>
            {integration.description && (
              <p className="font-mono text-[11px] text-j-dim mt-0.5">{integration.description}</p>
            )}
          </div>
        </div>
        <span className={`shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] font-medium border ${s.bg} ${s.text} ${s.border}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
          {integration.status}
        </span>
      </div>

      {/* Card meta */}
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim">{integration.source_type}</span>
          {configKeys.length > 0 && (
            <span className="font-mono text-[10px] text-j-dim opacity-60">
              {configKeys.join(' · ')}
            </span>
          )}
        </div>
        <div className="text-right font-mono text-[10px] text-j-dim">
          {integration.last_run_at
            ? <>last run {new Date(integration.last_run_at).toLocaleDateString()}</>
            : <>created {new Date(integration.created_at).toLocaleDateString()}</>
          }
        </div>
      </div>
    </div>
  )
}

export default function IntegrationsPage() {
  const { data: integrations, isLoading, error, refetch } = useQuery({
    queryKey: ['integrations'],
    queryFn: api.integrations.list,
    staleTime: 30_000,
  })

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      <div className="flex items-center justify-between mb-5 pb-4 border-b border-j-border">
        <div>
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">Integrations</div>
          <h2 className="text-j-bright font-semibold">Data Sources</h2>
        </div>
        <button onClick={() => refetch()} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors">
          Refresh
        </button>
      </div>

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading integrations…</p>}
      {error && <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">{error instanceof Error ? error.message : 'error'}</div>}

      {!isLoading && !error && !(integrations ?? []).length && (
        <div className="text-center py-16">
          <p className="font-mono text-[11px] text-j-dim mb-2">no integrations yet — run <code className="bg-j-surface2 px-1.5 py-0.5 rounded text-j-accent border border-j-border">make seed</code></p>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {(integrations ?? []).map((i) => <IntegrationCard key={i.id} integration={i} />)}
      </div>
    </div>
  )
}
