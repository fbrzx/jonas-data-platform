import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Entity, type EntityField } from '../lib/api'

// ── Layer config ──────────────────────────────────────────────────────────────

const LAYER: Record<string, { label: string; dot: string; text: string; border: string; bg: string }> = {
  bronze: { label: 'Bronze', dot: 'bg-j-amber',  text: 'text-j-amber',  border: 'border-j-amber',  bg: 'bg-j-amber-dim'  },
  silver: { label: 'Silver', dot: 'bg-j-accent',  text: 'text-j-accent',  border: 'border-j-accent',  bg: 'bg-j-accent-dim' },
  gold:   { label: 'Gold',   dot: 'bg-j-bright',  text: 'text-j-bright',  border: 'border-j-bright',  bg: 'bg-j-surface2'   },
}

function LayerBadge({ layer }: { layer: string }) {
  const cfg = LAYER[layer] ?? LAYER.bronze
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] font-medium border ${cfg.bg} ${cfg.text} ${cfg.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

// ── Field table ───────────────────────────────────────────────────────────────

function FieldTable({ fields }: { fields: EntityField[] }) {
  if (!fields.length)
    return <p className="font-mono text-[11px] text-j-dim italic px-4 py-3">no fields registered</p>

  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-j-border">
          {['field', 'type', 'nullable', 'pii', 'samples'].map((h) => (
            <th key={h} className="px-4 py-2 text-left font-mono text-[10px] tracking-[0.12em] uppercase text-j-dim font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {[...fields].sort((a, b) => a.ordinal - b.ordinal).map((f) => {
          let samples: string[] = []
          try { samples = JSON.parse(f.sample_values || '[]') } catch { /* */ }
          return (
            <tr key={f.id} className="border-b border-j-border hover:bg-j-surface2 transition-colors">
              <td className="px-4 py-2 font-mono text-j-bright font-medium">{f.name}</td>
              <td className="px-4 py-2 font-mono text-j-accent">{f.data_type}</td>
              <td className="px-4 py-2 font-mono text-j-dim">{f.nullable ? 'yes' : 'no'}</td>
              <td className="px-4 py-2">
                {f.is_pii
                  ? <span className="px-1.5 py-0.5 font-mono text-[10px] bg-j-red-dim text-j-red border border-j-red rounded font-semibold">PII</span>
                  : <span className="text-j-border">—</span>
                }
              </td>
              <td className="px-4 py-2 font-mono text-j-dim">
                {samples.length > 0 ? samples.slice(0, 3).join(', ') : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Entity row ────────────────────────────────────────────────────────────────

function EntityRow({ entity }: { entity: Entity }) {
  const [open, setOpen] = useState(false)
  const { data: fields, isLoading } = useQuery({
    queryKey: ['entity-fields', entity.id],
    queryFn: () => api.catalogue.getFields(entity.id),
    enabled: open,
    staleTime: 60_000,
  })

  let tags: string[] = []
  try { tags = JSON.parse(entity.tags || '[]') } catch { /* */ }

  return (
    <div className="border border-j-border rounded bg-j-surface overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-j-surface2 transition-colors"
      >
        <span className={`font-mono text-j-dim text-xs transition-transform duration-150 ${open ? 'rotate-90' : ''}`}>▶</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-j-bright font-medium">{entity.name}</span>
            <LayerBadge layer={entity.layer} />
            {tags.map((tag) => (
              <span key={tag} className="px-1.5 py-0.5 font-mono text-[10px] bg-j-surface2 text-j-dim border border-j-border rounded">
                {tag}
              </span>
            ))}
          </div>
          {entity.description && (
            <p className="font-mono text-[11px] text-j-dim mt-0.5 truncate">{entity.description}</p>
          )}
        </div>
        <span className="font-mono text-[10px] text-j-dim shrink-0">
          {new Date(entity.created_at).toLocaleDateString()}
        </span>
      </button>

      {open && (
        <div className="border-t border-j-border fade-up">
          {isLoading
            ? <p className="font-mono text-[11px] text-j-dim px-4 py-3">loading fields…</p>
            : <FieldTable fields={fields ?? []} />
          }
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CataloguePage() {
  const [search, setSearch] = useState('')
  const { data: entities, isLoading, error, refetch } = useQuery({
    queryKey: ['entities'],
    queryFn: api.catalogue.list,
    staleTime: 30_000,
  })

  const filtered = (entities ?? []).filter(
    (e) => !search || e.name.toLowerCase().includes(search.toLowerCase()) || (e.description ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  const layers = ['bronze', 'silver', 'gold'] as const
  const grouped = Object.fromEntries(layers.map((l) => [l, filtered.filter((e) => e.layer === l)]))

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      {/* Page header */}
      <div className="flex items-center justify-between mb-5 pb-4 border-b border-j-border">
        <div>
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">Catalogue</div>
          <h2 className="text-j-bright font-semibold">Data Catalogue</h2>
        </div>
        <button onClick={() => refetch()} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors">
          Refresh
        </button>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="search entities…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full mb-6 px-3 py-2.5 font-mono text-sm bg-j-surface border border-j-border text-j-text rounded placeholder-j-dim focus:outline-none focus:border-j-accent transition-colors"
      />

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading catalogue…</p>}
      {error && <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">{error instanceof Error ? error.message : 'error'}</div>}
      {!isLoading && !error && filtered.length === 0 && (
        <p className="font-mono text-[11px] text-j-dim text-center py-16">
          {search ? 'no entities match' : 'no entities in catalogue yet — run make seed'}
        </p>
      )}

      {layers.map((layer) => {
        const items = grouped[layer] ?? []
        if (!items.length) return null
        const cfg = LAYER[layer]
        return (
          <div key={layer} className="mb-8">
            <div className={`flex items-center gap-2 mb-3 pb-2 border-b border-j-border`}>
              <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
              <span className={`font-mono text-[10px] font-semibold tracking-[0.18em] uppercase ${cfg.text}`}>
                {cfg.label} layer
              </span>
              <span className="font-mono text-[10px] text-j-dim">· {items.length}</span>
            </div>
            <div className="space-y-2">
              {items.map((e) => <EntityRow key={e.id} entity={e} />)}
            </div>
          </div>
        )
      })}
    </div>
  )
}
