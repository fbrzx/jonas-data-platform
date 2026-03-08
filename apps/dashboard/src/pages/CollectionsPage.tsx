import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, getToken, getActiveTenantId, type Collection, type Entity, type Integration, type Transform, type ImportResult } from '../lib/api'
import { usePermissions } from '../lib/permissions'

// ── Inline items section ──────────────────────────────────────────────────────

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
  title, color, glyph, children, empty,
}: {
  title: string; color: string; glyph: string; children: React.ReactNode; empty: boolean
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

// ── Export helper ─────────────────────────────────────────────────────────────

async function triggerExport(name: string) {
  const tid = getActiveTenantId()
  const resp = await fetch(api.collections.exportUrl(name), {
    headers: {
      Authorization: `Bearer ${getToken()}`,
      ...(tid ? { 'X-Tenant-ID': tid } : {}),
    },
  })
  if (!resp.ok) throw new Error(`Export failed: ${resp.statusText}`)
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `collection-${name}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// ── Import result summary ─────────────────────────────────────────────────────

function ImportSummary({ result, onClose }: { result: ImportResult; onClose: () => void }) {
  const sections = [
    { label: 'Entities',   created: result.entities.created,   updated: result.entities.updated,   skipped: result.entities.skipped },
    { label: 'Transforms', created: result.transforms.created, updated: result.transforms.updated, skipped: result.transforms.skipped },
    { label: 'Connectors', created: result.connectors.created, updated: [] as string[],            skipped: result.connectors.skipped },
  ]
  return (
    <div className="mb-4 rounded border border-j-border bg-j-surface p-4 space-y-3 font-mono text-[11px]">
      <div className="flex items-center justify-between">
        <span className="text-j-bright font-semibold">Import complete — {result.collection}</span>
        <button onClick={onClose} className="text-j-dim hover:text-j-text transition-colors">✕</button>
      </div>
      {sections.map(({ label, created, updated, skipped }) =>
        (created.length + updated.length + skipped.length) > 0 ? (
          <div key={label}>
            <span className="text-j-dim uppercase tracking-widest text-[10px]">{label}</span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {created.map(n => <span key={n} className="px-1.5 py-0.5 rounded bg-j-green/10 border border-j-green/30 text-j-green">+ {n}</span>)}
              {updated.map(n => <span key={n} className="px-1.5 py-0.5 rounded bg-j-accent/10 border border-j-accent/30 text-j-accent">~ {n}</span>)}
              {skipped.map(n => <span key={n} className="px-1.5 py-0.5 rounded bg-j-surface2 border border-j-border text-j-dim">· {n}</span>)}
            </div>
          </div>
        ) : null
      )}
      {result.errors.length > 0 && (
        <div>
          <span className="text-j-red uppercase tracking-widest text-[10px]">Errors</span>
          <ul className="mt-1 space-y-0.5">
            {result.errors.map((e, i) => <li key={i} className="text-j-red">{e}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Collection expandable card ────────────────────────────────────────────────

function CollectionCard({
  col, entities, transforms, connectors, canAdmin,
}: {
  col: Collection
  entities: Entity[]
  transforms: Transform[]
  connectors: Integration[]
  canAdmin: boolean
}) {
  const [open, setOpen] = useState(false)
  const [exporting, setExporting] = useState(false)

  const colEntities   = entities.filter((e) => e.collection === col.name)
  const colTransforms = transforms.filter((t) => t.collection === col.name)
  const colConnectors = connectors.filter((c) => c.collection === col.name)

  async function handleExport(e: React.MouseEvent) {
    e.stopPropagation()
    setExporting(true)
    try { await triggerExport(col.name) } finally { setExporting(false) }
  }

  return (
    <div className="border border-j-border rounded bg-j-surface transition-colors hover:border-j-border-b">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-3 flex items-center justify-between gap-3 text-left"
      >
        <span className="font-mono text-sm font-semibold text-j-bright truncate">{col.name}</span>
        <div className="flex items-center gap-3 shrink-0">
          {col.entity_count > 0    && <span className="font-mono text-[10px] text-j-amber">{col.entity_count} entities</span>}
          {col.transform_count > 0 && <span className="font-mono text-[10px] text-j-accent">{col.transform_count} transforms</span>}
          {col.connector_count > 0 && <span className="font-mono text-[10px] text-j-green">{col.connector_count} connectors</span>}
          {canAdmin && (
            <button
              onClick={handleExport}
              disabled={exporting}
              title="Export collection as JSON"
              className="font-mono text-[10px] text-j-dim hover:text-j-accent border border-transparent hover:border-j-border rounded px-1.5 py-0.5 transition-colors disabled:opacity-40"
            >
              {exporting ? '…' : '↓ export'}
            </button>
          )}
          <span className="font-mono text-[10px] text-j-dim">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-j-border px-4 py-3 space-y-4">
          <ItemGroup title="Entities" color="text-j-amber" glyph="◈" empty={colEntities.length === 0}>
            {colEntities.map((e) => (
              <div key={e.id} className="px-3 py-2">
                <ItemRow label={e.name} sub={e.layer} to={`/catalogue?collection=${encodeURIComponent(col.name)}`} />
                {e.description && <p className="font-mono text-[10px] text-j-dim mt-0.5">{e.description}</p>}
              </div>
            ))}
          </ItemGroup>
          <ItemGroup title="Transforms" color="text-j-accent" glyph="⟳" empty={colTransforms.length === 0}>
            {colTransforms.map((t) => (
              <div key={t.id} className="px-3 py-2">
                <ItemRow label={t.name} sub={t.status} to={`/transforms?collection=${encodeURIComponent(col.name)}`} />
                {t.description && <p className="font-mono text-[10px] text-j-dim mt-0.5">{t.description}</p>}
              </div>
            ))}
          </ItemGroup>
          <ItemGroup title="Connectors" color="text-j-green" glyph="⬡" empty={colConnectors.length === 0}>
            {colConnectors.map((c) => (
              <div key={c.id} className="px-3 py-2">
                <ItemRow label={c.name} sub={c.connector_type} to={`/connectors?collection=${encodeURIComponent(col.name)}`} />
                {c.description && <p className="font-mono text-[10px] text-j-dim mt-0.5">{c.description}</p>}
              </div>
            ))}
          </ItemGroup>
        </div>
      )}
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

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
  const [search, setSearch]             = useState('')
  const [overwrite, setOverwrite]       = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const { canAdmin } = usePermissions()

  const { data: collections = [], isLoading } = useQuery({ queryKey: ['collections'], queryFn: api.collections.list, staleTime: 30_000 })
  const { data: entities   = [] } = useQuery({ queryKey: ['entities'],   queryFn: api.catalogue.list,  staleTime: 30_000 })
  const { data: transforms = [] } = useQuery({ queryKey: ['transforms'], queryFn: api.transforms.list, staleTime: 30_000 })
  const { data: connectors = [] } = useQuery({ queryKey: ['connectors'], queryFn: api.connectors.list, staleTime: 30_000 })

  const importMut = useMutation({
    mutationFn: ({ file, ow }: { file: File; ow: boolean }) =>
      api.collections.importCollection(file, ow),
    onSuccess: (result) => {
      setImportResult(result)
      qc.invalidateQueries({ queryKey: ['collections'] })
      qc.invalidateQueries({ queryKey: ['entities'] })
      qc.invalidateQueries({ queryKey: ['transforms'] })
      qc.invalidateQueries({ queryKey: ['connectors'] })
    },
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImportResult(null)
    importMut.mutate({ file, ow: overwrite })
    e.target.value = ''
  }

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

      {/* Toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {collections.length > 0 && (
          <input
            type="text"
            placeholder="Filter collections…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="font-mono text-sm bg-j-surface border border-j-border rounded px-3 py-1.5 text-j-text placeholder-j-dim focus:outline-none focus:border-j-accent w-full max-w-sm"
          />
        )}
        {canAdmin && (
          <div className="flex items-center gap-2 ml-auto shrink-0">
            <label className="flex items-center gap-1.5 font-mono text-[10px] text-j-dim cursor-pointer select-none">
              <input
                type="checkbox"
                checked={overwrite}
                onChange={(e) => setOverwrite(e.target.checked)}
                className="accent-j-accent"
              />
              overwrite existing
            </label>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importMut.isPending}
              className="px-3 py-1.5 font-mono text-[10px] tracking-wider uppercase border border-j-border rounded text-j-dim hover:border-j-accent hover:text-j-accent transition-colors disabled:opacity-40"
            >
              {importMut.isPending ? 'importing…' : '↑ import'}
            </button>
            <input ref={fileInputRef} type="file" accept=".json,application/json" className="hidden" onChange={handleFileChange} />
          </div>
        )}
      </div>

      {importMut.isError && (
        <p className="mb-4 font-mono text-[11px] text-j-red">
          {importMut.error instanceof Error ? importMut.error.message : 'Import failed'}
        </p>
      )}

      {importResult && <ImportSummary result={importResult} onClose={() => setImportResult(null)} />}

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
              canAdmin={canAdmin}
            />
          ))}
        </div>
      )}
    </div>
  )
}
