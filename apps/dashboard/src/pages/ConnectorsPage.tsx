import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Integration, type IntegrationCreate, type IntegrationUpdate, type IntegrationRun } from '../lib/api'
import { usePermissions } from '../lib/permissions'
import { useToast } from '../lib/toast'
import PageHeader from '../components/PageHeader'
import CollectionTag from '../components/CollectionTag'

// ── Cron helpers ───────────────────────────────────────────────────────────────

function parseCronHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hour, dom, , dow] = parts
  if (min === '0' && hour !== '*' && dom === '*' && dow === '*') return `daily at ${hour}:00 UTC`
  if (min === '0' && hour === '*' && dom === '*' && dow === '*') return 'every hour'
  if (min === '*/15' && hour === '*') return 'every 15 min'
  if (min === '*/30' && hour === '*') return 'every 30 min'
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  if (dom === '*' && dow !== '*') {
    const d = days[parseInt(dow, 10)]
    return d ? `weekly on ${d}` : cron
  }
  return cron
}

// ── Constants ──────────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, { dot: string; text: string; bg: string; border: string }> = {
  active:   { dot: 'bg-j-green',  text: 'text-j-green',  bg: 'bg-j-green-dim',  border: 'border-j-green'  },
  inactive: { dot: 'bg-j-dim',    text: 'text-j-dim',    bg: 'bg-j-surface2',   border: 'border-j-border' },
  error:    { dot: 'bg-j-red',    text: 'text-j-red',    bg: 'bg-j-red-dim',    border: 'border-j-red'    },
}

const RUN_STATUS_STYLE: Record<string, { text: string; bg: string; border: string }> = {
  success: { text: 'text-j-green', bg: 'bg-j-green-dim', border: 'border-j-green' },
  partial: { text: 'text-j-amber', bg: 'bg-j-amber-dim', border: 'border-j-amber' },
  failed:  { text: 'text-j-red',   bg: 'bg-j-red-dim',   border: 'border-j-red'   },
  running: { text: 'text-j-accent', bg: 'bg-j-surface2', border: 'border-j-accent' },
}

const TYPE_GLYPH: Record<string, string> = {
  webhook:    '⬡',
  batch_csv:  '⊞',
  batch_json: '⊟',
  api_pull:   '◎',
}

const TYPE_COLOR: Record<string, string> = {
  webhook:    'text-j-purple',
  batch_csv:  'text-j-accent',
  batch_json: 'text-j-amber',
  api_pull:   'text-j-green',
}

const CONNECTOR_TYPES = [
  { value: 'webhook',    label: 'Webhook',    hint: 'Real-time JSON events via HTTP POST' },
  { value: 'batch_csv',  label: 'Batch CSV',  hint: 'Periodic CSV file uploads (max 50 MB)' },
  { value: 'batch_json', label: 'Batch JSON', hint: 'Periodic JSON file uploads (array or newline-delimited)' },
  { value: 'api_pull',   label: 'API Pull',   hint: 'Manually trigger a fetch from a remote JSON endpoint' },
]

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).catch(() => undefined)
}

function webhookUrl(id: string) {
  return `${window.location.origin}/api/v1/connectors/${id}/webhook`
}

// ── Run History Panel ──────────────────────────────────────────────────────────

