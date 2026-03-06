import { useQuery } from '@tanstack/react-query'
import { api, type LineageNode, type LineageEdge } from '../lib/api'

// ── Layer config ──────────────────────────────────────────────────────────────

const LAYER = {
  bronze: { label: 'Bronze', dot: 'bg-j-amber', text: 'text-j-amber', border: 'border-j-amber', bg: 'bg-j-amber-dim', order: 0 },
  silver: { label: 'Silver', dot: 'bg-j-accent', text: 'text-j-accent', border: 'border-j-accent', bg: 'bg-j-accent-dim', order: 1 },
  gold:   { label: 'Gold',   dot: 'bg-j-bright', text: 'text-j-bright', border: 'border-j-bright', bg: 'bg-j-surface2',  order: 2 },
} as const

const STATUS_COLOR: Record<string, string> = {
  draft:    'text-j-dim',
  approved: 'text-j-green',
  rejected: 'text-j-red',
}

// ── Node card ─────────────────────────────────────────────────────────────────

function NodeCard({ node }: { node: LineageNode }) {
  const cfg = LAYER[node.layer as keyof typeof LAYER] ?? LAYER.bronze
  let tags: string[] = []
  try { tags = JSON.parse(node.tags || '[]') } catch { /* */ }

  return (
    <div className={`border ${cfg.border} rounded bg-j-surface px-3 py-2.5 w-full`}>
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
        <span className="font-mono text-j-bright text-[12px] font-medium truncate">{node.name}</span>
      </div>
      {node.description && (
        <p className="font-mono text-[10px] text-j-dim leading-snug truncate">{node.description}</p>
      )}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {tags.map((t) => (
            <span key={t} className="px-1 py-0.5 font-mono text-[9px] bg-j-surface2 text-j-dim border border-j-border rounded">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Edge label ────────────────────────────────────────────────────────────────

function EdgeLabel({ edge }: { edge: LineageEdge }) {
  const color = STATUS_COLOR[edge.status] ?? STATUS_COLOR.draft
  return (
    <div className="flex items-center gap-1.5 py-1 px-2 rounded border border-j-border bg-j-surface2">
      <span className="font-mono text-[9px] text-j-dim truncate max-w-[120px]">{edge.name}</span>
      <span className={`font-mono text-[9px] ${color} shrink-0`}>{edge.status}</span>
    </div>
  )
}

// ── Column header (standalone, for grid alignment) ────────────────────────────

function ColumnHeader({ layer, count }: { layer: keyof typeof LAYER; count: number }) {
  const cfg = LAYER[layer]
  return (
    <div className="flex items-center gap-2 py-2.5 border-b border-j-border px-1">
      <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
      <span className={`font-mono text-[10px] font-semibold tracking-[0.18em] uppercase ${cfg.text}`}>
        {cfg.label}
      </span>
      <span className="font-mono text-[10px] text-j-dim">· {count}</span>
    </div>
  )
}

// ── Arrow connector header (spacer + label, for grid alignment) ───────────────

function ArrowHeader() {
  return (
    <div className="py-2.5 border-b border-transparent px-2">
      <div className="h-[14px]" /> {/* matches text line-height of ColumnHeader */}
    </div>
  )
}

// ── Arrow connector content ───────────────────────────────────────────────────

function ArrowContent({ edges, from, to }: { edges: LineageEdge[]; from: string; to: string }) {
  const relevant = edges.filter((e) => e.source_layer === from && e.target_layer === to)
  return (
    <div className="flex flex-col gap-2 pt-3 px-2 min-w-[148px] shrink-0">
      {relevant.length === 0 ? (
        <div className="flex items-center gap-1 opacity-20 mt-1">
          <div className="flex-1 border-t border-dashed border-j-border" />
          <span className="font-mono text-[10px] text-j-dim">→</span>
          <div className="flex-1 border-t border-dashed border-j-border" />
        </div>
      ) : (
        relevant.map((e) => (
          <div key={e.id} className="flex items-center gap-0.5 w-full">
            <div className="w-3 border-t border-j-border shrink-0" />
            <EdgeLabel edge={e} />
            <div className="flex-1 border-t border-j-border min-w-[6px]" />
            <span className="font-mono text-[11px] text-j-dim shrink-0">›</span>
          </div>
        ))
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const LAYERS = ['bronze', 'silver', 'gold'] as const

export default function LineagePage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['lineage'],
    queryFn: api.transforms.lineage,
    staleTime: 30_000,
  })

  const nodesByLayer = Object.fromEntries(
    LAYERS.map((l) => [l, (data?.nodes ?? []).filter((n) => n.layer === l)])
  )

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      {/* Header */}
      <div className="flex items-center justify-between mb-5 pb-4 border-b border-j-border">
        <div>
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">Lineage</div>
          <h2 className="text-j-bright font-semibold">Data Lineage</h2>
        </div>
        <button
          onClick={() => refetch()}
          className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent px-3 py-1.5 rounded transition-colors"
        >
          Refresh
        </button>
      </div>

      {isLoading && <p className="font-mono text-[11px] text-j-dim text-center py-16">loading lineage…</p>}
      {error && (
        <div className="px-4 py-3 rounded border border-j-red-dim bg-j-red-dim font-mono text-xs text-j-red">
          {error instanceof Error ? error.message : 'error'}
        </div>
      )}

      {!isLoading && !error && (
        <>
          {/* Legend */}
          <div className="flex items-center gap-4 mb-6 px-1">
            <span className="font-mono text-[10px] text-j-dim uppercase tracking-wider">Legend:</span>
            {LAYERS.map((l) => {
              const cfg = LAYER[l]
              return (
                <div key={l} className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
                  <span className={`font-mono text-[10px] ${cfg.text}`}>{cfg.label}</span>
                </div>
              )
            })}
            <span className="ml-4 font-mono text-[10px] text-j-dim">arrows = transforms</span>
          </div>

          {/* DAG — header row then content row, so arrow labels align with entity cards */}
          <div className="overflow-x-auto pb-4">
            {/* Header row */}
            <div className="flex items-stretch min-w-max">
              <div className="flex-1 min-w-[220px]"><ColumnHeader layer="bronze" count={nodesByLayer.bronze.length} /></div>
              <ArrowHeader />
              <div className="flex-1 min-w-[220px]"><ColumnHeader layer="silver" count={nodesByLayer.silver.length} /></div>
              <ArrowHeader />
              <div className="flex-1 min-w-[220px]"><ColumnHeader layer="gold"   count={nodesByLayer.gold.length}   /></div>
            </div>
            {/* Content row */}
            <div className="flex items-start min-w-max">
              <div className="flex-1 min-w-[220px] flex flex-col gap-3 pt-3 px-1">
                {nodesByLayer.bronze.length === 0
                  ? <p className="font-mono text-[10px] text-j-border italic">empty</p>
                  : nodesByLayer.bronze.map((n) => <NodeCard key={n.id} node={n} />)}
              </div>
              <ArrowContent edges={data?.edges ?? []} from="bronze" to="silver" />
              <div className="flex-1 min-w-[220px] flex flex-col gap-3 pt-3 px-1">
                {nodesByLayer.silver.length === 0
                  ? <p className="font-mono text-[10px] text-j-border italic">empty</p>
                  : nodesByLayer.silver.map((n) => <NodeCard key={n.id} node={n} />)}
              </div>
              <ArrowContent edges={data?.edges ?? []} from="silver" to="gold" />
              <div className="flex-1 min-w-[220px] flex flex-col gap-3 pt-3 px-1">
                {nodesByLayer.gold.length === 0
                  ? <p className="font-mono text-[10px] text-j-border italic">empty</p>
                  : nodesByLayer.gold.map((n) => <NodeCard key={n.id} node={n} />)}
              </div>
            </div>
          </div>

          {/* Summary */}
          <div className="mt-6 pt-4 border-t border-j-border flex items-center gap-6">
            <span className="font-mono text-[10px] text-j-dim">
              {(data?.nodes ?? []).length} entities · {(data?.edges ?? []).length} transforms
            </span>
            {(data?.edges ?? []).filter((e) => e.status === 'approved').length > 0 && (
              <span className="font-mono text-[10px] text-j-green">
                {(data?.edges ?? []).filter((e) => e.status === 'approved').length} approved
              </span>
            )}
            {(data?.edges ?? []).filter((e) => e.status === 'draft').length > 0 && (
              <span className="font-mono text-[10px] text-j-dim">
                {(data?.edges ?? []).filter((e) => e.status === 'draft').length} pending approval
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
