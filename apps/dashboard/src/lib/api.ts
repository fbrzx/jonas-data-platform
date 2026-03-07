// ── Auth helpers ──────────────────────────────────────────────────────────────

const TOKEN_KEY = 'jonas_token'
const REFRESH_KEY = 'jonas_refresh_token'
const API_BASE_PATH = '/api/v1'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_KEY) ?? ''
}

export function setToken(access: string, refresh?: string): void {
  localStorage.setItem(TOKEN_KEY, access)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  window.dispatchEvent(new Event('jonas_token_changed'))
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  window.dispatchEvent(new Event('jonas_token_changed'))
}

export function isLoggedIn(): boolean {
  return !!localStorage.getItem(TOKEN_KEY)
}

/** Decode role from JWT payload (base64url). Falls back to 'viewer'. */
export function getRoleFromToken(token: string): string {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return payload.role ?? 'viewer'
  } catch {
    // demo tokens
    const map: Record<string, string> = {
      'owner-token': 'owner', 'admin-token': 'admin', 'engineer-token': 'engineer',
      'analyst-token': 'analyst', 'viewer-token': 'viewer',
    }
    return map[token] ?? 'viewer'
  }
}

// Keep for backward compat
export const DEMO_TOKENS = [
  { label: 'Admin',   value: 'admin-token'   },
  { label: 'Analyst', value: 'analyst-token' },
  { label: 'Viewer',  value: 'viewer-token'  },
]

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Entity {
  id: string
  tenant_id: string
  name: string
  layer: string
  description?: string
  namespace?: string
  tags?: string
  created_at: string
  updated_at: string
}

export interface EntityField {
  id: string
  entity_id: string
  name: string
  data_type: string
  nullable: boolean
  is_pii: boolean
  ordinal: number
  description?: string
  sample_values?: string
}

export interface PreviewResult {
  columns: string[]
  rows: Record<string, unknown>[]
  count: number
  pii_masked: boolean
  pii_fields: string[]
  error?: string
}

export interface Integration {
  id: string
  tenant_id: string
  name: string
  description?: string
  connector_type: string
  status: string
  config?: string
  target_entity_id?: string | null
  cron_schedule?: string | null
  created_at: string
  updated_at: string
}

export interface IntegrationCreate {
  name: string
  description?: string
  connector_type: 'webhook' | 'batch_csv' | 'batch_json' | 'api_pull'
  config?: Record<string, unknown>
  tags?: string[]
  entity_id?: string
}

export interface IntegrationUpdate {
  name?: string
  description?: string
  status?: 'active' | 'paused'
  config?: Record<string, unknown>
  tags?: string[]
  entity_id?: string | null
  cron_schedule?: string | null
}

export interface AuditJob {
  id: string
  job_type: 'connector' | 'transform'
  job_name: string
  sub_type: string
  status: string
  started_at: string
  completed_at?: string
  records_in: number
  records_out: number
  records_rejected: number
  error_detail?: string | null
}

export interface AuditLog {
  id: string
  tenant_id: string
  user_id: string
  action: string
  resource_type: string
  resource_id?: string
  detail?: string
  created_at: string
}

export interface TransformCreate {
  name: string
  description?: string
  source_layer: string
  target_layer: string
  sql: string
  tags?: string[]
}

export interface TransformUpdate {
  name?: string
  description?: string
  sql?: string
  source_layer?: string
  target_layer?: string
  tags?: string[]
}

export interface FieldUpdate {
  data_type?: string
  nullable?: boolean
  is_pii?: boolean
  description?: string
}

export interface EntityCreate {
  name: string
  description?: string
  layer?: string
  tags?: string[]
}

export interface EntityUpdate {
  name?: string
  description?: string
  tags?: string[]
}

export interface IngestResponse {
  rows_received: number
  rows_landed: number
  target_table: string
  errors: string[]
  run_id?: string
}

export interface IntegrationRun {
  id: string
  integration_id: string
  status: 'running' | 'success' | 'partial' | 'failed'
  started_at: string
  completed_at?: string
  records_in: number
  records_out: number
  records_rejected: number
  error_detail?: Record<string, unknown>
}

export interface Transform {
  id: string
  tenant_id: string
  name: string
  description?: string
  source_layer: string
  target_layer: string
  transform_sql?: string
  status: string
  created_by?: string
  approved_by?: string
  created_at: string
  updated_at: string
}

export interface ExecuteResult {
  transform_id: string
  target_table: string
  rows_affected: number
  duration_ms: number
  errors: string[]
}

export interface LineageNode {
  id: string
  name: string
  layer: string
  description?: string
  tags?: string
}

