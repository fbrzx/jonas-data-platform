import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Entity, type Transform, getToken, getRoleFromToken, isSuperUser, getActiveTenantId } from '../lib/api'
import ActivityChart from '../components/ActivityChart'


// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label, value, sub, color = 'text-j-bright', border = 'border-j-border',
}: {
  label: string
  value: number | string
  sub?: string
  color?: string
  border?: string
}) {
  return (
    <div className={`border ${border} rounded bg-j-surface px-4 py-3`}>
      <div className="font-mono text-[10px] text-j-dim tracking-[0.14em] uppercase mb-1">{label}</div>
      <div className={`font-mono text-2xl font-semibold leading-none ${color}`}>{value}</div>
      {sub && <div className="font-mono text-[10px] text-j-dim mt-1">{sub}</div>}
    </div>
  )
}

// ── Layer mini badge ──────────────────────────────────────────────────────────

const LAYER_COLOR: Record<string, string> = {
  bronze: 'text-j-amber',
  silver: 'text-j-accent',
  gold:   'text-j-bright',
}

// ── Recent entity row ─────────────────────────────────────────────────────────

function EntityRow({ entity }: { entity: Entity }) {
  let tags: string[] = []
  try { tags = JSON.parse(entity.tags || '[]') } catch { /* */ }
  return (
    <div className="flex items-center gap-3 py-2 border-b border-j-border last:border-0">
      <span className={`font-mono text-[10px] w-12 shrink-0 ${LAYER_COLOR[entity.layer] ?? 'text-j-dim'}`}>
        {entity.layer}
      </span>
      <span className="font-mono text-sm text-j-bright flex-1 truncate">{entity.name}</span>
      {tags[0] && (
        <span className="font-mono text-[10px] text-j-dim shrink-0">{tags[0]}</span>
      )}
    </div>
  )
}

// ── Transform row ─────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  draft:    'text-j-dim',
  approved: 'text-j-green',
  rejected: 'text-j-red',
}

function TransformRow({ t }: { t: Transform }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-j-border last:border-0">
      <span className={`font-mono text-[10px] w-16 shrink-0 ${STATUS_COLOR[t.status] ?? 'text-j-dim'}`}>
        {t.status}
      </span>
      <span className="font-mono text-sm text-j-text flex-1 truncate">{t.name}</span>
      <span className="font-mono text-[10px] text-j-dim shrink-0">
        {t.source_layer}→{t.target_layer}
      </span>
    </div>
  )
}

// ── Quick action ──────────────────────────────────────────────────────────────

