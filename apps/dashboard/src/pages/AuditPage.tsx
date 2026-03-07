import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type AuditJob, type AuditLog } from '../lib/api'
import PageHeader from '../components/PageHeader'

// ── DataPager ─────────────────────────────────────────────────────────────────

function DataPager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number
  pageSize: number
  total: number
  onPage: (p: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  if (totalPages <= 1) return null
  return (
    <div className="flex items-center gap-2 mt-3 justify-end">
      <button
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
        className="px-2 py-1 font-mono text-[10px] tracking-wider uppercase border border-j-border text-j-dim rounded hover:border-j-accent hover:text-j-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        ← prev
      </button>
      <span className="font-mono text-[10px] text-j-dim">
        {page} / {totalPages}
        <span className="ml-2 text-j-border">({total} total)</span>
      </span>
      <button
        onClick={() => onPage(page + 1)}
        disabled={page >= totalPages}
        className="px-2 py-1 font-mono text-[10px] tracking-wider uppercase border border-j-border text-j-dim rounded hover:border-j-accent hover:text-j-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        next →
      </button>
    </div>
  )
}

// ── Jobs tab ──────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  success:  'text-j-green  bg-j-green-dim  border-j-green',
  partial:  'text-j-yellow bg-j-yellow-dim border-j-yellow',
  failed:   'text-j-red    bg-j-red-dim    border-j-red',
  running:  'text-j-accent bg-j-accent-dim border-j-accent',
}

function statusClass(status: string) {
  return STATUS_COLORS[status] ?? 'text-j-dim bg-j-surface2 border-j-border'
}

