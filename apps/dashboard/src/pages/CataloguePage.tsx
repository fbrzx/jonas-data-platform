import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Entity, type EntityField, type PreviewResult, type EntityCreate, type EntityUpdate, type FieldUpdate } from '../lib/api'
import { usePermissions } from '../lib/permissions'
import { useToast } from '../lib/toast'
import PageHeader from '../components/PageHeader'
import DataChart from '../components/DataChart'

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

// ── Edit Entity Modal ─────────────────────────────────────────────────────────

function EditEntityModal({ entity, onClose }: { entity: Entity; onClose: () => void }) {
  const { canAdmin } = usePermissions()
  const qc = useQueryClient()
  let initialTags: string[] = []
  try { initialTags = JSON.parse(entity.tags || '[]') } catch { /* */ }

  const [form, setForm] = useState<EntityUpdate>({
    name: entity.name,
    description: entity.description ?? '',
    tags: initialTags,
  })
  const [tagsInput, setTagsInput] = useState(initialTags.join(', '))
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: EntityUpdate) => api.catalogue.update(entity.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entities'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const tags = tagsInput.split(',').map((t) => t.trim()).filter(Boolean)
    mutation.mutate({ ...form, tags })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">Edit Entity</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4">
          {/* Name — admin only */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">
              Name {canAdmin && <span className="text-j-red">*</span>}
            </label>
            {canAdmin ? (
              <>
                <input
                  type="text"
                  value={form.name ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
                <p className="font-mono text-[10px] text-j-red mt-1">
                  ⚠ Renaming changes the underlying DuckDB table reference — use with caution.
                </p>
              </>
            ) : (
              <p className="font-mono text-xs text-j-dim bg-j-surface2 border border-j-border rounded px-3 py-1.5">{entity.name}</p>
            )}
          </div>

          {/* Description */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Description</label>
            <input
              type="text"
              value={form.description ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="Describe this entity…"
            />
          </div>

          {/* Tags */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Tags</label>
            <input
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="comma-separated tags"
            />
          </div>

          {error && (
            <div className="font-mono text-[11px] text-j-red bg-j-red-dim border border-j-red rounded px-3 py-2">{error}</div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim border border-j-border px-3 py-1.5 rounded hover:border-j-border-b transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-3 py-1.5 rounded hover:bg-j-accent hover:text-j-bg transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Edit Field Modal ──────────────────────────────────────────────────────────

const DATA_TYPES = ['string', 'int', 'float', 'bool', 'timestamp', 'json', 'array']

function EditFieldModal({
  field,
  entityId,
  onClose,
}: {
  field: EntityField
  entityId: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<FieldUpdate>({
    data_type: field.data_type,
    nullable: field.nullable,
    is_pii: field.is_pii,
    description: field.description ?? '',
  })
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: FieldUpdate) => api.catalogue.updateField(entityId, field.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entity-fields', entityId] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    mutation.mutate(form)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">Edit Field</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4">
          {/* Name — read-only */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Name</label>
            <p className="font-mono text-xs text-j-dim bg-j-surface2 border border-j-border rounded px-3 py-1.5">{field.name}</p>
          </div>

          {/* Data type */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Type</label>
            <select
              value={form.data_type}
              onChange={(e) => setForm((f) => ({ ...f, data_type: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
            >
              {DATA_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {/* Description */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Description</label>
            <input
              type="text"
              value={form.description ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="Describe this field…"
            />
          </div>

          {/* Nullable */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.nullable ?? true}
              onChange={(e) => setForm((f) => ({ ...f, nullable: e.target.checked }))}
              className="accent-j-accent"
            />
            <span className="font-mono text-[11px] text-j-text">Nullable</span>
          </label>

          {/* PII */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_pii ?? false}
              onChange={(e) => setForm((f) => ({ ...f, is_pii: e.target.checked }))}
              className="accent-j-red"
            />
            <span className="font-mono text-[11px] text-j-text">PII field</span>
            <span className="font-mono text-[10px] text-j-red">(data will be masked for non-admins)</span>
          </label>

          {error && (
            <div className="font-mono text-[11px] text-j-red bg-j-red-dim border border-j-red rounded px-3 py-2">{error}</div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim border border-j-border px-3 py-1.5 rounded hover:border-j-border-b transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-3 py-1.5 rounded hover:bg-j-accent hover:text-j-bg transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Field table ───────────────────────────────────────────────────────────────

function FieldTable({
  fields,
  entityId,
  canWrite,
  canAdmin,
}: {
  fields: EntityField[]
  entityId: string
  canWrite: boolean
  canAdmin: boolean
}) {
  const qc = useQueryClient()
  const { confirm } = useToast()
  const [editField, setEditField] = useState<EntityField | null>(null)

  const deleteMut = useMutation({
    mutationFn: (fieldId: string) => api.catalogue.deleteField(entityId, fieldId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['entity-fields', entityId] }),
  })

  if (!fields.length)
    return <p className="font-mono text-[11px] text-j-dim italic px-4 py-3">no fields registered</p>

  return (
    <>
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-j-border">
            {['field', 'type', 'nullable', 'pii', 'samples', ...(canWrite ? [''] : [])].map((h, i) => (
              <th key={i} className="px-4 py-2 text-left font-mono text-[10px] tracking-[0.12em] uppercase text-j-dim font-medium">
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
                {canWrite && (
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1 justify-end">
                      <button
                        onClick={() => setEditField(f)}
                        className="font-mono text-[10px] text-j-dim hover:text-j-accent transition-colors px-1.5 py-0.5 rounded border border-transparent hover:border-j-border"
                        title="Edit field"
                      >
                        ✎
                      </button>
                      {canAdmin && (
                        <button
                          onClick={async () => {
                            const ok = await confirm(`Delete field "${f.name}"?`)
                            if (!ok) return
                            deleteMut.mutate(f.id)
                          }}
                          disabled={deleteMut.isPending}
                          className="font-mono text-[10px] text-j-red/50 hover:text-j-red transition-colors px-1.5 py-0.5 rounded border border-transparent hover:border-j-red/30 disabled:opacity-30"
                          title="Delete field"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
      {editField && (
        <EditFieldModal field={editField} entityId={entityId} onClose={() => setEditField(null)} />
      )}
    </>
  )
}

// ── Data preview grid ─────────────────────────────────────────────────────────

function DataGrid({ result }: { result: PreviewResult }) {
  if (result.error) {
    return (
      <p className="font-mono text-[11px] text-j-red px-4 py-3">
        {result.error.includes('does not exist') || result.error.includes('not found')
          ? 'table not populated yet — run a transform to load data'
          : result.error}
      </p>
    )
  }
  if (!result.rows.length) {
    return <p className="font-mono text-[11px] text-j-dim italic px-4 py-3">no rows yet</p>
  }
  return (
    <div className="overflow-x-auto">
      {result.pii_masked && (
        <div className="flex items-center gap-2 px-4 py-2 bg-j-red-dim border-b border-j-red">
          <span className="font-mono text-[10px] text-j-red font-semibold tracking-wider">
            PII MASKED · {result.pii_fields.join(', ')}
          </span>
        </div>
      )}
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-j-border">
            {result.columns.map((col) => (
              <th key={col} className={`px-4 py-2 text-left font-mono text-[10px] tracking-[0.1em] uppercase whitespace-nowrap ${result.pii_fields.includes(col) ? 'text-j-red' : 'text-j-dim'}`}>
                {col}{result.pii_fields.includes(col) ? ' ⚠' : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className="border-b border-j-border hover:bg-j-surface2 transition-colors">
              {result.columns.map((col) => {
                const v = row[col]
                const raw = v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)
                const isPii = result.pii_fields.includes(col)
                return (
                  <td key={col} className={`px-4 py-2 font-mono max-w-[200px] truncate ${isPii ? 'text-j-red opacity-70' : 'text-j-text'}`} title={raw}>
                    {raw}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-4 py-2 font-mono text-[10px] text-j-dim border-t border-j-border">
        showing {result.count} row{result.count !== 1 ? 's' : ''}
      </p>
    </div>
  )
}

// ── Entity row ────────────────────────────────────────────────────────────────

function EntityRow({ entity }: { entity: Entity }) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'fields' | 'data'>('fields')
  const [dataView, setDataView] = useState<'table' | 'chart'>('table')
  const [editOpen, setEditOpen] = useState(false)
  const { canWrite, canAdmin } = usePermissions()
  const qc = useQueryClient()
  const { confirm } = useToast()

  const deleteMut = useMutation({
    mutationFn: () => api.catalogue.delete(entity.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['entities'] }),
  })

  async function handleDelete() {
    // Check if entity has data by doing a quick preview
    let warning = `Delete entity "${entity.name}"? This removes the catalogue entry.`
    try {
      const preview = await api.catalogue.preview(entity.id)
      if (preview && preview.count > 0) {
        warning = `⚠ Entity "${entity.name}" contains ${preview.count}+ rows of data.\n\nDelete anyway? The underlying table will NOT be dropped, but the catalogue entry and field definitions will be removed.`
      }
    } catch { /* table may not exist — safe to delete */ }
    const ok = await confirm(warning)
    if (!ok) return
    deleteMut.mutate()
  }

  const { data: fields, isLoading: fieldsLoading } = useQuery({
    queryKey: ['entity-fields', entity.id],
    queryFn: () => api.catalogue.getFields(entity.id),
    enabled: open && tab === 'fields',
    staleTime: 60_000,
  })
  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ['entity-preview', entity.id],
    queryFn: () => api.catalogue.preview(entity.id),
    enabled: open && tab === 'data',
    staleTime: 30_000,
  })

  let tags: string[] = []
  try { tags = JSON.parse(entity.tags || '[]') } catch { /* */ }

  return (
    <>
      <div className="border border-j-border rounded bg-j-surface overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3">
          <button
            onClick={() => setOpen(!open)}
            className="flex-1 flex items-center gap-3 text-left"
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
          </button>
          <div className="flex items-center gap-2 shrink-0">
            <span className="font-mono text-[10px] text-j-dim">
              {new Date(entity.created_at).toLocaleDateString()}
            </span>
            {canWrite && (
              <button
                onClick={() => setEditOpen(true)}
                className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-2 py-1 rounded transition-colors"
                title="Edit entity"
              >
                Edit
              </button>
            )}
            {canAdmin && (
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-red/60 border border-j-border hover:border-j-red hover:text-j-red px-2 py-1 rounded transition-colors disabled:opacity-30"
                title="Delete entity"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {open && (
          <div className="border-t border-j-border fade-up">
            {/* Tabs */}
            <div className="flex border-b border-j-border px-4 pt-1">
              {(['fields', 'data'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`mr-4 pb-2 font-mono text-[10px] tracking-[0.12em] uppercase border-b-2 transition-colors ${
                    tab === t
                      ? 'border-j-accent text-j-accent'
                      : 'border-transparent text-j-dim hover:text-j-text'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            {tab === 'fields' && (
              fieldsLoading
                ? <p className="font-mono text-[11px] text-j-dim px-4 py-3">loading…</p>
                : <FieldTable
                    fields={fields ?? []}
                    entityId={entity.id}
                    canWrite={canWrite}
                    canAdmin={canAdmin}
                  />
            )}
            {tab === 'data' && (
              previewLoading
                ? <p className="font-mono text-[11px] text-j-dim px-4 py-3">loading preview…</p>
                : preview && !preview.error && preview.rows.length > 0
                  ? (
                    <>
                      {/* table / chart toggle */}
                      <div className="flex items-center gap-1 px-4 py-2 border-b border-j-border">
                        {(['table', 'chart'] as const).map((v) => (
                          <button
                            key={v}
                            onClick={() => setDataView(v)}
                            className={`px-2 py-0.5 font-mono text-[10px] rounded border transition-colors ${
                              dataView === v
                                ? 'border-j-accent text-j-accent bg-j-accent-dim'
                                : 'border-j-border text-j-dim hover:text-j-text'
                            }`}
                          >
                            {v === 'table' ? '⊞ table' : '▲ chart'}
                          </button>
                        ))}
                        <span className="ml-auto font-mono text-[10px] text-j-dim">
                          {preview.count} row{preview.count !== 1 ? 's' : ''}
                        </span>
                      </div>
                      {dataView === 'table'
                        ? <DataGrid result={preview} />
                        : <div className="px-4 py-3">
                            <DataChart columns={preview.columns} rows={preview.rows} />
                          </div>
                      }
                    </>
                  )
                  : <DataGrid result={preview ?? { columns: [], rows: [], count: 0, pii_masked: false, pii_fields: [] }} />
            )}
          </div>
        )}
      </div>

      {editOpen && <EditEntityModal entity={entity} onClose={() => setEditOpen(false)} />}
    </>
  )
}

// ── Create Entity Modal ───────────────────────────────────────────────────────

function CreateEntityModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<EntityCreate>({ name: '', layer: 'bronze' })
  const [tagsInput, setTagsInput] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: EntityCreate) => api.catalogue.create(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entities'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    setError(null)
    const tags = tagsInput.split(',').map((t) => t.trim()).filter(Boolean)
    mutation.mutate({ ...form, tags })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">New Entity</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4">
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Name <span className="text-j-red">*</span></label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="e.g. orders"
            />
          </div>
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Layer</label>
            <select
              value={form.layer}
              onChange={(e) => setForm((f) => ({ ...f, layer: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
            >
              {['bronze', 'silver', 'gold'].map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Description</label>
            <input
              type="text"
              value={form.description ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="Describe this entity…"
            />
          </div>
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Tags</label>
            <input
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="comma-separated tags"
            />
          </div>
          {error && (
            <div className="font-mono text-[11px] text-j-red bg-j-red-dim border border-j-red rounded px-3 py-2">{error}</div>
          )}
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim border border-j-border px-3 py-1.5 rounded hover:border-j-border-b transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-3 py-1.5 rounded hover:bg-j-accent hover:text-j-bg transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CataloguePage() {
  const { canWrite } = usePermissions()
  const [search, setSearch] = useState('')
  const [layerFilter, setLayerFilter] = useState<'all' | 'bronze' | 'silver' | 'gold'>('all')
  const [showCreate, setShowCreate] = useState(false)
  const { data: entities, isLoading, error, refetch } = useQuery({
    queryKey: ['entities'],
    queryFn: api.catalogue.list,
    staleTime: 30_000,
  })

  const filtered = (entities ?? []).filter(
    (e) => (layerFilter === 'all' || e.layer === layerFilter) &&
           (!search || e.name.toLowerCase().includes(search.toLowerCase())),
  )

  const layers = ['bronze', 'silver', 'gold'] as const
  const grouped = Object.fromEntries(layers.map((l) => [l, filtered.filter((e) => e.layer === l)]))

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      <PageHeader label="Catalogue" title="Data Catalogue">
        <input
          type="text"
          placeholder="filter entities…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="font-mono text-[11px] bg-j-surface border border-j-border rounded px-2.5 py-1.5 text-j-bright placeholder-j-dim focus:outline-none focus:border-j-accent w-40"
        />
        <div className="flex items-center gap-1">
          {(['all', 'bronze', 'silver', 'gold'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setLayerFilter(s)}
              className={`font-mono text-[10px] tracking-[0.08em] uppercase px-2.5 py-1.5 rounded border transition-colors
                ${layerFilter === s
                  ? 'border-j-accent text-j-accent bg-j-surface2'
                  : 'border-j-border text-j-dim hover:border-j-accent hover:text-j-accent'
                }`}
            >
              {s}
            </button>
          ))}
        </div>
        <button onClick={() => refetch()} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors">
          Refresh
        </button>
        {canWrite && (
          <button
            onClick={() => setShowCreate(true)}
            className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-3 py-1.5 rounded hover:bg-j-accent hover:text-j-bg transition-colors"
          >
            + New
          </button>
        )}
      </PageHeader>

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading catalogue…</p>}
      {error && <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">{error instanceof Error ? error.message : 'error'}</div>}
      {!isLoading && !error && filtered.length === 0 && (
        <p className="font-mono text-[11px] text-j-dim text-center py-16">
          {layerFilter !== 'all' ? `no ${layerFilter} entities` : 'no entities in catalogue yet — run make seed'}
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

      {showCreate && <CreateEntityModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}
