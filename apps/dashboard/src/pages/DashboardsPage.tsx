import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import * as Plot from '@observablehq/plot'
import * as Inputs from '@observablehq/inputs'
import { api, type Dashboard, type DashboardDetail } from '../lib/api'

type PanelMode = 'edit' | 'preview'
type Selection = { kind: 'dashboard'; slug: string } | { kind: 'config' }

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KB`
}

// ── Markdown parser ───────────────────────────────────────────────────────────

type Block =
  | { kind: 'h1' | 'h2' | 'h3'; text: string }
  | { kind: 'code'; lang: string; body: string }
  | { kind: 'p'; text: string }
  | { kind: 'hr' }

function parseMd(raw: string): Block[] {
  const lines = raw.split('\n')
  const blocks: Block[] = []
  let i = 0

  // Strip YAML frontmatter
  if (lines[0]?.trim() === '---') {
    i = 1
    while (i < lines.length && lines[i]?.trim() !== '---') i++
    i++
  }

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    if (line.match(/^```/)) {
      const lang = line.slice(3).trim()
      const bodyLines: string[] = []
      i++
      while (i < lines.length && !lines[i].match(/^```\s*$/)) {
        bodyLines.push(lines[i])
        i++
      }
      i++
      blocks.push({ kind: 'code', lang, body: bodyLines.join('\n') })
      continue
    }

    // HTML comments — skip
    if (line.trim().startsWith('<!--')) {
      while (i < lines.length && !lines[i].includes('-->')) i++
      i++
      continue
    }

    const h3 = line.match(/^###\s+(.+)/)
    if (h3) { blocks.push({ kind: 'h3', text: h3[1] }); i++; continue }
    const h2 = line.match(/^##\s+(.+)/)
    if (h2) { blocks.push({ kind: 'h2', text: h2[1] }); i++; continue }
    const h1 = line.match(/^#\s+(.+)/)
    if (h1) { blocks.push({ kind: 'h1', text: h1[1] }); i++; continue }

    if (line.match(/^---+\s*$/)) { blocks.push({ kind: 'hr' }); i++; continue }

    if (line.trim()) {
      const textLines = [line]
      i++
      while (i < lines.length && lines[i].trim() && !lines[i].match(/^[#`<-]/)) {
        textLines.push(lines[i])
        i++
      }
      blocks.push({ kind: 'p', text: textLines.join(' ') })
      continue
    }

    i++
  }
  return blocks
}

