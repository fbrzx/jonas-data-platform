import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Transform, type ExecuteResult, getToken, getRoleFromToken } from '../lib/api'

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

// ── Transform card ────────────────────────────────────────────────────────────

function TransformCard({ transform, canApprove }: { transform: Transform; canApprove: boolean }) {
  const [sqlOpen, setSqlOpen] = useState(false)
  const [execResult, setExecResult] = useState<ExecuteResult | null>(null)
  const qc = useQueryClient()

  const approveMut = useMutation({
    mutationFn: (action: 'approve' | 'reject') => api.transforms.approve(transform.id, action),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['transforms'] }),
  })
  const executeMut = useMutation({
    mutationFn: () => api.transforms.execute(transform.id),
    onSuccess: (r) => { setExecResult(r); qc.invalidateQueries({ queryKey: ['transforms'] }) },
  })
  const busy = approveMut.isPending || executeMut.isPending

  return (
    <div className="border border-j-border rounded bg-j-surface overflow-hidden">
      <div className="px-4 py-3 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-j-bright font-medium">{transform.name}</span>
            <StatusBadge status={transform.status} />
            <LayerArrow from={transform.source_layer} to={transform.target_layer} />
          </div>
          {transform.description && (
            <p className="font-mono text-[11px] text-j-dim mt-0.5">{transform.description}</p>
          )}
          <p className="font-mono text-[10px] text-j-dim mt-1.5">
            {transform.created_by}
            {transform.approved_by && <span> · approved by {transform.approved_by}</span>}
            <span className="ml-2">{new Date(transform.created_at).toLocaleDateString()}</span>
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {canApprove && transform.status === 'draft' && (
            <>
              <button disabled={busy} onClick={() => approveMut.mutate('approve')}
                className="px-3 py-1.5 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-green bg-j-green-dim text-j-green hover:bg-j-green hover:text-j-bg disabled:opacity-30 transition-colors">
                Approve
              </button>
              <button disabled={busy} onClick={() => approveMut.mutate('reject')}
                className="px-3 py-1.5 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-red bg-j-red-dim text-j-red hover:bg-j-red hover:text-j-bg disabled:opacity-30 transition-colors">
                Reject
              </button>
            </>
          )}
          {canApprove && transform.status === 'approved' && (
            <button disabled={busy} onClick={() => executeMut.mutate()}
              className="px-3 py-1.5 font-mono text-[10px] tracking-[0.1em] uppercase rounded border border-j-accent bg-j-accent-dim text-j-accent hover:bg-j-accent hover:text-j-bg disabled:opacity-30 transition-colors">
              {executeMut.isPending ? 'running…' : 'Execute'}
            </button>
          )}
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
            <pre className="bg-j-surface px-4 py-3 text-[12px] font-mono text-j-text overflow-x-auto leading-relaxed">
              {transform.transform_sql || '— no sql —'}
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
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TransformsPage() {
  const role = getRoleFromToken(getToken())
  const canApprove = role === 'admin'
  const [statusFilter, setStatusFilter] = useState('all')

  const { data: transforms, isLoading, error, refetch } = useQuery({
    queryKey: ['transforms'],
    queryFn: api.transforms.list,
    staleTime: 30_000,
  })

  const filtered = (transforms ?? []).filter((t) => statusFilter === 'all' || t.status === statusFilter)

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      <div className="flex items-center justify-between mb-5 pb-4 border-b border-j-border">
        <div>
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">Transforms</div>
          <h2 className="text-j-bright font-semibold">SQL Transforms</h2>
        </div>
        <button onClick={() => refetch()} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors">
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 mb-6">
        {['all', 'draft', 'approved', 'rejected'].map((s) => (
          <button key={s} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 font-mono text-[10px] tracking-[0.1em] uppercase rounded border transition-colors ${
              statusFilter === s
                ? 'bg-j-surface2 text-j-bright border-j-border-b'
                : 'text-j-dim border-j-border hover:border-j-border-b hover:text-j-text'
            }`}>
            {s}
          </button>
        ))}
        {!canApprove && (
          <span className="ml-auto font-mono text-[10px] text-j-dim">analyst · read-only</span>
        )}
      </div>

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading transforms…</p>}
      {error && <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">{error instanceof Error ? error.message : 'error'}</div>}
      {!isLoading && !error && filtered.length === 0 && (
        <p className="font-mono text-[11px] text-j-dim text-center py-16">
          {statusFilter === 'all' ? 'no transforms yet — run make seed' : `no ${statusFilter} transforms`}
        </p>
      )}

      <div className="space-y-3">
        {filtered.map((t) => <TransformCard key={t.id} transform={t} canApprove={canApprove} />)}
      </div>
    </div>
  )
}
