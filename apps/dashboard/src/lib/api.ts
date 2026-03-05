// ── Auth helpers ──────────────────────────────────────────────────────────────

const TOKEN_KEY = 'jonas_token'
const DEFAULT_TOKEN = 'admin-token'

export const DEMO_TOKENS = [
  { label: 'Admin',   value: 'admin-token'   },
  { label: 'Analyst', value: 'analyst-token' },
  { label: 'Viewer',  value: 'viewer-token'  },
]

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? DEFAULT_TOKEN
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getRoleFromToken(token: string): string {
  const map: Record<string, string> = {
    'admin-token':   'admin',
    'analyst-token': 'analyst',
    'viewer-token':  'viewer',
  }
  return map[token] ?? 'viewer'
}

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
  source_type: string
  status: string
  config?: string
  last_run_at?: string
  created_at: string
  updated_at: string
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
  status: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

// ── Fetch wrapper ─────────────────────────────────────────────────────────────

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...(init.headers ?? {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  catalogue: {
    list: () => request<Entity[]>('/catalogue/entities'),
    get: (id: string) => request<Entity>(`/catalogue/entities/${id}`),
    getFields: (id: string) => request<EntityField[]>(`/catalogue/entities/${id}/fields`),
    preview: (id: string) => request<PreviewResult>(`/catalogue/entities/${id}/preview`),
  },

  integrations: {
    list: () => request<Integration[]>('/integrations'),
  },

  transforms: {
    list: () => request<Transform[]>('/transforms'),
    get: (id: string) => request<Transform>(`/transforms/${id}`),
    approve: (id: string, action: 'approve' | 'reject') =>
      request<Transform>(`/transforms/${id}/approval`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      }),
    execute: (id: string) =>
      request<ExecuteResult>(`/transforms/${id}/execute`, { method: 'POST' }),
    lineage: () => request<{ nodes: LineageNode[]; edges: LineageEdge[] }>('/transforms/lineage/graph'),
  },

  agent: {
    chat: (messages: ChatMessage[]) =>
      request<ChatMessage>('/agent/chat', {
        method: 'POST',
        body: JSON.stringify({ messages }),
      }),

    async *streamChat(messages: ChatMessage[]): AsyncGenerator<{ type: string; text?: string; name?: string; message?: string }> {
      const res = await fetch('/api/agent/chat/stream', {
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
