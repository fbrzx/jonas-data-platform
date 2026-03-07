import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type LineageNode, type LineageEdge } from '../lib/api'
import PageHeader from '../components/PageHeader'

// ── Layer config ───────────────────────────────────────────────────────────────

const LAYER = {
  bronze: { label: 'Bronze', dot: 'bg-j-amber',  text: 'text-j-amber',  border: 'border-j-amber'  },
  silver: { label: 'Silver', dot: 'bg-j-accent', text: 'text-j-accent', border: 'border-j-accent' },
  gold:   { label: 'Gold',   dot: 'bg-j-bright', text: 'text-j-bright', border: 'border-j-bright' },
} as const

type LayerKey = keyof typeof LAYER
const LAYERS: LayerKey[] = ['bronze', 'silver', 'gold']

// Edge stroke colours by layer pair
const EDGE_COLOR: Record<string, string> = {
  'bronze-silver': '#f59e0b',
  'silver-gold':   '#6366f1',
  'bronze-gold':   '#22c55e',
}

const STATUS_TEXT: Record<string, string> = {
  approved: 'text-j-green',
  draft:    'text-j-dim',
  rejected: 'text-j-red',
}

// ── Types ──────────────────────────────────────────────────────────────────────

interface PathInfo {
  d: string
  midX: number
  midY: number
  edge: LineageEdge
  color: string
}

// ── NodeCard ───────────────────────────────────────────────────────────────────