export interface LineageEdge {
  id: string
  name: string
  source_layer: string
  target_layer: string
  source_entity_id?: string
  target_entity_id?: string
  status: string
  sql?: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface TenantConfig {
  llm_provider: string
  llm_model: string
  pii_masking_enabled: boolean
  data_retention_days: number
  max_connector_runs_per_day: number
}

export interface TenantUser {
  id: string
  email: string
  display_name: string
  role: string
  granted_at: string
  revoked_at: string | null
}

export interface TenantUserCreate {
  email: string
  display_name: string
  password: string
  role: string
}

export interface InviteCreate {
  email: string
  role: string
}

export interface InviteResponse {
  invite_id: string
  email: string
  role: string
  expires_at: string
  invite_link: string
}

export interface AuditDayCount {
  day: string
  total: number
  success: number
  error: number
}

export interface AuditStats {
  days: number
  connector_daily: AuditDayCount[]
  transform_daily: AuditDayCount[]
  totals: {
    total_connectors: number
    total_transforms: number
    total_connector_runs: number
    total_transform_runs: number
  }
}

// ── Fetch wrapper ─────────────────────────────────────────────────────────────

let _refreshing: Promise<void> | null = null

async function _tryRefresh(): Promise<void> {
  const refresh = getRefreshToken()
  if (!refresh) { clearTokens(); return }
  try {
    const res = await fetch(`${API_BASE_PATH}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) { clearTokens(); return }
    const data = await res.json() as { access_token: string; refresh_token: string }
    setToken(data.access_token, data.refresh_token)
  } catch {
    clearTokens()
  }
}

async function request<T>(path: string, init: RequestInit = {}, _retry = true): Promise<T> {
  const res = await fetch(`${API_BASE_PATH}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...(init.headers ?? {}),
    },
  })
  if (res.status === 401 && _retry) {
    if (!_refreshing) _refreshing = _tryRefresh().finally(() => { _refreshing = null })
    await _refreshing
    if (!getToken()) throw new Error('Session expired — please log in again')
    return request<T>(path, init, false)
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE_PATH}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: form,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  auth: {
    login: (email: string, password: string) =>
      request<{ access_token: string; refresh_token: string; token_type: string }>(
        '/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }
      ),
    refresh: (refresh_token: string) =>
      request<{ access_token: string; refresh_token: string }>('/auth/refresh', {
        method: 'POST', body: JSON.stringify({ refresh_token }),
      }),
    me: () => request<{ user_id: string; email: string; tenant_id: string; role: string }>('/auth/me'),
    logout: () => { clearTokens() },
    acceptInvite: (token: string, display_name: string, password: string) =>
      request<{ access_token: string; refresh_token: string; token_type: string }>(
        '/auth/accept-invite',
        { method: 'POST', body: JSON.stringify({ token, display_name, password }) }
      ),
  },
  catalogue: {
    list: () => request<Entity[]>('/catalogue/entities'),
    create: (body: EntityCreate) =>
      request<Entity>('/catalogue/entities', { method: 'POST', body: JSON.stringify(body) }),
    get: (id: string) => request<Entity>(`/catalogue/entities/${id}`),
    getFields: (id: string) => request<EntityField[]>(`/catalogue/entities/${id}/fields`),
    preview: (id: string) => request<PreviewResult>(`/catalogue/entities/${id}/preview`),
    update: (id: string, body: EntityUpdate) =>
      request<Entity>(`/catalogue/entities/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    updateField: (entityId: string, fieldId: string, body: FieldUpdate) =>
      request<EntityField>(`/catalogue/entities/${entityId}/fields/${fieldId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      request<void>(`/catalogue/entities/${id}`, { method: 'DELETE' }),
    deleteField: (entityId: string, fieldId: string) =>
      request<void>(`/catalogue/entities/${entityId}/fields/${fieldId}`, { method: 'DELETE' }),
  },

  connectors: {
    list: () => request<Integration[]>('/connectors'),
    create: (body: IntegrationCreate) =>
      request<Integration>('/connectors', { method: 'POST', body: JSON.stringify(body) }),
    update: (id: string, body: IntegrationUpdate) =>
      request<Integration>(`/connectors/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: (id: string) =>
      request<void>(`/connectors/${id}`, { method: 'DELETE' }),
    sendWebhook: (id: string, data: unknown, metadata?: Record<string, unknown>) =>
      request<IngestResponse>(`/connectors/${id}/webhook`, {
        method: 'POST',
        body: JSON.stringify({ data, metadata: metadata ?? {} }),
      }),
    uploadBatch: (id: string, file: File) =>
      upload<IngestResponse>(`/connectors/${id}/batch`, file),
    getRuns: (id: string) =>
      request<IntegrationRun[]>(`/connectors/${id}/runs`),
    trigger: (id: string) =>
      request<IngestResponse>(`/connectors/${id}/trigger`, { method: 'POST' }),
  },
  // Legacy alias — keep IntegrationsPage working during transition
  integrations: {
    list: () => request<Integration[]>('/connectors'),
    create: (body: IntegrationCreate) =>
      request<Integration>('/connectors', { method: 'POST', body: JSON.stringify(body) }),
    update: (id: string, body: IntegrationUpdate) =>
      request<Integration>(`/connectors/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: (id: string) =>
      request<void>(`/connectors/${id}`, { method: 'DELETE' }),
    sendWebhook: (id: string, data: unknown, metadata?: Record<string, unknown>) =>
      request<IngestResponse>(`/connectors/${id}/webhook`, {
        method: 'POST',
        body: JSON.stringify({ data, metadata: metadata ?? {} }),
      }),
    uploadBatch: (id: string, file: File) =>
      upload<IngestResponse>(`/connectors/${id}/batch`, file),
    getRuns: (id: string) =>
      request<IntegrationRun[]>(`/connectors/${id}/runs`),
    trigger: (id: string) =>
      request<IngestResponse>(`/connectors/${id}/trigger`, { method: 'POST' }),
  },

  transforms: {
    list: () => request<Transform[]>('/transforms'),
    get: (id: string) => request<Transform>(`/transforms/${id}`),
    create: (body: TransformCreate) =>
      request<Transform>('/transforms', { method: 'POST', body: JSON.stringify(body) }),
    update: (id: string, body: TransformUpdate) =>
      request<Transform>(`/transforms/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    approve: (id: string, action: 'approve' | 'reject') =>
      request<Transform>(`/transforms/${id}/approval`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      }),
    execute: (id: string) =>
      request<ExecuteResult>(`/transforms/${id}/execute`, { method: 'POST' }),
    delete: (id: string) =>
      request<void>(`/transforms/${id}`, { method: 'DELETE' }),
    lineage: () => request<{ nodes: LineageNode[]; edges: LineageEdge[] }>('/transforms/lineage/graph'),
  },

  audit: {
    jobs: (page = 1, pageSize = 50) =>
      request<{ jobs: AuditJob[]; total: number; page: number; page_size: number }>(
        `/audit/jobs?page=${page}&page_size=${pageSize}`
      ),
    logs: (page = 1, pageSize = 50, action?: string, entityType?: string) => {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (action) params.set('action', action)
      if (entityType) params.set('entity_type', entityType)
      return request<{ logs: AuditLog[]; total: number; page: number; page_size: number }>(
        `/audit/logs?${params}`
      )
    },
    stats: (days = 14) =>
      request<AuditStats>(`/audit/stats?days=${days}`),
  },

  tenant: {
    getConfig: () => request<TenantConfig>('/tenant/config'),
    updateConfig: (body: Partial<TenantConfig>) =>
      request<TenantConfig>('/tenant/config', { method: 'PATCH', body: JSON.stringify(body) }),
    listUsers: () => request<TenantUser[]>('/tenant/users'),
    createUser: (body: TenantUserCreate) =>
      request<TenantUser>('/tenant/users', { method: 'POST', body: JSON.stringify(body) }),
    inviteUser: (body: InviteCreate) =>
      request<InviteResponse>('/tenant/users/invite', { method: 'POST', body: JSON.stringify(body) }),
    changeRole: (userId: string, role: string) =>
      request<{ user_id: string; role: string }>(`/tenant/users/${userId}/role`, {
        method: 'PATCH',
        body: JSON.stringify({ role }),
      }),
    revokeUser: (userId: string) =>
      request<void>(`/tenant/users/${userId}`, { method: 'DELETE' }),
  },

  agent: {
    chat: (messages: ChatMessage[]) =>
      request<ChatMessage>('/agent/chat', {
        method: 'POST',
        body: JSON.stringify({ messages }),
      }),

    async *streamChat(messages: ChatMessage[]): AsyncGenerator<{ type: string; text?: string; name?: string; message?: string }> {
      const res = await fetch(`${API_BASE_PATH}/agent/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({ messages }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText)
        throw new Error(text || `HTTP ${res.status}`)
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              yield JSON.parse(line.slice(6)) as { type: string; text?: string; name?: string; message?: string }
            } catch { /* skip malformed lines */ }
          }
        }
      }
    },
  },
}