function RunHistory({ connectorId, onClose }: { connectorId: string; onClose: () => void }) {
  const { data: runs, isLoading, error } = useQuery({
    queryKey: ['connector-runs', connectorId],
    queryFn: () => api.connectors.getRuns(connectorId),
    staleTime: 10_000,
  })

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">Run History</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕ close</button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-8">loading…</p>}
          {error && <p className="font-mono text-[11px] text-j-red text-center py-8">failed to load runs</p>}
          {!isLoading && !error && !(runs ?? []).length && (
            <p className="font-mono text-[11px] text-j-dim text-center py-8">no runs recorded yet</p>
          )}
          {(runs ?? []).map((run: IntegrationRun) => {
            const s = RUN_STATUS_STYLE[run.status] ?? RUN_STATUS_STYLE.running
            const errors = (run.error_detail as { errors?: string[] } | undefined)?.errors ?? []
            return (
              <div key={run.id} className="px-4 py-3 border-b border-j-border last:border-0">
                <div className="flex items-center justify-between mb-1">
                  <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${s.bg} ${s.text} ${s.border}`}>
                    {run.status}
                  </span>
                  <span className="font-mono text-[10px] text-j-dim">{fmtDate(run.started_at)}</span>
                </div>
                <div className="flex gap-4 font-mono text-[10px] text-j-dim mt-1">
                  <span>in: <span className="text-j-bright">{run.records_in}</span></span>
                  <span>out: <span className="text-j-bright">{run.records_out}</span></span>
                  {run.records_rejected > 0 && (
                    <span>rejected: <span className="text-j-red">{run.records_rejected}</span></span>
                  )}
                </div>
                {errors.length > 0 && (
                  <div className="mt-2 font-mono text-[10px] text-j-red bg-j-red-dim border border-j-red rounded px-2 py-1.5 space-y-0.5">
                    {errors.slice(0, 3).map((e, i) => <div key={i}>{e}</div>)}
                    {errors.length > 3 && <div>…and {errors.length - 3} more</div>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Upload Modal ───────────────────────────────────────────────────────────────

function UploadModal({
  connector,
  onClose,
}: {
  connector: Integration
  onClose: () => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: (file: File) => api.connectors.uploadBatch(connector.id, file),
    onSuccess: (data) => {
      setResult(`✓ Landed ${data.rows_landed}/${data.rows_received} rows into ${data.target_table}` +
        (data.errors.length ? `\n⚠ ${data.errors.length} row error(s): ${data.errors.slice(0, 2).join('; ')}` : ''))
    },
    onError: (err: Error) => setResult(`✗ ${err.message}`),
  })

  function handleUpload() {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setResult(null)
    mutation.mutate(file)
  }

  const accept = connector.connector_type === 'batch_csv' ? '.csv' : '.json,.ndjson'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">Upload to {connector.name}</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>
        <div className="px-4 py-4 space-y-3">
          <p className="font-mono text-[11px] text-j-dim">
            Upload a {connector.connector_type === 'batch_csv' ? 'CSV' : 'JSON'} file (max 50 MB).
            Rows will land in the bronze layer.
          </p>
          <input
            ref={fileRef}
            type="file"
            accept={accept}
            className="font-mono text-[11px] text-j-bright w-full"
          />
          {result && (
            <pre className={`font-mono text-[10px] rounded border px-2 py-1.5 whitespace-pre-wrap ${
              result.startsWith('✓') ? 'text-j-green bg-j-green-dim border-j-green' : 'text-j-red bg-j-red-dim border-j-red'
            }`}>{result}</pre>
          )}
          <div className="flex gap-2 justify-end">
            <button onClick={onClose} className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim border border-j-border px-3 py-1.5 rounded hover:border-j-border-b transition-colors">
              Cancel
            </button>
            <button
              onClick={handleUpload}
              disabled={mutation.isPending}
              className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-3 py-1.5 rounded hover:bg-j-accent hover:text-j-bg transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── OAuth Config Section ────────────────────────────────────────────────────────

type OAuthGrant = 'none' | 'client_credentials' | 'password' | 'salesforce_jwt'

interface OAuthConfig {
  grant_type?: OAuthGrant
  token_url?: string
  client_id?: string
  client_secret?: string
  scope?: string
  audience?: string
  base_url?: string
  username?: string
  password?: string
  subject?: string
  private_key_pem?: string
}

const GRANT_OPTIONS: { value: OAuthGrant; label: string; hint: string }[] = [
  { value: 'none',               label: 'None',                hint: 'No OAuth — use a static Bearer token in the Authorization header above, or no auth' },
  { value: 'client_credentials', label: 'Client Credentials',  hint: 'Machine-to-machine. Used by Salesforce Connected Apps and Adobe IMS' },
  { value: 'password',           label: 'Password',            hint: 'Resource-owner password flow (username + password)' },
  { value: 'salesforce_jwt',     label: 'Salesforce JWT',      hint: 'Salesforce JWT Bearer / certificate flow — no client_secret required' },
]

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="font-mono text-[10px] text-j-dim block mb-1">{label}</label>
      {children}
      {hint && <p className="font-mono text-[10px] text-j-dim mt-0.5 opacity-70">{hint}</p>}
    </div>
  )
}

function inputCls(bg = 'bg-j-bg') {
  return `w-full ${bg} border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent`
}

function OAuthConfigSection({
  value,
  onChange,
}: {
  value: OAuthConfig
  onChange: (v: OAuthConfig) => void
}) {
  const [open, setOpen] = useState((value.grant_type ?? 'none') !== 'none')

  const grant = value.grant_type ?? 'none'

  function set(patch: Partial<OAuthConfig>) {
    onChange({ ...value, ...patch })
  }

  return (
    <div className="rounded border border-j-border bg-j-surface2">
      {/* Header toggle */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 font-mono text-[10px] text-left hover:bg-j-surface transition-colors rounded"
      >
        <span className="tracking-[0.1em] uppercase text-j-dim">
          OAuth / Token Auth
          {grant !== 'none' && (
            <span className="ml-2 normal-case text-j-accent">{grant}</span>
          )}
        </span>
        <span className="text-j-dim">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3 border-t border-j-border">
          {/* Grant type selector */}
          <div className="pt-2">
            <label className="font-mono text-[10px] text-j-dim block mb-1.5">Grant Type</label>
            <div className="grid grid-cols-2 gap-1.5">
              {GRANT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => set({ grant_type: opt.value })}
                  className={`px-2 py-1.5 rounded border font-mono text-[10px] text-left transition-colors ${
                    grant === opt.value
                      ? 'border-j-accent bg-j-accent/10 text-j-accent'
                      : 'border-j-border text-j-dim hover:border-j-border-b'
                  }`}
                  title={opt.hint}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {grant !== 'none' && (
              <p className="font-mono text-[10px] text-j-dim mt-1.5 opacity-70">
                {GRANT_OPTIONS.find((o) => o.value === grant)?.hint}
              </p>
            )}
          </div>

          {/* client_credentials / password shared fields */}
          {(grant === 'client_credentials' || grant === 'password') && (
            <>
              <Field label="Token URL *">
                <input type="url" placeholder="https://login.salesforce.com/services/oauth2/token"
                  value={value.token_url ?? ''} onChange={(e) => set({ token_url: e.target.value })}
                  className={inputCls()} />
              </Field>
              <Field label="Client ID *">
                <input type="text" placeholder="3MVG9…" value={value.client_id ?? ''}
                  onChange={(e) => set({ client_id: e.target.value })} className={inputCls()} />
              </Field>
              <Field label="Client Secret *">
                <input type="password" placeholder="••••••••" value={value.client_secret ?? ''}
                  onChange={(e) => set({ client_secret: e.target.value })} className={inputCls()} />
              </Field>
              <Field label="Scope" hint="Space-delimited. e.g. api refresh_token (optional)">
                <input type="text" placeholder="api" value={value.scope ?? ''}
                  onChange={(e) => set({ scope: e.target.value })} className={inputCls()} />
              </Field>
              {grant === 'client_credentials' && (
                <Field label="Audience" hint="Required for Adobe IMS. Leave blank for Salesforce.">
                  <input type="text" placeholder="https://ims-na1.adobelogin.com/c/…"
                    value={value.audience ?? ''} onChange={(e) => set({ audience: e.target.value })}
                    className={inputCls()} />
                </Field>
              )}
            </>
          )}

          {/* password-only fields */}
          {grant === 'password' && (
            <>
              <Field label="Username *">
                <input type="text" placeholder="user@org.com" value={value.username ?? ''}
                  onChange={(e) => set({ username: e.target.value })} className={inputCls()} />
              </Field>
              <Field label="Password *">
                <input type="password" placeholder="••••••••" value={value.password ?? ''}
                  onChange={(e) => set({ password: e.target.value })} className={inputCls()} />
              </Field>
            </>
          )}

          {/* salesforce_jwt fields */}
          {grant === 'salesforce_jwt' && (
            <>
              <Field label="Token URL" hint="Defaults to https://login.salesforce.com/services/oauth2/token">
                <input type="url" placeholder="https://login.salesforce.com/services/oauth2/token"
                  value={value.token_url ?? ''} onChange={(e) => set({ token_url: e.target.value })}
                  className={inputCls()} />
              </Field>
              <Field label="Client ID (Consumer Key) *">
                <input type="text" placeholder="3MVG9…" value={value.client_id ?? ''}
                  onChange={(e) => set({ client_id: e.target.value })} className={inputCls()} />
              </Field>
              <Field label="Subject (Salesforce username) *">
                <input type="text" placeholder="admin@yourorg.com" value={value.subject ?? ''}
                  onChange={(e) => set({ subject: e.target.value })} className={inputCls()} />
              </Field>
              <Field label="Private Key PEM *" hint="RSA private key. Paste the full -----BEGIN RSA PRIVATE KEY----- block.">
                <textarea
                  rows={4}
                  placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;MIIEo...&#10;-----END RSA PRIVATE KEY-----"
                  value={value.private_key_pem ?? ''}
                  onChange={(e) => set({ private_key_pem: e.target.value })}
                  className={`${inputCls()} resize-y`}
                />
              </Field>
              <Field label="Audience" hint="Defaults to https://login.salesforce.com">
                <input type="text" placeholder="https://login.salesforce.com"
                  value={value.audience ?? ''} onChange={(e) => set({ audience: e.target.value })}
                  className={inputCls()} />
              </Field>
            </>
          )}

          {/* base_url — shown for any OAuth grant (Salesforce relative URL resolution) */}
          {grant !== 'none' && (
            <Field label="Base URL" hint="Used to resolve relative pagination URLs (e.g. Salesforce nextRecordsUrl). e.g. https://yourorg.my.salesforce.com">
              <input type="url" placeholder="https://yourorg.my.salesforce.com"
                value={value.base_url ?? ''} onChange={(e) => set({ base_url: e.target.value })}
                className={inputCls()} />
            </Field>
          )}
        </div>
      )}
    </div>
  )
}

// ── Create Connector Modal ─────────────────────────────────────────────────────

function CreateModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<IntegrationCreate & { cron_schedule?: string }>({ name: '', connector_type: 'webhook' })
  const [oauthConfig, setOauthConfig] = useState<OAuthConfig>({ grant_type: 'none' })
  const [error, setError] = useState<string | null>(null)
  const { data: entities } = useQuery({ queryKey: ['entities'], queryFn: api.catalogue.list, staleTime: 60_000 })

  const mutation = useMutation({
    mutationFn: (body: IntegrationCreate) => api.connectors.create(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connectors'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    setError(null)
    const { cron_schedule, ...rest } = form
    // Strip empty OAuth config
    const authCfg = oauthConfig.grant_type && oauthConfig.grant_type !== 'none'
      ? Object.fromEntries(Object.entries(oauthConfig).filter(([, v]) => v !== '' && v != null))
      : undefined
    mutation.mutate({ ...rest, auth_config: authCfg }, {
      onSuccess: async (created) => {
        if (cron_schedule && created?.id) {
          await api.connectors.update(created.id, { cron_schedule }).catch(() => undefined)
          queryClient.invalidateQueries({ queryKey: ['connectors'] })
        }
      },
    })
  }

  const selectedType = CONNECTOR_TYPES.find((t) => t.value === form.connector_type)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">New Connector</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4">
          {/* Connector type */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-2">Type</label>
            <div className="grid grid-cols-2 gap-2">
              {CONNECTOR_TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, connector_type: t.value as IntegrationCreate['connector_type'], config: {} }))}
                  className={`px-2 py-2 rounded border font-mono text-[10px] text-left transition-colors ${
                    form.connector_type === t.value
                      ? 'border-j-accent bg-j-accent/10 text-j-accent'
                      : 'border-j-border text-j-dim hover:border-j-border-b'
                  }`}
                >
                  <div className="font-semibold">{TYPE_GLYPH[t.value]} {t.label}</div>
                </button>
              ))}
            </div>
            {selectedType && (
              <p className="font-mono text-[10px] text-j-dim mt-1.5">{selectedType.hint}</p>
            )}
          </div>

          {/* API Pull config */}
          {form.connector_type === 'api_pull' && (
            <div className="space-y-3 rounded border border-j-border bg-j-surface2 px-3 py-3">
              <p className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim">Pull Configuration</p>
              <div>
                <label className="font-mono text-[10px] text-j-dim block mb-1">Endpoint URL <span className="text-j-red">*</span></label>
                <input
                  type="url"
                  placeholder="https://api.example.com/data"
                  value={(form.config?.url as string) ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, config: { ...f.config, url: e.target.value } }))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
              </div>
              <div>
                <label className="font-mono text-[10px] text-j-dim block mb-1">
                  Static Authorization header <span className="text-j-dim">(optional — use OAuth below for Salesforce / Adobe)</span>
                </label>
                <input
                  type="text"
                  placeholder="Bearer your-token-here"
                  value={(form.config?.headers as Record<string, string> | undefined)?.Authorization ?? ''}
                  onChange={(e) => setForm((f) => ({
                    ...f,
                    config: { ...f.config, headers: { ...(f.config?.headers as object ?? {}), Authorization: e.target.value } },
                  }))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
              </div>
              <OAuthConfigSection value={oauthConfig} onChange={setOauthConfig} />
            </div>
          )}

          {/* Name */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Name <span className="text-j-red">*</span></label>
            <input
              type="text"
              placeholder="e.g. sales_orders_webhook"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
            />
            <p className="font-mono text-[10px] text-j-dim mt-1">Use snake_case. This becomes part of the bronze table name.</p>
          </div>

          {/* Description */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Description</label>
            <input
              type="text"
              placeholder="What data does this connector ingest?"
              value={form.description ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
            />
          </div>

          {/* Catalogue entity link */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Linked Entity</label>
            <select
              value={form.entity_id ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, entity_id: e.target.value || undefined }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
            >
              <option value="">— none —</option>
              {(entities ?? []).map((e) => (
                <option key={e.id} value={e.id}>{e.name} ({e.layer})</option>
              ))}
            </select>
            <p className="font-mono text-[10px] text-j-dim mt-1">Data lands in the linked entity's bronze table.</p>
          </div>

          {/* Cron schedule — api_pull only */}
          {form.connector_type === 'api_pull' && (
            <div>
              <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">
                Cron Schedule <span className="text-j-dim normal-case">(optional)</span>
              </label>
              <input
                type="text"
                placeholder="e.g. 0 * * * *  (every hour)"
                value={form.cron_schedule ?? ''}
                onChange={(e) => setForm((f) => ({ ...f, cron_schedule: e.target.value || undefined }))}
                className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
              />
              {form.cron_schedule && (
                <p className="font-mono text-[10px] text-j-green mt-1">
                  ↻ {parseCronHuman(form.cron_schedule)}
                </p>
              )}
            </div>
          )}

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

// ── Edit Connector Modal ───────────────────────────────────────────────────────

function EditConnectorModal({ connector, onClose }: { connector: Integration; onClose: () => void }) {
  const { canAdmin } = usePermissions()
  const qc = useQueryClient()

  const parsedConfig: Record<string, unknown> = (() => {
    try { return JSON.parse(connector.config ?? '{}') } catch { return {} }
  })()

  const parsedAuthConfig: OAuthConfig = (() => {
    try { return JSON.parse(connector.auth_config ?? '{}') as OAuthConfig } catch { return {} }
  })()

  const [form, setForm] = useState<IntegrationUpdate>({
    name: connector.name,
    description: connector.description ?? '',
    status: (connector.status as 'active' | 'paused') ?? 'active',
    config: parsedConfig,
    entity_id: connector.target_entity_id ?? null,
    cron_schedule: connector.cron_schedule ?? null,
  })
  const [oauthConfig, setOauthConfig] = useState<OAuthConfig>(
    parsedAuthConfig.grant_type ? parsedAuthConfig : { grant_type: 'none' }
  )
  const { data: entities } = useQuery({ queryKey: ['entities'], queryFn: api.catalogue.list, staleTime: 60_000 })
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: IntegrationUpdate) => api.connectors.update(connector.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const authCfg = oauthConfig.grant_type && oauthConfig.grant_type !== 'none'
      ? Object.fromEntries(Object.entries(oauthConfig).filter(([, v]) => v !== '' && v != null))
      : {}
    mutation.mutate({ ...form, auth_config: authCfg })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg bg-j-surface border border-j-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-j-border">
          <span className="font-mono text-xs font-semibold text-j-bright">Edit Connector</span>
          <button onClick={onClose} className="font-mono text-[10px] text-j-dim hover:text-j-accent">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="px-4 py-4 space-y-4">
          {/* Type — read-only */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Type</label>
            <p className="font-mono text-xs text-j-dim bg-j-surface2 border border-j-border rounded px-3 py-1.5">
              {TYPE_GLYPH[connector.connector_type] ?? '◉'} {connector.connector_type}
            </p>
          </div>

          {/* Name — admin only */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Name</label>
            {canAdmin ? (
              <>
                <input
                  type="text"
                  value={form.name ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
                <p className="font-mono text-[10px] text-j-red mt-1">
                  ⚠ Renaming affects the bronze table name — use with caution.
                </p>
              </>
            ) : (
              <p className="font-mono text-xs text-j-dim bg-j-surface2 border border-j-border rounded px-3 py-1.5">{connector.name}</p>
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
              placeholder="What data does this connector ingest?"
            />
          </div>

          {/* Status */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Status</label>
            <select
              value={form.status}
              onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as 'active' | 'paused' }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
            >
              <option value="active">active</option>
              <option value="paused">paused</option>
            </select>
          </div>

          {/* Catalogue entity link */}
          <div>
            <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1">Linked Entity</label>
            <select
              value={form.entity_id ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, entity_id: e.target.value || null }))}
              className="w-full bg-j-surface2 border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
            >
              <option value="">— none —</option>
              {(entities ?? []).map((e) => (
                <option key={e.id} value={e.id}>{e.name} ({e.layer})</option>
              ))}
            </select>
            <p className="font-mono text-[10px] text-j-dim mt-1">Data lands in the linked entity's bronze table.</p>
          </div>

          {/* API Pull config */}
          {connector.connector_type === 'api_pull' && (
            <div className="space-y-3 rounded border border-j-border bg-j-surface2 px-3 py-3">
              <p className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim">Pull Configuration</p>
              <div>
                <label className="font-mono text-[10px] text-j-dim block mb-1">Endpoint URL <span className="text-j-red">*</span></label>
                <input
                  type="url"
                  placeholder="https://api.example.com/data"
                  value={(form.config?.url as string) ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, config: { ...f.config, url: e.target.value } }))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
              </div>
              <div>
                <label className="font-mono text-[10px] text-j-dim block mb-1">
                  Static Authorization header <span className="text-j-dim">(optional — use OAuth below for Salesforce / Adobe)</span>
                </label>
                <input
                  type="text"
                  placeholder="Bearer your-token-here"
                  value={(form.config?.headers as Record<string, string> | undefined)?.Authorization ?? ''}
                  onChange={(e) => setForm((f) => ({
                    ...f,
                    config: { ...f.config, headers: { ...(f.config?.headers as object ?? {}), Authorization: e.target.value } },
                  }))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
              </div>
              <OAuthConfigSection value={oauthConfig} onChange={setOauthConfig} />
              <div>
                <label className="font-mono text-[10px] text-j-dim block mb-1">Cron Schedule <span className="text-j-dim">(optional)</span></label>
                <input
                  type="text"
                  placeholder="e.g. 0 * * * *  (every hour)"
                  value={form.cron_schedule ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, cron_schedule: e.target.value || null }))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-1.5 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
                {form.cron_schedule && (
                  <p className="font-mono text-[10px] text-j-green mt-1">↻ {parseCronHuman(form.cron_schedule)}</p>
                )}
              </div>
            </div>
          )}

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

// ── Connector Card ─────────────────────────────────────────────────────────────

function ConnectorCard({
  connector,
  canWrite,
  canApprove,
  canAdmin,
  onUpload,
  onRuns,
  onEdit,
  onDelete,
  onTrigger,
}: {
  connector: Integration
  canWrite: boolean
  canApprove: boolean
  canAdmin: boolean
  onUpload: () => void
  onRuns: () => void
  onEdit: () => void
  onDelete: () => void
  onTrigger: () => void
}) {
  const s = STATUS_STYLE[connector.status] ?? STATUS_STYLE.inactive
  const glyph = TYPE_GLYPH[connector.connector_type] ?? '◉'
  const glyphColor = TYPE_COLOR[connector.connector_type] ?? 'text-j-dim'
  const [copied, setCopied] = useState(false)
  const isWebhook = connector.connector_type === 'webhook'
  const isBatch = connector.connector_type === 'batch_csv' || connector.connector_type === 'batch_json'
  const isApiPull = connector.connector_type === 'api_pull'

  const parsedConfig: Record<string, unknown> = (() => {
    try { return JSON.parse(connector.config ?? '{}') } catch { return {} }
  })()
  const parsedAuthConfig: OAuthConfig = (() => {
    try { return JSON.parse(connector.auth_config ?? '{}') as OAuthConfig } catch { return {} }
  })()
  // Support both new (url/headers) and legacy (source_url/auth_header) config keys
  const configUrl = ((parsedConfig.url ?? parsedConfig.source_url) as string | undefined) ?? ''
  const configAuth =
    ((parsedConfig.headers as Record<string, string> | undefined)?.Authorization) ??
    (parsedConfig.auth_header as string | undefined) ?? ''
  const oauthGrant = parsedAuthConfig.grant_type

  function handleCopy() {
    copyText(webhookUrl(connector.id))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  function handleCopyUrl() {
    copyText(configUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="border border-j-border rounded bg-j-surface overflow-hidden hover:border-j-border-b transition-colors">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-j-border flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className={`font-mono text-2xl leading-none mt-0.5 shrink-0 ${glyphColor}`}>{glyph}</span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-j-bright font-medium truncate">{connector.name}</span>
            </div>
            {connector.description && (
              <p className="font-mono text-[11px] text-j-dim mt-0.5 truncate">{connector.description}</p>
            )}
          </div>
        </div>
        <span className={`shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] font-medium border ${s.bg} ${s.text} ${s.border}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
          {connector.status}
        </span>
      </div>

      {/* Webhook URL strip */}
      {isWebhook && (
        <div className="px-4 py-2 border-b border-j-border bg-j-surface2 flex items-center gap-2">
          <span className="font-mono text-[10px] text-j-dim truncate flex-1 select-all">
            POST {webhookUrl(connector.id)}
          </span>
          <button
            onClick={handleCopy}
            className="font-mono text-[10px] shrink-0 text-j-dim hover:text-j-accent transition-colors"
            title="Copy webhook URL"
          >
            {copied ? '✓ copied' : '⎘ copy'}
          </button>
        </div>
      )}

      {/* API Pull config strip */}
      {isApiPull && (
        <div className="px-4 py-2 border-b border-j-border bg-j-surface2 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-j-dim shrink-0">URL</span>
            {configUrl ? (
              <>
                <span className="font-mono text-[10px] text-j-text truncate flex-1 select-all" title={configUrl}>
                  {configUrl}
                </span>
                <button
                  onClick={handleCopyUrl}
                  className="font-mono text-[10px] shrink-0 text-j-dim hover:text-j-accent transition-colors"
                  title="Copy URL"
                >
                  {copied ? '✓' : '⎘'}
                </button>
              </>
            ) : (
              <span className="font-mono text-[10px] text-j-border italic">not configured</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-j-dim shrink-0">Auth</span>
            {oauthGrant && oauthGrant !== 'none' ? (
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-j-accent bg-j-accent/10 text-j-accent">
                OAuth · {oauthGrant === 'client_credentials' ? 'client creds'
                       : oauthGrant === 'salesforce_jwt' ? 'SF JWT'
                       : oauthGrant}
              </span>
            ) : configAuth ? (
              <span className="font-mono text-[10px] text-j-green">
                {configAuth.slice(0, 14)}{configAuth.length > 14 ? '●●●●' : ''}
              </span>
            ) : (
              <span className="font-mono text-[10px] text-j-border italic">none</span>
            )}
          </div>
        </div>
      )}

      {/* Meta + Actions */}
      <div className="px-4 py-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim">{connector.connector_type}</span>
          <span className="font-mono text-[10px] text-j-dim opacity-50">
            {fmtDate(connector.created_at)}
          </span>
          {connector.cron_schedule && (
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-j-green bg-j-green-dim text-j-green">
              ↻ {parseCronHuman(connector.cron_schedule)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          {canApprove && <CollectionTag resourceType="connector" resourceId={connector.id} current={connector.collection} />}
          <button
            onClick={onRuns}
            className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-2 py-1 rounded transition-colors"
            title="View run history"
          >
            runs
          </button>
          {isBatch && canWrite && (
            <button
              onClick={onUpload}
              className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-accent border border-j-accent px-2 py-1 rounded hover:bg-j-accent hover:text-j-bg transition-colors"
              title="Upload file"
            >
              upload
            </button>
          )}
          {isApiPull && canWrite && (
            <button
              onClick={onTrigger}
              className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-green border border-j-green px-2 py-1 rounded hover:bg-j-green hover:text-j-bg transition-colors"
              title="Fetch from endpoint now"
            >
              pull
            </button>
          )}
          {canApprove && (
            <button
              onClick={onEdit}
              className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-2 py-1 rounded transition-colors"
              title="Edit connector"
            >
              edit
            </button>
          )}
          {canAdmin && (
            <button
              onClick={onDelete}
              className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-red/60 border border-j-border hover:border-j-red hover:text-j-red px-2 py-1 rounded transition-colors"
              title="Delete connector"
            >
              ✕
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ConnectorsPage() {
  const queryClient = useQueryClient()
  const { canWrite, canApprove, canAdmin } = usePermissions()
  const { toast, confirm } = useToast()
  const [showCreate, setShowCreate] = useState(false)
  const [uploadTarget, setUploadTarget] = useState<Integration | null>(null)
  const [runsTarget, setRunsTarget] = useState<string | null>(null)
  const [editTarget, setEditTarget] = useState<Integration | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const collectionFilter = searchParams.get('collection')
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')

  const { data: connectors, isLoading, error, refetch } = useQuery({
    queryKey: ['connectors'],
    queryFn: api.connectors.list,
    staleTime: 30_000,
  })

  const filteredConnectors = (connectors ?? []).filter(
    (c) => (typeFilter === 'all' || c.connector_type === typeFilter) &&
           (!search || c.name.toLowerCase().includes(search.toLowerCase())) &&
           (!collectionFilter || c.collection === collectionFilter),
  )

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.connectors.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['connectors'] }),
    onError: (err: Error) => toast('error', `Delete failed: ${err.message}`),
  })

  const triggerMutation = useMutation({
    mutationFn: (id: string) => api.connectors.trigger(id),
    onSuccess: (data, id) => {
      queryClient.invalidateQueries({ queryKey: ['connector-runs', id] })
      queryClient.invalidateQueries({ queryKey: ['audit-jobs'] })
      const msg = `Pull complete — ${data.rows_landed} / ${data.rows_received} rows landed into ${data.target_table}`
      if (data.errors.length) {
        toast('info', msg + ` · ${data.errors.length} error(s)`)
      } else {
        toast('success', msg)
      }
    },
    onError: (err: Error) => toast('error', `Pull failed: ${err.message}`),
  })

  async function handleDelete(id: string, name: string) {
    const ok = await confirm(`Delete connector "${name}"? This cannot be undone.`)
    if (!ok) return
    deleteMutation.mutate(id)
  }

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      <PageHeader label="Connectors" title="Data Sources">
        <input
          type="text"
          placeholder="filter connectors…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="font-mono text-[11px] bg-j-surface border border-j-border rounded px-2.5 py-1.5 text-j-bright placeholder-j-dim focus:outline-none focus:border-j-accent w-40"
        />
        <div className="flex items-center gap-1">
          {(['all', 'webhook', 'batch_csv', 'batch_json', 'api_pull'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setTypeFilter(s)}
              className={`font-mono text-[10px] tracking-[0.08em] uppercase px-2.5 py-1.5 rounded border transition-colors
                ${typeFilter === s
                  ? 'border-j-accent text-j-accent bg-j-surface2'
                  : 'border-j-border text-j-dim hover:border-j-accent hover:text-j-accent'
                }`}
            >
              {s === 'all' ? 'all' : s.replace('_', ' ')}
            </button>
          ))}
        </div>
        {collectionFilter && (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-j-accent border border-j-accent bg-j-accent-dim rounded px-2 py-1">
            ◧ {collectionFilter}
            <button onClick={() => setSearchParams({})} className="hover:text-j-bright">✕</button>
          </span>
        )}
        <button
          onClick={() => refetch()}
          className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors"
        >
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

      {/* Import Guide */}
      <div className="mb-5 px-4 py-3 rounded border border-j-border bg-j-surface2 font-mono text-[11px] text-j-dim">
        <span className="text-j-accent font-semibold">How to import data</span>
        <span className="mx-2 text-j-border">|</span>
        <span>1. Create a connector</span>
        <span className="mx-1.5 opacity-40">→</span>
        <span>2. Webhook: copy the URL and POST JSON · Batch: click Upload · API Pull: click Pull</span>
        <span className="mx-1.5 opacity-40">→</span>
        <span>3. Check Runs to verify rows landed</span>
        <span className="mx-1.5 opacity-40">→</span>
        <span>4. Ask Jonas to draft a transform to silver/gold</span>
      </div>

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading connectors…</p>}
      {error && (
        <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">
          {error instanceof Error ? error.message : 'error'}
        </div>
      )}

      {!isLoading && !error && !filteredConnectors.length && (
        <div className="text-center py-16">
          <p className="font-mono text-[11px] text-j-dim mb-3">
            {typeFilter !== 'all' ? `no ${typeFilter.replace('_', ' ')} connectors` : 'no connectors yet'}
          </p>
          {typeFilter === 'all' && (
            <button
              onClick={() => setShowCreate(true)}
              className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-accent border border-j-accent px-4 py-2 rounded hover:bg-j-accent hover:text-j-bg transition-colors"
            >
              + Create your first connector
            </button>
          )}
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        {filteredConnectors.map((c) => (
          <ConnectorCard
            key={c.id}
            connector={c}
            canWrite={canWrite}
            canApprove={canApprove}
            canAdmin={canAdmin}
            onUpload={() => setUploadTarget(c)}
            onRuns={() => setRunsTarget(c.id)}
            onEdit={() => setEditTarget(c)}
            onDelete={() => handleDelete(c.id, c.name)}
            onTrigger={() => triggerMutation.mutate(c.id)}
          />
        ))}
      </div>

      {/* Modals */}
      {showCreate && <CreateModal onClose={() => setShowCreate(false)} />}
      {editTarget && <EditConnectorModal connector={editTarget} onClose={() => setEditTarget(null)} />}
      {uploadTarget && <UploadModal connector={uploadTarget} onClose={() => setUploadTarget(null)} />}
      {runsTarget && <RunHistory connectorId={runsTarget} onClose={() => setRunsTarget(null)} />}
    </div>
  )
}