function QuickAction({ to, glyph, label, sub }: { to: string; glyph: string; label: string; sub: string }) {
  return (
    <Link
      to={to}
      className="block border border-j-border rounded bg-j-surface hover:border-j-accent hover:bg-j-accent-dim transition-colors p-3 group"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="font-mono text-base text-j-dim group-hover:text-j-accent">{glyph}</span>
        <span className="font-mono text-[11px] font-medium text-j-bright group-hover:text-j-accent tracking-wide">{label}</span>
      </div>
      <p className="font-mono text-[10px] text-j-dim">{sub}</p>
    </Link>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const role = getRoleFromToken(getToken())
  const isSU = isSuperUser()
  const hasTenant = !!getActiveTenantId()

  const { data: entities } = useQuery({
    queryKey: ['entities'],
    queryFn: api.catalogue.list,
    staleTime: 30_000,
  })
  const { data: transforms } = useQuery({
    queryKey: ['transforms'],
    queryFn: api.transforms.list,
    staleTime: 30_000,
  })
  const { data: integrations } = useQuery({
    queryKey: ['integrations'],
    queryFn: api.integrations.list,
    staleTime: 30_000,
  })
  const { data: auditStats } = useQuery({
    queryKey: ['audit-stats'],
    queryFn: () => api.audit.stats(14),
    staleTime: 60_000,
  })
  const { data: collections } = useQuery({
    queryKey: ['collections'],
    queryFn: api.collections.list,
    staleTime: 30_000,
  })

  const ents = entities ?? []
  const trns = transforms ?? []
  const ints = integrations ?? []

  const bronze = ents.filter((e) => e.layer === 'bronze').length
  const silver = ents.filter((e) => e.layer === 'silver').length
  const gold   = ents.filter((e) => e.layer === 'gold').length
  const pending = trns.filter((t) => t.status === 'draft').length
  const approved = trns.filter((t) => t.status === 'approved').length
  const activeInts = ints.filter((i) => i.status === 'active').length

  const recentEntities = [...ents].sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  ).slice(0, 5)

  const recentTransforms = [...trns].sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  ).slice(0, 5)

  if (isSU && !hasTenant) {
    return (
      <div className="flex-1 flex items-center justify-center bg-j-bg">
        <div className="text-center space-y-3">
          <div className="font-mono text-2xl text-j-dim">⬢</div>
          <div className="font-mono text-sm text-j-bright">Platform Super User</div>
          <div className="font-mono text-[11px] text-j-dim max-w-xs">
            Select a tenant from the sidebar to view and manage its data.
          </div>
          <div className="font-mono text-[10px] text-j-dim opacity-60 pt-2">
            Or go to <Link to="/superuser" className="text-j-accent hover:underline">Platform Admin</Link> to manage tenants.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto p-6 bg-j-bg">
      {/* Header */}
      <div className="mb-6 pb-4 border-b border-j-border">
        <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">Overview</div>
        <div className="flex items-baseline gap-3">
          <h2 className="text-j-bright font-semibold">Jonas Data Platform</h2>
          <span className={`font-mono text-[10px] px-2 py-0.5 rounded border ${
            role === 'owner'    ? 'text-j-green  border-j-green  bg-j-green-dim'  :
            role === 'admin'    ? 'text-j-purple border-j-purple bg-j-purple-dim' :
            role === 'engineer' ? 'text-j-amber  border-j-amber  bg-j-amber-dim'  :
            role === 'analyst'  ? 'text-j-accent border-j-accent bg-j-accent-dim' :
                                  'text-j-dim border-j-border bg-j-surface2'
          }`}>{role}</span>
        </div>
        <p className="font-mono text-[11px] text-j-dim mt-1">
          tenant / acme
          {collections && collections.length > 0 && (
            <> · <Link to="/collections" className="hover:text-j-accent">{collections.length} collections</Link></>
          )}
          {' '}· {ents.length} entities · {trns.length} transforms · {ints.length} connectors
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <StatCard label="Bronze entities"   value={bronze}    color="text-j-amber"  border="border-j-amber" />
        <StatCard label="Silver entities"   value={silver}    color="text-j-accent" border="border-j-accent" />
        <StatCard label="Gold entities"     value={gold}      color="text-j-bright" border="border-j-bright" />
        <StatCard label="Active connectors" value={activeInts} sub={`${ints.length} total`} color="text-j-green" border="border-j-green" />
      </div>

      {/* Transform pipeline */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <StatCard label="Pending approval" value={pending}  color="text-j-dim"   />
        <StatCard label="Approved"         value={approved} color="text-j-green" />
        <StatCard label="Total transforms" value={trns.length} />
      </div>

      {/* Quick actions */}
      <div className="mb-6">
        <div className="font-mono text-[10px] text-j-dim tracking-[0.14em] uppercase mb-3">Quick actions</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <QuickAction to="/chat"         glyph="◈" label="Ask Jonas"        sub="Chat with the AI assistant" />
          <QuickAction to="/catalogue"    glyph="◫" label="Browse Catalogue" sub="Explore entities and schemas" />
          <QuickAction to="/transforms"   glyph="⟳" label="Transforms"       sub="Review and approve SQL transforms" />
          <QuickAction to="/lineage"      glyph="⬡" label="View Lineage"     sub="Bronze → Silver → Gold flow" />
        </div>
      </div>

      {/* Activity chart — full-bleed: -mx-6 cancels the p-6 container padding */}
      <div className="mb-6 -mx-6 border-y border-j-border bg-j-surface overflow-hidden">
        <div className="px-4 py-2.5 border-b border-j-border flex items-center justify-between">
          <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-j-dim">Job activity — last 14 days</span>
          <Link to="/audit" className="font-mono text-[10px] text-j-accent hover:underline">view audit →</Link>
        </div>
        <div className="px-4 py-3 text-j-dim">
          {auditStats ? (
            <ActivityChart
              connectorDays={auditStats.connector_daily}
              transformDays={auditStats.transform_daily}
              days={14}
            />
          ) : (
            <div className="h-14 flex items-center">
              <span className="font-mono text-[10px] text-j-dim italic">loading…</span>
            </div>
          )}
        </div>
      </div>

      {/* Recent entities + transforms */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="border border-j-border rounded bg-j-surface overflow-hidden">
          <div className="px-4 py-2.5 border-b border-j-border flex items-center justify-between">
            <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-j-dim">Recent entities</span>
            <Link to="/catalogue" className="font-mono text-[10px] text-j-accent hover:underline">view all →</Link>
          </div>
          <div className="px-4">
            {recentEntities.length === 0
              ? <p className="font-mono text-[11px] text-j-dim py-4 italic">none yet — run seed</p>
              : recentEntities.map((e) => <EntityRow key={e.id} entity={e} />)
            }
          </div>
        </div>

        <div className="border border-j-border rounded bg-j-surface overflow-hidden">
          <div className="px-4 py-2.5 border-b border-j-border flex items-center justify-between">
            <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-j-dim">Recent transforms</span>
            <Link to="/transforms" className="font-mono text-[10px] text-j-accent hover:underline">view all →</Link>
          </div>
          <div className="px-4">
            {recentTransforms.length === 0
              ? <p className="font-mono text-[11px] text-j-dim py-4 italic">none yet — run seed</p>
              : recentTransforms.map((t) => <TransformRow key={t.id} t={t} />)
            }
          </div>
        </div>
      </div>
    </div>
  )
}