function inlineCode(text: string): string {
  return text.replace(/`([^`]+)`/g, (_, c) =>
    `<code class="font-mono text-j-accent bg-j-surface2 px-1 rounded text-[11px]">${c}</code>`
  )
}

// ── JS block classifier ───────────────────────────────────────────────────────

// Statement-level keywords that make a block non-renderable as an expression
const STMT_RE = /^(const|let|var|function|class|async\s+function|\/\/)/m

type JsBlock =
  | { kind: 'import' }
  | { kind: 'setup' }                                                       // declarations — hidden in preview
  | { kind: 'data'; varName: string; layer: string; entityName: string }
  | { kind: 'chart'; code: string }

function classifyJsBlock(body: string): JsBlock {
  const raw = body.trim()
  if (raw.startsWith('import ')) return { kind: 'import' }

  const dataMatch = raw.match(
    /const\s+(\w+)\s*=\s*await\s+jonasPreview\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']/
  )
  if (dataMatch) {
    return { kind: 'data', varName: dataMatch[1], layer: dataMatch[2], entityName: dataMatch[3] }
  }

  // Any block that starts with a declaration keyword is a setup block, not an expression
  if (STMT_RE.test(raw.split('\n')[0])) return { kind: 'setup' }

  return { kind: 'chart', code: raw }
}

// ── Live chart cell ───────────────────────────────────────────────────────────

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor as new (
  ...args: string[]
) => (...args: unknown[]) => Promise<unknown>

function LiveChart({
  code,
  scope,
}: {
  code: string
  scope: Record<string, unknown>
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ref.current) return
    setError(null)

    const paramNames = ['Plot', 'Inputs', ...Object.keys(scope)]
    const paramValues = [Plot, Inputs, ...Object.values(scope)]

    // Treat the entire block as an expression — wrap in return so the chart element comes back.
    // Use a do-expression wrapper so multi-line Plot.plot({...}) works regardless of trailing `;`.
    const trimmed = code.trim().replace(/;$/, '')
    const fn = new AsyncFunction(...paramNames, `return (${trimmed})`)
    let cancelled = false

    fn(...paramValues)
      .then((result) => {
        if (cancelled || !ref.current) return
        ref.current.innerHTML = ''
        if (result instanceof Element) {
          ref.current.appendChild(result)
        } else if (result !== null && result !== undefined) {
          ref.current.textContent = String(result)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })

    return () => { cancelled = true }
  }, [code, scope])

  if (error) {
    return (
      <div className="my-3 p-3 rounded border border-j-red bg-j-red-dim">
        <p className="font-mono text-[10px] text-j-red">Chart error: {error}</p>
        <pre className="mt-2 font-mono text-[10px] text-j-dim whitespace-pre-wrap opacity-70">{code}</pre>
      </div>
    )
  }

  return <div ref={ref} className="my-3 overflow-x-auto" />
}

// ── Markdown preview (live) ───────────────────────────────────────────────────

function MarkdownPreview({ content }: { content: string }) {
  const blocks = useMemo(() => parseMd(content), [content])

  // Collect entity loaders needed
  const loaders = useMemo<{ varName: string; layer: string; entityName: string }[]>(() => {
    const result: { varName: string; layer: string; entityName: string }[] = []
    for (const block of blocks) {
      if (block.kind !== 'code' || block.lang !== 'js') continue
      const cls = classifyJsBlock(block.body)
      if (cls.kind === 'data') result.push(cls)
    }
    return result
  }, [blocks])

  // Fetch catalogue to resolve entity IDs
  const { data: allEntities = [] } = useQuery({
    queryKey: ['entities-for-preview'],
    queryFn: api.catalogue.list,
    staleTime: 60_000,
  })

  // Fetch preview data for each entity in parallel
  const previewQueries = useQueries({
    queries: loaders.map((loader) => {
      const entity = allEntities.find(
        (e) => e.name === loader.entityName && e.layer === loader.layer
      )
      return {
        queryKey: ['entity-preview', entity?.id ?? `${loader.layer}.${loader.entityName}`],
        queryFn: () => (entity ? api.catalogue.preview(entity.id) : Promise.resolve({ rows: [] })),
        enabled: allEntities.length > 0,
        staleTime: 60_000,
      }
    }),
  })

  // Build scope: varName → rows[]
  const scope = useMemo<Record<string, unknown>>(() => {
    const s: Record<string, unknown> = {}
    loaders.forEach((loader, idx) => {
      const rows = previewQueries[idx]?.data?.rows ?? []
      s[loader.varName] = rows
    })
    return s
  }, [loaders, previewQueries])

  const allLoaded = previewQueries.every((q) => !q.isLoading)

  return (
    <div className="flex-1 overflow-y-auto px-10 py-8 bg-j-bg">
      <div className="max-w-3xl mx-auto">
        {blocks.map((block, idx) => {
          if (block.kind === 'h1') return (
            <h1 key={idx} className="font-mono text-xl font-semibold text-j-bright mt-6 mb-3 pb-2 border-b border-j-border">
              {block.text}
            </h1>
          )
          if (block.kind === 'h2') return (
            <h2 key={idx} className="font-mono text-base font-semibold text-j-text mt-6 mb-2">
              {block.text}
            </h2>
          )
          if (block.kind === 'h3') return (
            <h3 key={idx} className="font-mono text-[13px] font-semibold text-j-dim uppercase tracking-wider mt-5 mb-2">
              {block.text}
            </h3>
          )
          if (block.kind === 'p') return (
            <p
              key={idx}
              className="font-mono text-[12px] text-j-dim leading-relaxed my-2"
              dangerouslySetInnerHTML={{ __html: inlineCode(block.text) }}
            />
          )
          if (block.kind === 'hr') return <hr key={idx} className="border-j-border my-6" />

          // Code blocks
          if (block.kind === 'code' && block.lang === 'js') {
            const cls = classifyJsBlock(block.body)

            if (cls.kind === 'import') return null  // hidden — injected from jonas.config.js
            if (cls.kind === 'setup') return null   // declarations hidden in preview

            if (cls.kind === 'data') {
              const rows = (scope[cls.varName] as unknown[] | undefined)?.length ?? 0
              return (
                <div key={idx} className="my-2 flex items-center gap-2 font-mono text-[10px] text-j-border">
                  <span className={`w-1.5 h-1.5 rounded-full ${allLoaded ? 'bg-j-green' : 'bg-j-yellow animate-pulse'}`} />
                  {allLoaded
                    ? <span><span className="text-j-accent">{cls.varName}</span> — {rows} rows from {cls.layer}.{cls.entityName}</span>
                    : <span>loading {cls.layer}.{cls.entityName}…</span>
                  }
                </div>
              )
            }

            // Chart block — live render
            if (cls.kind === 'chart') {
              return allLoaded
                ? <LiveChart key={idx} code={cls.code} scope={scope} />
                : (
                  <div key={idx} className="my-3 h-32 rounded border border-j-border flex items-center justify-center">
                    <span className="font-mono text-[10px] text-j-dim animate-pulse">rendering…</span>
                  </div>
                )
            }
          }

          // Non-js code blocks — show as styled code
          if (block.kind === 'code') return (
            <div key={idx} className="my-3 rounded border border-j-border overflow-hidden">
              {block.lang && (
                <div className="px-3 py-1 bg-j-surface border-b border-j-border">
                  <span className="font-mono text-[10px] text-j-dim bg-j-surface2 border border-j-border px-1.5 py-0.5 rounded">
                    {block.lang}
                  </span>
                </div>
              )}
              <pre className="flex bg-j-bg overflow-x-auto">
                <span className="select-none text-right font-mono text-[11px] leading-relaxed text-j-border shrink-0 px-3 py-4 border-r border-j-border/30 whitespace-pre">
                  {block.body.split('\n').map((_, i) => i + 1).join('\n')}
                </span>
                <code className="font-mono text-[11px] leading-relaxed text-j-text whitespace-pre pl-4 py-4 flex-1">{block.body}</code>
              </pre>
            </div>
          )

          return null
        })}
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
      <div className="text-4xl opacity-20 select-none">▦</div>
      <p className="font-mono text-j-dim text-xs max-w-sm leading-relaxed">
        No dashboards yet. Ask Jonas in the chat to create one:
      </p>
      <div className="font-mono text-[11px] text-j-accent bg-j-surface2 border border-j-border rounded px-4 py-2 text-left leading-relaxed">
        "Create a dashboard for the orders silver entity<br />
        with a revenue line chart and a status bar chart"
      </div>
      <p className="font-mono text-[10px] text-j-border">
        Dashboards are Observable Framework .md files — edit here, run locally.
      </p>
    </div>
  )
}

// ── Dashboard list panel ──────────────────────────────────────────────────────

function DashboardList({
  dashboards,
  selection,
  onSelect,
}: {
  dashboards: Dashboard[]
  selection: Selection | null
  onSelect: (s: Selection) => void
}) {
  const configActive = selection?.kind === 'config'
  return (
    <ul className="flex-1 overflow-y-auto">
      {/* Config entry — pinned at top */}
      <li>
        <button
          onClick={() => onSelect({ kind: 'config' })}
          className={`w-full text-left px-4 py-2.5 border-b border-j-border transition-colors
            ${configActive
              ? 'bg-j-surface2 border-l-2 border-l-j-dim'
              : 'hover:bg-j-surface border-l-2 border-l-transparent'
            }`}
        >
          <p className={`font-mono text-[10px] font-medium ${configActive ? 'text-j-text' : 'text-j-dim'}`}>
            ⚙ api config
          </p>
          <p className="font-mono text-[9px] text-j-border mt-0.5">jonas.config.js</p>
        </button>
      </li>

      {dashboards.map((d) => {
        const active = selection?.kind === 'dashboard' && selection.slug === d.slug
        return (
          <li key={d.slug}>
            <button
              onClick={() => onSelect({ kind: 'dashboard', slug: d.slug })}
              className={`w-full text-left px-4 py-3 border-b border-j-border transition-colors
                ${active
                  ? 'bg-j-accent-dim border-l-2 border-l-j-accent'
                  : 'hover:bg-j-surface border-l-2 border-l-transparent'
                }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className={`font-mono text-[11px] font-medium truncate ${active ? 'text-j-accent' : 'text-j-text'}`}>
                    {d.title}
                  </p>
                  <p className="font-mono text-[10px] text-j-dim mt-0.5 truncate">{d.slug}.md</p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="font-mono text-[9px] text-j-border">{relativeTime(d.updated_at)}</span>
                  <span className="font-mono text-[9px] text-j-border">{formatBytes(d.size_bytes)}</span>
                </div>
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