function NodeCard({
  node,
  selected,
  dimmed,
}: {
  node: LineageNode
  selected: boolean
  dimmed: boolean
}) {
  const cfg = LAYER[node.layer as LayerKey] ?? LAYER.bronze
  let tags: string[] = []
  try { tags = JSON.parse(node.tags ?? '[]') } catch { /**/ }

  return (
    <div
      className={`
        border rounded px-2.5 py-2 w-full transition-all duration-150 select-none
        ${selected
          ? `${cfg.border} bg-j-surface2 ring-1 ring-inset ${cfg.border}`
          : dimmed
          ? 'border-j-border bg-j-surface'
          : 'border-j-border bg-j-surface hover:border-j-accent hover:bg-j-surface2'
        }
        ${dimmed ? 'opacity-25' : 'opacity-100'}
      `}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
        <span className="font-mono text-[12px] text-j-bright font-medium truncate">{node.name}</span>
      </div>
      {node.description && (
        <p className="font-mono text-[10px] text-j-dim truncate leading-snug mt-0.5">{node.description}</p>
      )}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {tags.map((t) => (
            <span
              key={t}
              className="px-1 py-0.5 font-mono text-[9px] bg-j-surface2 text-j-dim border border-j-border rounded"
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function LineagePage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['lineage'],
    queryFn: api.transforms.lineage,
    staleTime: 30_000,
  })

  const [search,       setSearch]       = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'approved' | 'draft'>('all')
  const [selectedId,   setSelectedId]   = useState<string | null>(null)
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null)
  const [paths,        setPaths]        = useState<PathInfo[]>([])

  const wrapperRef = useRef<HTMLDivElement>(null)
  const nodeEls    = useRef<Map<string, HTMLDivElement>>(new Map())

  const allNodes = data?.nodes ?? []
  const rawEdges = data?.edges ?? []

  // ── Resolve missing entity IDs on edges ──────────────────────────────────
  // Backend resolves from SQL but Docker may not be rebuilt. Parse SQL on the
  // frontend as fallback: FROM/JOIN → source entities, CREATE/INSERT → target.

  const nodesByName = new Map(allNodes.map((n) => [`${n.layer}:${n.name}`, n]))

  function resolveFromSql(sql: string, preferredLayer: string, role: 'source' | 'target'): string | undefined {
    if (!sql) return undefined
    const tables: string[] = []
    if (role === 'target') {
      const m = sql.match(/(?:CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+)(?:\w+\.)?(\w+)/i)
      if (m) tables.push(m[1])
    } else {
      for (const m of sql.matchAll(/\bFROM\s+(?:\w+\.)?(\w+)/gi)) tables.push(m[1])
      for (const m of sql.matchAll(/\bJOIN\s+(?:\w+\.)?(\w+)/gi)) tables.push(m[1])
    }
    const layerOrder = [preferredLayer, ...LAYERS.filter((l) => l !== preferredLayer)]
    for (const t of tables) {
      for (const l of layerOrder) {
        const node = nodesByName.get(`${l}:${t}`)
        if (node) return node.id
      }
    }
    return undefined
  }

  // Resolve all source entity references from SQL (may be multiple FROM/JOIN)
  // For medallion pattern: prefer the layer closest to the target (e.g. silver for gold transforms)
  function resolveAllSources(sql: string, sourceLayer: string, targetLayer: string): string[] {
    if (!sql) return []
    const tables: string[] = []
    for (const m of sql.matchAll(/\bFROM\s+(?:\w+\.)?(\w+)/gi)) tables.push(m[1])
    for (const m of sql.matchAll(/\bJOIN\s+(?:\w+\.)?(\w+)/gi)) {
      if (!tables.includes(m[1])) tables.push(m[1])
    }
    // Order layers: prefer layer just below target, then declared source, then rest
    const srcIdx = LAYERS.indexOf(sourceLayer as LayerKey)
    const tgtIdx = LAYERS.indexOf(targetLayer as LayerKey)
    const intermediates = LAYERS.slice(srcIdx, tgtIdx).reverse()
    const layerOrder = [...new Set([...intermediates, sourceLayer, ...LAYERS.filter((l) => l !== targetLayer)])]
    const ids: string[] = []
    for (const t of tables) {
      for (const l of layerOrder) {
        const node = nodesByName.get(`${l}:${t}`)
        if (node && !ids.includes(node.id)) { ids.push(node.id); break }
      }
    }
    return ids
  }

  // Expand each raw edge into one-or-more edges (one per source entity)
  const allEdges: LineageEdge[] = []
  for (const e of rawEdges) {
    const sql = e.sql ?? ''

    // Resolve target entity
    let target_entity_id = e.target_entity_id
      ?? resolveFromSql(sql, e.target_layer, 'target')
    if (!target_entity_id) {
      const match = allNodes.find(
        (n) => n.layer === e.target_layer && e.name.toLowerCase().includes(n.name.toLowerCase()),
      )
      if (match) target_entity_id = match.id
    }
    if (!target_entity_id) {
      const layerNodes = allNodes.filter((n) => n.layer === e.target_layer)
      if (layerNodes.length === 1) target_entity_id = layerNodes[0].id
    }

    // Resolve all source entities (may be multiple)
    // Always re-resolve from SQL to prefer intermediate layers (e.g. silver for bronze→gold)
    let sourceIds: string[] = resolveAllSources(sql, e.source_layer, e.target_layer)
    if (!sourceIds.length && e.source_entity_id) {
      sourceIds = [e.source_entity_id]
    }
    if (!sourceIds.length) {
      const match = allNodes.find(
        (n) => n.layer === e.source_layer && e.name.toLowerCase().includes(n.name.toLowerCase()),
      )
      if (match) sourceIds = [match.id]
    }
    if (!sourceIds.length) {
      const layerNodes = allNodes.filter((n) => n.layer === e.source_layer)
      if (layerNodes.length === 1) sourceIds = [layerNodes[0].id]
    }

    // Create one edge per source entity (or one with null if unresolved)
    // Use the resolved entity's actual layer for correct edge coloring
    if (sourceIds.length > 0 && target_entity_id) {
      for (const srcId of sourceIds) {
        const srcNode = allNodes.find((n) => n.id === srcId)
        const tgtNode = allNodes.find((n) => n.id === target_entity_id)
        allEdges.push({
          ...e, id: `${e.id}_${srcId}`, source_entity_id: srcId, target_entity_id,
          source_layer: srcNode?.layer ?? e.source_layer,
          target_layer: tgtNode?.layer ?? e.target_layer,
        })
      }
    } else {
      allEdges.push({ ...e, source_entity_id: sourceIds[0], target_entity_id })
    }
  }

  // ── Filtering ──────────────────────────────────────────────────────────────

  const visibleNodeIds = new Set(
    allNodes
      .filter((n) => !search || n.name.toLowerCase().includes(search.toLowerCase()))
      .map((n) => n.id),
  )

  // Edges visible when status matches AND both endpoints are visible
  const visibleEdges = allEdges.filter((e) =>
    (statusFilter === 'all' || e.status === statusFilter) &&
    (!e.source_entity_id || visibleNodeIds.has(e.source_entity_id)) &&
    (!e.target_entity_id || visibleNodeIds.has(e.target_entity_id)),
  )

  // Show all nodes matching search (no further filtering by edge connectivity)
  const visibleNodes = allNodes.filter((n) => visibleNodeIds.has(n.id))

  const nodesByLayer = Object.fromEntries(
    LAYERS.map((l) => [l, visibleNodes.filter((n) => n.layer === l)])
  ) as Record<LayerKey, LineageNode[]>

  // ── Selection / focus ─────────────────────────────────────────────────────
  // Only silver/gold nodes are clickable for tracing. When clicked, trace
  // upstream through edges to find all connected bronze source nodes.

  const selectedNode = selectedId ? visibleNodes.find((n) => n.id === selectedId) : null
  const selectedIsTraced = selectedNode && selectedNode.layer !== 'bronze'

  const connectedNodeIds = selectedIsTraced ? new Set<string>([selectedId!]) : null
  const connectedEdgeIds = selectedIsTraced ? new Set<string>() : null

  if (selectedIsTraced && connectedNodeIds && connectedEdgeIds) {
    // Walk upstream: from the selected node, find edges whose target matches a
    // connected node, then add the source node. Repeat until stable.
    let changed = true
    while (changed) {
      changed = false
      for (const e of visibleEdges) {
        if (!e.source_entity_id || !e.target_entity_id) continue
        // upstream: edge target is in our set → add edge + source
        if (connectedNodeIds.has(e.target_entity_id)) {
          if (!connectedEdgeIds.has(e.id)) { connectedEdgeIds.add(e.id); changed = true }
          if (!connectedNodeIds.has(e.source_entity_id)) {
            connectedNodeIds.add(e.source_entity_id); changed = true
          }
        }
      }
    }
  }

  const isNodeDimmed = (id: string) => selectedIsTraced ? !connectedNodeIds?.has(id) : false
  const isEdgeDimmed = (id: string) => selectedIsTraced ? !connectedEdgeIds?.has(id) : true

  // ── SVG path calculation ───────────────────────────────────────────────────
  //
  // We use offsetLeft / offsetTop (layout coordinates relative to offsetParent)
  // rather than getBoundingClientRect so paths are unaffected by page scroll.

  const calcPaths = useCallback(() => {
    const newPaths: PathInfo[] = []

    for (const edge of visibleEdges) {
      if (!edge.source_entity_id || !edge.target_entity_id) continue
      const srcEl = nodeEls.current.get(edge.source_entity_id)
      const tgtEl = nodeEls.current.get(edge.target_entity_id)
      if (!srcEl || !tgtEl) continue

      const x1 = srcEl.offsetLeft + srcEl.offsetWidth
      const y1 = srcEl.offsetTop  + srcEl.offsetHeight / 2
      const x2 = tgtEl.offsetLeft
      const y2 = tgtEl.offsetTop  + tgtEl.offsetHeight / 2

      const cx = (x1 + x2) / 2
      const d  = `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`
      // Midpoint of cubic bezier at t=0.5 with symmetric control points
      const midX = cx
      const midY = (y1 + y2) / 2

      const colorKey = `${edge.source_layer}-${edge.target_layer}`
      newPaths.push({ d, midX, midY, edge, color: EDGE_COLOR[colorKey] ?? '#64748b' })
    }

    setPaths(newPaths)
  }, [visibleEdges])

  useEffect(() => {
    // rAF ensures DOM has laid out before we measure
    const frame = requestAnimationFrame(calcPaths)
    return () => cancelAnimationFrame(frame)
  }, [calcPaths])

  useEffect(() => {
    window.addEventListener('resize', calcPaths)
    return () => window.removeEventListener('resize', calcPaths)
  }, [calcPaths])

  // ── Hovered edge ──────────────────────────────────────────────────────────

  const hoveredPath = paths.find((p) => p.edge.id === hoveredEdgeId) ?? null

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col flex-1 overflow-auto bg-j-bg p-6">

      {/* ── Header ── */}
      <PageHeader label="Lineage" title="Data Lineage">
        <input
          type="text"
          placeholder="filter entities…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="font-mono text-[11px] bg-j-surface border border-j-border rounded px-2.5 py-1.5 text-j-bright placeholder-j-dim focus:outline-none focus:border-j-accent w-40"
        />
        <div className="flex items-center gap-1">
          {(['all', 'approved', 'draft'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`font-mono text-[10px] tracking-[0.08em] uppercase px-2.5 py-1.5 rounded border transition-colors
                ${statusFilter === s
                  ? 'border-j-accent text-j-accent bg-j-surface2'
                  : 'border-j-border text-j-dim hover:border-j-accent hover:text-j-accent'
                }`}
            >
              {s}
            </button>
          ))}
        </div>
        <button
          onClick={() => refetch()}
          className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors"
        >
          Refresh
        </button>
      </PageHeader>

      {/* ── States ── */}
      {isLoading && (
        <p className="font-mono text-[11px] text-j-dim text-center py-16">loading lineage…</p>
      )}
      {error && (
        <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">
          {error instanceof Error ? error.message : 'error'}
        </div>
      )}

      {!isLoading && !error && (
        <>
          {/* ── Legend + selection hint ── */}
          <div className="flex items-center gap-4 mb-5 px-1 flex-wrap">
            <span className="font-mono text-[10px] text-j-dim uppercase tracking-wider">Legend:</span>
            {LAYERS.map((l) => (
              <div key={l} className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${LAYER[l].dot}`} />
                <span className={`font-mono text-[10px] ${LAYER[l].text}`}>{LAYER[l].label}</span>
              </div>
            ))}
            <span className="font-mono text-[10px] text-j-dim ml-2">
              · click a silver or gold node to trace its pipeline
            </span>
            {selectedId && (
              <button
                onClick={() => setSelectedId(null)}
                className="font-mono text-[9px] text-j-accent border border-j-accent px-2 py-0.5 rounded hover:bg-j-surface2 transition-colors"
              >
                clear ×
              </button>
            )}
          </div>

          {/* ── DAG ── */}
          <div className="overflow-x-auto pb-2">
            {/*
              wrapperRef is position:relative so node offsetLeft/offsetTop are
              relative to it, and the SVG overlay shares the same origin.
            */}
            <div ref={wrapperRef} className="relative" style={{ display: 'inline-flex', minWidth: '100%' }}>

              {/* SVG connection overlay — pointer-events:none on SVG,
                  individual <g> groups re-enable events for hover targets  */}
              <svg
                className="absolute inset-0"
                style={{ width: '100%', height: '100%', overflow: 'visible', pointerEvents: 'none' }}
                aria-hidden="true"
              >
                {paths.map(({ d, midX, midY, edge, color }) => {
                  const dimmed  = isEdgeDimmed(edge.id)
                  const hovered = hoveredEdgeId === edge.id
                  const isDraft = edge.status === 'draft'
                  // Always show edges at baseline opacity; highlight connected on selection
                  const opacity = hovered ? 1 : dimmed ? (selectedIsTraced ? 0 : 0.25) : 0.6
                  const sw      = hovered ? 2.5 : 1.5

                  return (
                    <g key={edge.id} style={{ pointerEvents: 'auto' }}>
                      {/* Wide transparent hit area for easy hover */}
                      <path
                        d={d}
                        fill="none"
                        stroke="transparent"
                        strokeWidth={14}
                        style={{ cursor: 'default' }}
                        onMouseEnter={() => setHoveredEdgeId(edge.id)}
                        onMouseLeave={() => setHoveredEdgeId(null)}
                      />
                      {/* Visible path */}
                      <path
                        d={d}
                        fill="none"
                        stroke={color}
                        strokeWidth={sw}
                        strokeDasharray={isDraft ? '5 3' : undefined}
                        strokeOpacity={opacity}
                        style={{ pointerEvents: 'none' }}
                      />
                      {/* Label at curve midpoint when hovered */}
                      {hovered && (
                        <g style={{ pointerEvents: 'none' }}>
                          <rect
                            x={midX - edge.name.length * 3.3 - 4}
                            y={midY - 10}
                            width={edge.name.length * 6.6 + 8}
                            height={14}
                            rx={3}
                            fill="#12121e"
                            stroke={color}
                            strokeWidth={0.75}
                            opacity={0.95}
                          />
                          <text
                            x={midX}
                            y={midY}
                            textAnchor="middle"
                            dominantBaseline="middle"
                            fontSize={9}
                            fill={color}
                            fontFamily="monospace"
                          >
                            {edge.name}
                          </text>
                        </g>
                      )}
                    </g>
                  )
                })}
              </svg>

              {/* ── Columns ── */}
              <div className="flex items-start w-full">
                {LAYERS.map((layer, idx) => (
                  <Fragment key={layer}>
                    {/* Gap between columns — SVG paths route through here */}
                    {idx > 0 && <div className="w-16 shrink-0" />}

                    <div className="flex-1 min-w-[160px] max-w-[280px]">
                      {/* Column header */}
                      <div className={`flex items-center gap-2 py-2.5 border-b ${LAYER[layer].border} mb-3 px-1`}>
                        <span className={`w-2 h-2 rounded-full shrink-0 ${LAYER[layer].dot}`} />
                        <span className={`font-mono text-[10px] font-semibold tracking-[0.18em] uppercase ${LAYER[layer].text}`}>
                          {LAYER[layer].label}
                        </span>
                        <span className="font-mono text-[10px] text-j-dim">
                          · {nodesByLayer[layer].length}
                        </span>
                      </div>

                      {/* Node cards */}
                      <div className="flex flex-col gap-3 px-1">
                        {nodesByLayer[layer].length === 0 ? (
                          <p className="font-mono text-[10px] text-j-border italic">empty</p>
                        ) : (
                          nodesByLayer[layer].map((n) => (
                            <div
                              key={n.id}
                              ref={(el) => {
                                if (el) nodeEls.current.set(n.id, el)
                                else nodeEls.current.delete(n.id)
                              }}
                              onClick={() => {
                                if (n.layer === 'bronze') return
                                setSelectedId(selectedId === n.id ? null : n.id)
                              }}
                              className={n.layer === 'bronze' ? 'cursor-default' : 'cursor-pointer'}
                            >
                              <NodeCard
                                node={n}
                                selected={selectedId === n.id}
                                dimmed={isNodeDimmed(n.id)}
                              />
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </Fragment>
                ))}
              </div>
            </div>
          </div>

          {/* ── Hovered edge info bar ── */}
          <div
            className={`mt-3 px-3 py-2 rounded border transition-all duration-100 ${
              hoveredPath
                ? 'border-j-border bg-j-surface'
                : 'border-transparent bg-transparent pointer-events-none'
            }`}
            style={{ minHeight: 34, opacity: hoveredPath ? 1 : 0 }}
          >
            {hoveredPath && (
              <div className="flex items-center gap-3 flex-wrap">
                <span className="font-mono text-[10px] text-j-dim">Transform:</span>
                <span className="font-mono text-[11px] text-j-bright font-medium">
                  {hoveredPath.edge.name}
                </span>
                <span className="font-mono text-[10px] text-j-dim">
                  {hoveredPath.edge.source_layer} → {hoveredPath.edge.target_layer}
                </span>
                <span className={`font-mono text-[10px] ${STATUS_TEXT[hoveredPath.edge.status] ?? 'text-j-dim'}`}>
                  {hoveredPath.edge.status}
                </span>
              </div>
            )}
          </div>

          {/* ── Summary ── */}
          <div className="mt-4 pt-4 border-t border-j-border flex items-center gap-6 flex-wrap">
            <span className="font-mono text-[10px] text-j-dim">
              {visibleNodes.length} entities · {visibleEdges.length} transforms
            </span>
            {visibleEdges.filter((e) => e.status === 'approved').length > 0 && (
              <span className="font-mono text-[10px] text-j-green">
                {visibleEdges.filter((e) => e.status === 'approved').length} approved
              </span>
            )}
            {visibleEdges.filter((e) => e.status === 'draft').length > 0 && (
              <span className="font-mono text-[10px] text-j-dim">
                {visibleEdges.filter((e) => e.status === 'draft').length} draft
              </span>
            )}
            {allNodes.length !== visibleNodes.length && (
              <span className="font-mono text-[10px] text-j-accent">
                {allNodes.length - visibleNodes.length} filtered
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
