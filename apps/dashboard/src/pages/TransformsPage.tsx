import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, type Transform, type ExecuteResult, type TransformCreate, type TransformUpdate } from '../lib/api'
import { usePermissions } from '../lib/permissions'
import { useToast } from '../lib/toast'
import PageHeader from '../components/PageHeader'
import CollectionTag from '../components/CollectionTag'

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  draft:    { bg: 'bg-j-surface2',  text: 'text-j-dim',   border: 'border-j-border',   dot: 'bg-j-dim'   },
  approved: { bg: 'bg-j-green-dim', text: 'text-j-green', border: 'border-j-green',    dot: 'bg-j-green' },
  rejected: { bg: 'bg-j-red-dim',   text: 'text-j-red',   border: 'border-j-red',      dot: 'bg-j-red'   },
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.draft
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] font-medium border ${s.bg} ${s.text} ${s.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  )
}

// ── Layer pill ─────────────────────────────────────────────────────────────────

const LAYER_TEXT: Record<string, string> = {
  bronze: 'text-j-amber', silver: 'text-j-accent', gold: 'text-j-bright',
}
function LayerArrow({ from, to }: { from: string; to: string }) {
  return (
    <span className="font-mono text-[11px] text-j-dim">
      <span className={LAYER_TEXT[from] ?? 'text-j-dim'}>{from}</span>
      <span className="text-j-dim mx-1">→</span>
      <span className={LAYER_TEXT[to] ?? 'text-j-dim'}>{to}</span>
    </span>
  )
}

// ── Execute result ────────────────────────────────────────────────────────────

function ExecResult({ result }: { result: ExecuteResult }) {
  const ok = result.errors.length === 0
  return (
    <div className={`mt-3 px-3 py-2.5 rounded border font-mono text-xs ${ok ? 'bg-j-green-dim border-j-green text-j-green' : 'bg-j-red-dim border-j-red text-j-red'}`}>
      {ok
        ? <>executed · {result.duration_ms.toFixed(0)}ms · {result.rows_affected} rows · <span className="text-j-text">{result.target_table}</span></>
        : <>{result.errors.map((e, i) => <div key={i}>{e}</div>)}</>
      }
    </div>
  )
}

// ── Transform Form Modal ──────────────────────────────────────────────────────

const LAYERS = ['bronze', 'silver', 'gold']