// ── Config editor ─────────────────────────────────────────────────────────────

function ConfigEditor({ onSave, saving }: { onSave: (c: string) => void; saving: boolean }) {
  const gutterRef = useRef<HTMLDivElement>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard-config'],
    queryFn: api.dashboards.getConfig,
  })
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (data?.content !== undefined) {
      setContent(data.content)
      setDirty(false)
    }
  }, [data?.content])

  function handleSave() { onSave(content); setDirty(false) }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); if (dirty) handleSave() }
    },
    [dirty, content], // eslint-disable-line react-hooks/exhaustive-deps
  )

  if (isLoading) return (
    <div className="flex-1 flex items-center justify-center">
      <span className="font-mono text-[10px] text-j-dim animate-pulse">loading…</span>
    </div>
  )

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0">
      <div className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-j-border bg-j-surface">
        <span className="font-mono text-[11px] text-j-text font-medium flex-1">
          jonas.config.js
          <span className="ml-2 text-j-dim font-normal text-[10px]">shared API config for all dashboards</span>
          {dirty && <span className="ml-2 text-j-yellow">●</span>}
        </span>
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="px-3 py-1 font-mono text-[10px] tracking-wider uppercase border rounded transition-colors
            border-j-dim text-j-dim hover:bg-j-surface2
            disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {saving ? 'saving…' : 'save'}
        </button>
      </div>
      <div className="shrink-0 px-4 py-1.5 bg-j-surface2 border-b border-j-border">
        <span className="font-mono text-[10px] text-j-dim">
          Edit <code className="text-j-text">_API</code> to change the endpoint — all dashboards inherit it. Not stored in .md files. ⌘S to save.
        </span>
      </div>
      <div className="flex flex-1 overflow-hidden">
        <div
          ref={gutterRef}
          aria-hidden="true"
          className="select-none text-right font-mono text-[12px] leading-relaxed text-j-border/50 bg-j-bg border-r border-j-border/30 overflow-hidden shrink-0 px-3 py-4"
        >
          {content.split('\n').map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        <textarea
          value={content}
          onChange={(e) => { setContent(e.target.value); setDirty(e.target.value !== data?.content) }}
          onKeyDown={handleKeyDown}
          onScroll={(e) => { if (gutterRef.current) gutterRef.current.scrollTop = e.currentTarget.scrollTop }}
          spellCheck={false}
          className="flex-1 resize-none bg-j-bg text-j-text font-mono text-[12px] leading-relaxed
            pl-4 pr-4 py-4 border-0 outline-none focus:outline-none selection:bg-j-accent-dim"
          style={{ tabSize: 2 }}
        />
      </div>
    </div>
  )
}