function fmtDate(s?: string) {
  if (!s) return '—'
  return new Date(s).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function JobsTab({ search }: { search: string }) {
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 25

  const { data, isLoading, error } = useQuery({
    queryKey: ['audit-jobs', page],
    queryFn: () => api.audit.jobs(page, PAGE_SIZE),
  })

  if (isLoading)
    return <p className="font-mono text-xs text-j-dim py-8 text-center">loading…</p>
  if (error)
    return <p className="font-mono text-xs text-j-red py-4">Error: {String(error)}</p>

  const q = search.toLowerCase()
  const jobs: AuditJob[] = (data?.jobs ?? []).filter(
    (j) => !q || j.job_name.toLowerCase().includes(q) || j.job_type.toLowerCase().includes(q) || j.status.toLowerCase().includes(q),
  )

  return (
    <div>
      <div className="overflow-x-auto rounded border border-j-border">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-j-border bg-j-surface2">
              {['type', 'name', 'sub-type', 'status', 'started', 'in', 'out', 'rejected'].map((h) => (
                <th key={h} className={`px-3 py-2 text-j-dim tracking-[0.1em] uppercase font-medium text-[10px] ${['in', 'out', 'rejected'].includes(h) ? 'text-right' : 'text-left'}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center text-j-dim py-8">No jobs found</td>
              </tr>
            )}
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-j-border hover:bg-j-surface2 transition-colors">
                <td className="px-3 py-2 text-j-dim">{job.job_type}</td>
                <td className="px-3 py-2 text-j-bright max-w-[200px] truncate">{job.job_name}</td>
                <td className="px-3 py-2 text-j-dim">{job.sub_type}</td>
                <td className="px-3 py-2">
                  <span className={`px-1.5 py-0.5 rounded border text-[10px] ${statusClass(job.status)}`}>
                    {job.status}
                  </span>
                </td>
                <td className="px-3 py-2 text-j-dim whitespace-nowrap">{fmtDate(job.started_at)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{job.records_in}</td>
                <td className="px-3 py-2 text-right tabular-nums text-j-green">{job.records_out}</td>
                <td className="px-3 py-2 text-right tabular-nums text-j-red">{job.records_rejected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DataPager page={page} pageSize={PAGE_SIZE} total={data?.total ?? 0} onPage={setPage} />
    </div>
  )
}

// ── Logs tab ──────────────────────────────────────────────────────────────────

const ACTION_OPTIONS = ['', 'create', 'update', 'delete', 'approve', 'reject', 'execute', 'ingest']
const ENTITY_OPTIONS = ['', 'entity', 'field', 'transform', 'connector', 'permission']

function LogsTab({ search }: { search: string }) {
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [entityType, setEntityType] = useState('')
  const PAGE_SIZE = 25

  const { data, isLoading, error } = useQuery({
    queryKey: ['audit-logs', page, action, entityType],
    queryFn: () => api.audit.logs(page, PAGE_SIZE, action || undefined, entityType || undefined),
  })

  function handleFilter() { setPage(1) }

  if (error)
    return <p className="font-mono text-xs text-j-red py-4">Error: {String(error)}</p>

  const q = search.toLowerCase()
  const logs: AuditLog[] = (data?.logs ?? []).filter(
    (l) => !q || l.action.toLowerCase().includes(q) || l.resource_type.toLowerCase().includes(q) || (l.user_id ?? '').toLowerCase().includes(q) || (l.detail ?? '').toLowerCase().includes(q),
  )

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-j-dim uppercase tracking-wider">Action</span>
          <select
            value={action}
            onChange={(e) => { setAction(e.target.value); handleFilter() }}
            className="bg-j-surface2 border border-j-border rounded px-2 py-1 font-mono text-xs text-j-text focus:outline-none focus:border-j-accent"
          >
            {ACTION_OPTIONS.map((o) => (
              <option key={o} value={o}>{o || '— all —'}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-j-dim uppercase tracking-wider">Entity</span>
          <select
            value={entityType}
            onChange={(e) => { setEntityType(e.target.value); handleFilter() }}
            className="bg-j-surface2 border border-j-border rounded px-2 py-1 font-mono text-xs text-j-text focus:outline-none focus:border-j-accent"
          >
            {ENTITY_OPTIONS.map((o) => (
              <option key={o} value={o}>{o || '— all —'}</option>
            ))}
          </select>
        </div>
        {(action || entityType) && (
          <button
            onClick={() => { setAction(''); setEntityType(''); setPage(1) }}
            className="font-mono text-[10px] tracking-wider uppercase text-j-dim hover:text-j-accent transition-colors"
          >
            × clear
          </button>
        )}
      </div>

      {isLoading && (
        <p className="font-mono text-xs text-j-dim py-8 text-center">loading…</p>
      )}

      {!isLoading && (
        <>
          <div className="overflow-x-auto rounded border border-j-border">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-j-border bg-j-surface2">
                  {['when', 'user', 'action', 'entity type', 'entity id', 'detail'].map((h) => (
                    <th key={h} className="text-left px-3 py-2 text-j-dim tracking-[0.1em] uppercase font-medium text-[10px]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center text-j-dim py-8">No log entries found</td>
                  </tr>
                )}
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-j-border hover:bg-j-surface2 transition-colors">
                    <td className="px-3 py-2 text-j-dim whitespace-nowrap">{fmtDate(log.created_at)}</td>
                    <td className="px-3 py-2 text-j-dim max-w-[120px] truncate">{log.user_id}</td>
                    <td className="px-3 py-2">
                      <span className="text-j-accent">{log.action}</span>
                    </td>
                    <td className="px-3 py-2 text-j-dim">{log.resource_type}</td>
                    <td className="px-3 py-2 text-j-dim text-[10px] max-w-[100px] truncate">{log.resource_id ?? '—'}</td>
                    <td className="px-3 py-2 text-j-text max-w-[300px] truncate" title={log.detail}>
                      {log.detail ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <DataPager page={page} pageSize={PAGE_SIZE} total={data?.total ?? 0} onPage={setPage} />
        </>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = 'jobs' | 'logs'

export default function AuditPage() {
  const [tab, setTab] = useState<Tab>('jobs')
  const [search, setSearch] = useState('')

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      <PageHeader label="Audit" title="Jobs & Change History">
        <input
          type="text"
          placeholder="search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="font-mono text-[11px] bg-j-surface border border-j-border rounded px-2.5 py-1.5 text-j-bright placeholder-j-dim focus:outline-none focus:border-j-accent w-40"
        />
        <div className="flex items-center gap-1">
          {(['jobs', 'logs'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`font-mono text-[10px] tracking-[0.08em] uppercase px-2.5 py-1.5 rounded border transition-colors ${
                tab === t
                  ? 'border-j-accent text-j-accent bg-j-surface2'
                  : 'border-j-border text-j-dim hover:border-j-accent hover:text-j-accent'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </PageHeader>

      {tab === 'jobs' ? <JobsTab search={search} /> : <LogsTab search={search} />}
    </div>
  )
}