function TransformFormModal({
  transform,
  onClose,
}: {
  transform?: Transform
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { canAdmin } = usePermissions()
  const isEdit = !!transform
  const isDraft = !transform || transform.status === 'draft'
  const canEditSql = canAdmin || isDraft

  const [form, setForm] = useState({
    name: transform?.name ?? '',
    description: transform?.description ?? '',
    source_layer: transform?.source_layer ?? 'bronze',
    target_layer: transform?.target_layer ?? 'silver',
    sql: transform?.transform_sql ?? '',
    tags: '',
  })
  const [error, setError] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: (body: TransformCreate) => api.transforms.create(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transforms'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  const updateMut = useMutation({
    mutationFn: (body: TransformUpdate) => api.transforms.update(transform!.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transforms'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  const isPending = createMut.isPending || updateMut.isPending

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    if (!isEdit && !form.sql.trim()) { setError('SQL is required'); return }
    setError(null)
    const tags = form.tags.split(',').map((t) => t.trim()).filter(Boolean)
    if (isEdit) {
      const body: TransformUpdate = { name: form.name, description: form.description, tags }
      if (canEditSql) {
        body.sql = form.sql
        body.source_layer = form.source_layer
        body.target_layer = form.target_layer
      }
      updateMut.mutate(body)
    } else {
      createMut.mutate({ name: form.name, description: form.description, source_layer: form.source_layer, target_layer: form.target_layer, sql: form.sql, tags })
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">
            {isEdit ? 'Edit Transform' : 'New Transform'}
          </span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>

        {isEdit && !isDraft && !canAdmin && (
          <div className="px-4 py-2 bg-j-amber-dim border-b border-j-amber font-mono text-[10px] text-j-amber">
            ⚠ This transform is {transform.status} — SQL and layer fields are locked. Only name, description and tags can be changed.
          </div>
        )}
        {isEdit && !isDraft && canAdmin && (
          <div className="px-4 py-2 bg-j-amber-dim border-b border-j-amber font-mono text-[10px] text-j-amber">
            ⚠ This transform is {transform.status}. Editing the SQL will reset it to draft and require re-approval.
          </div>
        )}

        <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4 max-h-[80vh] overflow-y-auto">
          {/* Name */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Name <span className="text-j-red">*</span></label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="e.g. customers_to_silver"
            />
          </div>

          {/* Description */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Description</label>
            <input
              type="text"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              placeholder="What does this transform do?"
            />
          </div>

          {/* Layers */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Source Layer</label>
              {canEditSql ? (
                <select
                  value={form.source_layer}
                  onChange={(e) => setForm((f) => ({ ...f, source_layer: e.target.value }))}
                  className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
                >
                  {LAYERS.map((l) => <option key={l} value={l}>{l}</option>)}
                </select>
              ) : (
                <p className="font-mono text-xs text-j-dim bg-j-surface2 border border-j-border rounded px-3 py-1.5">{form.source_layer}</p>
              )}
            </div>
            <div>
              <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Target Layer</label>
              {canEditSql ? (
                <select
                  value={form.target_layer}
                  onChange={(e) => setForm((f) => ({ ...f, target_layer: e.target.value }))}
                  className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
                >
                  {LAYERS.map((l) => <option key={l} value={l}>{l}</option>)}
                </select>
              ) : (
                <p className="font-mono text-xs text-j-dim bg-j-surface2 border border-j-border rounded px-3 py-1.5">{form.target_layer}</p>
              )}
            </div>
          </div>

          {/* SQL */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">
              SQL {!isEdit && <span className="text-j-red">*</span>}
              {!canEditSql && <span className="ml-2 text-j-amber opacity-70">(locked)</span>}
            </label>
            <textarea
              value={form.sql}
              onChange={(e) => setForm((f) => ({ ...f, sql: e.target.value }))}
              disabled={!canEditSql}
              rows={8}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent resize-y disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder="CREATE TABLE silver.customers AS SELECT ..."
              style={{ minHeight: '200px' }}
            />
          </div>

          {/* Tags */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Tags</label>
            <input
              type="text"
              value={form.tags}
              onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
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
              disabled={isPending}
              className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-3 py-1.5 rounded hover:bg-j-accent hover:text-j-bg transition-colors disabled:opacity-50"
            >
              {isPending ? (isEdit ? 'Saving…' : 'Creating…') : (isEdit ? 'Save' : 'Create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Transform card ────────────────────────────────────────────────────────────

function TransformCard({ transform, canApprove, canWrite, canAdmin }: { transform: Transform; canApprove: boolean; canWrite: boolean; canAdmin: boolean }) {
  const [sqlOpen, setSqlOpen] = useState(false)
  const [execResult, setExecResult] = useState<ExecuteResult | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const qc = useQueryClient()
  const { confirm } = useToast()

  const isDraft = transform.status === 'draft'
  const canEdit = canWrite && (canAdmin || isDraft)

  const approveMut = useMutation({
    mutationFn: (action: 'approve' | 'reject') => api.transforms.approve(transform.id, action),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['transforms'] }),
  })
  const executeMut = useMutation({
    mutationFn: () => api.transforms.execute(transform.id),
    onSuccess: (r) => { setExecResult(r); qc.invalidateQueries({ queryKey: ['transforms'] }) },
  })
  const deleteMut = useMutation({
    mutationFn: () => api.transforms.delete(transform.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['transforms'] }),
  })
  const busy = approveMut.isPending || executeMut.isPending || deleteMut.isPending

  return (
    <>
      <div className="border border-j-border rounded bg-j-surface overflow-hidden">
        <div className="px-4 py-3">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-mono text-j-bright font-medium truncate">{transform.name}</span>
            <StatusBadge status={transform.status} />
            <LayerArrow from={transform.source_layer} to={transform.target_layer} />
            <CollectionTag resourceType="transform" resourceId={transform.id} current={transform.collection} />
          </div>
          {transform.description && (
            <p className="font-mono text-[11px] text-j-dim mt-0.5 line-clamp-2">{transform.description}</p>
          )}
          <div className="flex items-center justify-between gap-2 flex-wrap mt-2">
            <p className="font-mono text-[10px] text-j-dim">
              {transform.created_by}
              {transform.approved_by && <span> · approved by {transform.approved_by}</span>}
              <span className="ml-2">{new Date(transform.created_at).toLocaleDateString()}</span>
            </p>
            {/* Actions */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {canEdit && (
                <button onClick={() => setEditOpen(true)}
                  className="px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-border text-j-dim hover:border-j-accent hover:text-j-accent disabled:opacity-30 transition-colors">
                  Edit
                </button>
              )}
              {canApprove && isDraft && (
                <>
                  <button disabled={busy} onClick={() => approveMut.mutate('approve')}
                    className="px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-green bg-j-green-dim text-j-green hover:bg-j-green hover:text-j-bg disabled:opacity-30 transition-colors">
                    Approve
                  </button>
                  <button disabled={busy} onClick={() => approveMut.mutate('reject')}
                    className="px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-red bg-j-red-dim text-j-red hover:bg-j-red hover:text-j-bg disabled:opacity-30 transition-colors">
                    Reject
                  </button>
                </>
              )}
              {canApprove && transform.status === 'approved' && (
                <button disabled={busy} onClick={() => executeMut.mutate()}
                  className="px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-accent bg-j-accent-dim text-j-accent hover:bg-j-accent hover:text-j-bg disabled:opacity-30 transition-colors">
                  {executeMut.isPending ? 'running…' : 'Execute'}
                </button>
              )}
              {canAdmin && (
                <button disabled={busy} onClick={async () => {
                  const ok = await confirm(`Delete transform "${transform.name}"?`)
                  if (!ok) return
                  deleteMut.mutate()
                }}
                  className="px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-red/40 text-j-red/60 hover:border-j-red hover:text-j-red disabled:opacity-30 transition-colors">
                  {deleteMut.isPending ? '…' : '✕'}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* SQL toggle */}
        <div className="px-4 pb-3">
          <button onClick={() => setSqlOpen(!sqlOpen)}
            className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent flex items-center gap-1.5 transition-colors">
            <span className={`text-xs transition-transform ${sqlOpen ? 'rotate-90' : ''}`}>▶</span>
            {sqlOpen ? 'hide sql' : 'view sql'}
          </button>

          {sqlOpen && (
            <div className="mt-2 rounded border border-j-border overflow-hidden fade-up">
              <div className="px-3 py-1.5 bg-j-surface2 border-b border-j-border flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-j-amber opacity-70" />
                <span className="font-mono text-[10px] tracking-[0.12em] uppercase text-j-dim">sql</span>
              </div>
              <pre className="flex bg-j-surface overflow-x-auto">
                <span className="select-none text-right font-mono text-[12px] leading-relaxed text-j-border shrink-0 px-3 py-3 border-r border-j-border/30 whitespace-pre">
                  {(transform.transform_sql || '— no sql —').split('\n').map((_, i) => i + 1).join('\n')}
                </span>
                <code className="font-mono text-[12px] leading-relaxed text-j-text whitespace-pre pl-4 py-3 flex-1">
                  {transform.transform_sql || '— no sql —'}
                </code>
              </pre>
            </div>
          )}

          {approveMut.error && (
            <p className="mt-2 font-mono text-[11px] text-j-red">
              {approveMut.error instanceof Error ? approveMut.error.message : 'error'}
            </p>
          )}
          {execResult && <ExecResult result={execResult} />}
        </div>
      </div>

      {editOpen && <TransformFormModal transform={transform} onClose={() => setEditOpen(false)} />}
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TransformsPage() {
  const { canWrite, canApprove, canAdmin } = usePermissions()
  const [searchParams, setSearchParams] = useSearchParams()
  const collectionFilter = searchParams.get('collection')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)

  const { data: transforms, isLoading, error, refetch } = useQuery({
    queryKey: ['transforms'],
    queryFn: api.transforms.list,
    staleTime: 30_000,
  })

  const filtered = (transforms ?? []).filter((t) =>
    (statusFilter === 'all' || t.status === statusFilter) &&
    (!search || t.name.toLowerCase().includes(search.toLowerCase())) &&
    (!collectionFilter || t.collection === collectionFilter),
  )

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      <PageHeader label="Transforms" title="SQL Transforms">
        <input
          type="text"
          placeholder="filter transforms…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="font-mono text-[11px] bg-j-surface border border-j-border rounded px-2.5 py-1.5 text-j-bright placeholder-j-dim focus:outline-none focus:border-j-accent w-40"
        />
        <div className="flex items-center gap-1">
          {['all', 'draft', 'approved'].map((s) => (
            <button key={s} onClick={() => setStatusFilter(s)}
              className={`font-mono text-[10px] tracking-[0.08em] uppercase px-2.5 py-1.5 rounded border transition-colors ${
                statusFilter === s
                  ? 'border-j-accent text-j-accent bg-j-surface2'
                  : 'border-j-border text-j-dim hover:border-j-accent hover:text-j-accent'
              }`}>
              {s}
            </button>
          ))}
        </div>
        {collectionFilter && (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-j-accent border border-j-accent bg-j-accent-dim rounded px-2 py-1">
            ◧ {collectionFilter}
            <button onClick={() => setSearchParams({})} className="hover:text-j-bright">✕</button>
          </span>
        )}
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

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading transforms…</p>}
      {error && <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">{error instanceof Error ? error.message : 'error'}</div>}
      {!isLoading && !error && filtered.length === 0 && (
        <p className="font-mono text-[11px] text-j-dim text-center py-16">
          {statusFilter === 'all' ? 'no transforms yet — run make seed' : `no ${statusFilter} transforms`}
        </p>
      )}

      <div className="space-y-3">
        {filtered.map((t) => (
          <TransformCard
            key={t.id}
            transform={t}
            canApprove={canApprove}
            canWrite={canWrite}
            canAdmin={canAdmin}
          />
        ))}
      </div>

      {showCreate && <TransformFormModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}