// ── Editor + Preview panel ────────────────────────────────────────────────────

function EditorPanel({
  detail,
  onSave,
  saving,
  onDelete,
}: {
  detail: DashboardDetail
  onSave: (content: string) => void
  saving: boolean
  onDelete: () => void
}) {
  const gutterRef = useRef<HTMLDivElement>(null)
  const [content, setContent] = useState(detail.content)
  const [dirty, setDirty] = useState(false)
  const [mode, setMode] = useState<PanelMode>('preview')

  useEffect(() => {
    setContent(detail.content)
    setDirty(false)
  }, [detail.slug, detail.content])

  function handleChange(v: string) {
    setContent(v)
    setDirty(v !== detail.content)
  }

  function handleSave() {
    onSave(content)
    setDirty(false)
  }

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (dirty) handleSave()
      }
    },
    [dirty, content], // eslint-disable-line react-hooks/exhaustive-deps
  )

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0">
      {/* Toolbar */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-2 border-b border-j-border bg-j-surface">
        <span className="font-mono text-[11px] text-j-bright font-medium truncate flex-1 min-w-0">
          {detail.title}
          <span className="ml-2 text-j-dim font-normal">{detail.slug}.md</span>
          {dirty && <span className="ml-2 text-j-yellow">●</span>}
        </span>

        {/* Edit / Preview toggle */}
        <div className="flex items-center shrink-0 border border-j-border rounded overflow-hidden">
          {(['edit', 'preview'] as PanelMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 font-mono text-[10px] tracking-wider uppercase transition-colors
                ${mode === m
                  ? 'bg-j-accent-dim text-j-accent'
                  : 'text-j-dim hover:text-j-text hover:bg-j-surface2'
                }`}
            >
              {m}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <a
            href="https://observablehq.com/framework/getting-started"
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-[10px] text-j-border hover:text-j-accent transition-colors"
            title="Observable Framework docs"
          >
            obs ↗
          </a>
          <button
            onClick={() => { if (confirm(`Delete "${detail.title}"?`)) onDelete() }}
            className="font-mono text-[10px] text-j-dim hover:text-j-red transition-colors px-2 py-1"
          >
            delete
          </button>
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="px-3 py-1 font-mono text-[10px] tracking-wider uppercase border rounded transition-colors
              border-j-accent text-j-accent hover:bg-j-accent-dim
              disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {saving ? 'saving…' : 'save'}
          </button>
        </div>
      </div>

      {/* Hint bar */}
      {mode === 'edit' ? (
        <div className="shrink-0 px-4 py-1.5 bg-j-surface2 border-b border-j-border flex items-center gap-2">
          <span className="font-mono text-[10px] text-j-dim">Run locally:</span>
          <code className="font-mono text-[10px] text-j-accent bg-j-bg px-2 py-0.5 rounded">
            npm i -g @observablehq/framework &amp;&amp; observable preview
          </code>
          <span className="font-mono text-[10px] text-j-border ml-auto">⌘S to save</span>
        </div>
      ) : (
        <div className="shrink-0 px-4 py-1.5 bg-j-surface2 border-b border-j-border flex items-center gap-2">
          <span className="font-mono text-[10px] text-j-border">
            Live preview — charts rendered with Observable Plot, data fetched from the API
          </span>
        </div>
      )}

      {/* Content */}
      {mode === 'edit' ? (
        <div className="flex flex-1 overflow-hidden">
          <div
            ref={gutterRef}
            aria-hidden="true"
            className="select-none text-right font-mono text-[12px] leading-relaxed text-j-border/50 bg-j-bg border-r border-j-border/30 overflow-hidden shrink-0 px-3 py-4"
          >
            {content.split('\n').map((_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <textarea
            value={content}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onScroll={(e) => { if (gutterRef.current) gutterRef.current.scrollTop = e.currentTarget.scrollTop }}
            spellCheck={false}
            className="flex-1 resize-none bg-j-bg text-j-text font-mono text-[12px] leading-relaxed
              pl-4 pr-4 py-4 border-0 outline-none focus:outline-none selection:bg-j-accent-dim"
            style={{ tabSize: 2 }}
          />
        </div>
      ) : (
        <MarkdownPreview content={content} />
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DashboardsPage() {
  const queryClient = useQueryClient()
  const [selection, setSelection] = useState<Selection | null>(null)

  const { data: dashboards = [], isLoading } = useQuery({
    queryKey: ['dashboards'],
    queryFn: api.dashboards.list,
  })

  const selectedSlug = selection?.kind === 'dashboard' ? selection.slug : null

  const { data: detail, isLoading: loadingDetail } = useQuery({
    queryKey: ['dashboard', selectedSlug],
    queryFn: () => api.dashboards.get(selectedSlug!),
    enabled: !!selectedSlug,
  })

  useEffect(() => {
    if (!selection && dashboards.length > 0) {
      setSelection({ kind: 'dashboard', slug: dashboards[0].slug })
    }
  }, [dashboards, selection])

  const saveMutation = useMutation({
    mutationFn: ({ slug, content }: { slug: string; content: string }) =>
      api.dashboards.save(slug, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', selectedSlug] })
    },
  })

  const saveConfigMutation = useMutation({
    mutationFn: (content: string) => api.dashboards.saveConfig(content),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard-config'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => api.dashboards.delete(slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      setSelection(null)
    },
  })

  function renderMain() {
    if (selection?.kind === 'config') {
      return (
        <ConfigEditor
          onSave={(c) => saveConfigMutation.mutate(c)}
          saving={saveConfigMutation.isPending}
        />
      )
    }
    if (!dashboards.length && !isLoading) return <EmptyState />
    if (!selection) return (
      <div className="flex-1 flex items-center justify-center">
        <p className="font-mono text-[11px] text-j-dim">Select a dashboard</p>
      </div>
    )
    if (loadingDetail || !detail) return (
      <div className="flex-1 flex items-center justify-center">
        <span className="font-mono text-[10px] text-j-dim animate-pulse">loading…</span>
      </div>
    )
    return (
      <EditorPanel
        detail={detail}
        onSave={(content) => saveMutation.mutate({ slug: detail.slug, content })}
        saving={saveMutation.isPending}
        onDelete={() => deleteMutation.mutate(detail.slug)}
      />
    )
  }

  return (
    <div className="flex-1 flex overflow-hidden">
      <aside className="w-56 shrink-0 flex flex-col border-r border-j-border bg-j-surface overflow-hidden">
        <div className="shrink-0 h-9 flex items-center px-4 border-b border-j-border">
          <span className="font-mono text-[10px] text-j-dim uppercase tracking-wider">Dashboards</span>
          <span className="ml-auto font-mono text-[10px] text-j-border">{dashboards.length}</span>
        </div>
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <span className="font-mono text-[10px] text-j-dim animate-pulse">loading…</span>
          </div>
        ) : (
          <DashboardList
            dashboards={dashboards}
            selection={selection}
            onSelect={setSelection}
          />
        )}
      </aside>
      {renderMain()}
    </div>
  )
}
