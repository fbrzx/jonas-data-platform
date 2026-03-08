import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Collection, type Entity, type Integration, type Transform } from '../lib/api'

// ── Inline items section ────────────────────────────────────────────────────────

function ItemRow({ label, sub, to }: { label: string; sub?: string; to: string }) {
  return (
    <Link
      to={to}
      className="flex items-baseline gap-2 py-0.5 group hover:text-j-accent transition-colors"
    >
      <span className="font-mono text-[11px] text-j-bright group-hover:text-j-accent">{label}</span>
      {sub && <span className="font-mono text-[10px] text-j-dim">{sub}</span>}
      <span className="font-mono text-[10px] text-j-dim opacity-0 group-hover:opacity-100 transition-opacity ml-auto">→</span>
    </Link>
  )
}

function ItemGroup({
  title,
  color,
  glyph,
  children,
  empty,
}: {
  title: string
  color: string
  glyph: string
  children: React.ReactNode
  empty: boolean
}) {
  if (empty) return null
  return (
    <div>
      <p className={`font-mono text-[10px] tracking-[0.12em] uppercase mb-1.5 ${color}`}>
        {glyph} {title}
      </p>
      <div className="border border-j-border rounded divide-y divide-j-border bg-j-bg">
        {children}
      </div>
    </div>
  )
}

// ── Collection expandable card ──────────────────────────────────────────────────

function CollectionCard({
  col,
  entities,
  transforms,
  connectors,
}: {
  col: Collection
  entities: Entity[]
  transforms: Transform[]
  connectors: Integration[]
}) {
  const [open, setOpen] = useState(false)

  const colEntities = entities.filter((e) => e.collection === col.name)
  const colTransforms = transforms.filter((t) => t.collection === col.name)
  const colConnectors = connectors.filter((c) => c.collection === col.name)

  return (
    <div className="border border-j-border rounded bg-j-surface transition-colors hover:border-j-border-b">
      {/* Card header — click to expand */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-3 flex items-center justify-between gap-3 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-sm font-semibold text-j-bright truncate">{col.name}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {col.entity_count > 0 && (
            <span className="font-mono text-[10px] text-j-amber">{col.entity_count} entities</span>
          )}
          {col.transform_count > 0 && (
            <span className="font-mono text-[10px] text-j-accent">{col.transform_count} transforms</span>
          )}
          {col.connector_count > 0 && (
            <span className="font-mono text-[10px] text-j-green">{col.connector_count} connectors</span>
          )}
          <span className="font-mono text-[10px] text-j-dim">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Expanded items */}
      {open && (
        <div className="border-t border-j-border px-4 py-3 space-y-4">
          <ItemGroup
            title="Entities"
            color="text-j-amber"
            glyph="◈"
            empty={colEntities.length === 0}
          >
            {colEntities.map((e) => (
              <div key={e.id} className="px-3 py-2">
                <ItemRow
                  label={e.name}
                  sub={e.layer}
                  to={`/catalogue?collection=${encodeURIComponent(col.name)}`}
                />
                {e.description && (
                  <p className="font-mono text-[10px] text-j-dim mt-0.5">{e.description}</p>
                )}
              </div>
            ))}
          </ItemGroup>

          <ItemGroup
            title="Transforms"
            color="text-j-accent"
            glyph="⟳"
            empty={colTransforms.length === 0}
          >
            {colTransforms.map((t) => (
              <div key={t.id} className="px-3 py-2">
                <ItemRow
                  label={t.name}
                  sub={t.status}
                  to={`/transforms?collection=${encodeURIComponent(col.name)}`}
                />
                {t.description && (
                  <p className="font-mono text-[10px] text-j-dim mt-0.5">{t.description}</p>
                )}
              </div>
            ))}
          </ItemGroup>

          <ItemGroup
            title="Connectors"
            color="text-j-green"
            glyph="⬡"
            empty={colConnectors.length === 0}
          >
            {colConnectors.map((c) => (
              <div key={c.id} className="px-3 py-2">
                <ItemRow
                  label={c.name}
                  sub={c.connector_type}
                  to={`/connectors?collection=${encodeURIComponent(col.name)}`}
                />
                {c.description && (
                  <p className="font-mono text-[10px] text-j-dim mt-0.5">{c.description}</p>
                )}
              </div>
            ))}
          </ItemGroup>
        </div>
      )}
    </div>
  )
}

// ── Empty state ────────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
      <span className="text-3xl text-j-dim">◻</span>
      <p className="font-mono text-sm text-j-dim">No collections yet</p>
      <p className="font-mono text-[11px] text-j-dim max-w-xs">
        Tag entities, transforms, or connectors with a collection name to group them here.
      </p>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CollectionsPage() {
  const [search, setSearch] = useState('')

  const { data: collections = [], isLoading } = useQuery({
    queryKey: ['collections'],
    queryFn: api.collections.list,
    staleTime: 30_000,
  })

  const { data: entities = [] } = useQuery({
    queryKey: ['entities'],
    queryFn: api.catalogue.list,
    staleTime: 30_000,
  })

  const { data: transforms = [] } = useQuery({
    queryKey: ['transforms'],
    queryFn: api.transforms.list,
    staleTime: 30_000,
  })

  const { data: connectors = [] } = useQuery({
    queryKey: ['connectors'],
    queryFn: api.connectors.list,
    staleTime: 30_000,
  })

  const filtered = search.trim()
    ? collections.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()))
    : collections

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      {/* Header */}
      <div className="mb-6 pb-4 border-b border-j-border">
        <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">Workspace</div>
        <div className="flex items-baseline gap-3">
          <h2 className="text-j-bright font-semibold">Collections</h2>
          <span className="font-mono text-[10px] text-j-dim">{collections.length} total</span>
        </div>
        <p className="font-mono text-[11px] text-j-dim mt-1">
          Group entities, transforms, and connectors into logical collections.
        </p>
      </div>

      {/* Search */}
      {collections.length > 0 && (
        <div className="mb-4">
          <input
            type="text"
            placeholder="Filter collections…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="font-mono text-sm bg-j-surface border border-j-border rounded px-3 py-1.5 text-j-text placeholder-j-dim focus:outline-none focus:border-j-accent w-full max-w-sm"
          />
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <p className="font-mono text-[11px] text-j-dim italic">Loading…</p>
      ) : filtered.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-2">
          {filtered.map((col) => (
            <CollectionCard
              key={col.name}
              col={col}
              entities={entities}
              transforms={transforms}
              connectors={connectors}
            />
          ))}
        </div>
      )}
    </div>
  )
}
