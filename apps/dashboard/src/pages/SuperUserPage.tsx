import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { PlatformTenant, PlatformSuperUser, TenantUser } from '../lib/api'
import { useToast } from '../lib/toast'

// ── Helpers ────────────────────────────────────────────────────────────────────

function Pill({ children, red }: { children: React.ReactNode; red?: boolean }) {
  return (
    <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${
      red ? 'text-j-red border-j-red bg-j-red/10' : 'text-j-dim border-j-border bg-j-surface2'
    }`}>
      {children}
    </span>
  )
}

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="font-mono text-[11px] font-semibold tracking-widest uppercase text-j-bright">{title}</h2>
      {action}
    </div>
  )
}

// ── Create Tenant Modal ────────────────────────────────────────────────────────

function CreateTenantModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: () => api.superuser.createTenant({ slug, name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['su-tenants'] })
      toast('success', 'Tenant created')
      onClose()
    },
    onError: (e: Error) => toast('error', e.message),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-j-surface border border-j-border rounded p-6 w-full max-w-md font-mono">
        <h3 className="text-[11px] font-semibold tracking-widest uppercase text-j-bright mb-4">Create Tenant</h3>
        <div className="space-y-3">
          <div>
            <label className="text-[10px] text-j-dim uppercase tracking-widest block mb-1">Slug</label>
            <input
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 text-[11px] text-j-text font-mono outline-none focus:border-j-accent"
              placeholder="my-tenant"
              value={slug}
              onChange={e => setSlug(e.target.value.toLowerCase())}
            />
            <p className="text-[10px] text-j-dim mt-1">Lowercase, alphanumeric, hyphens. Immutable.</p>
          </div>
          <div>
            <label className="text-[10px] text-j-dim uppercase tracking-widest block mb-1">Display Name</label>
            <input
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 text-[11px] text-j-text font-mono outline-none focus:border-j-accent"
              placeholder="My Tenant"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          </div>
        </div>
        <div className="flex gap-2 mt-5">
          <button
            className="flex-1 bg-j-accent text-j-bg font-mono text-[10px] tracking-widest uppercase px-4 py-2 rounded hover:opacity-90 disabled:opacity-40"
            disabled={!slug || !name || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
          <button
            className="flex-1 border border-j-border font-mono text-[10px] tracking-widest uppercase px-4 py-2 rounded text-j-dim hover:text-j-text"
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Create Super User Modal ────────────────────────────────────────────────────

function CreateSuperUserModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')

  const create = useMutation({
    mutationFn: () => api.superuser.createSuperUser({ email, display_name: displayName, password }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['su-superusers'] })
      toast('success', 'Super user created')
      onClose()
    },
    onError: (e: Error) => toast('error', e.message),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-j-surface border border-j-border rounded p-6 w-full max-w-md font-mono">
        <h3 className="text-[11px] font-semibold tracking-widest uppercase text-j-bright mb-4">Add Super User</h3>
        <div className="space-y-3">
          <div>
            <label className="text-[10px] text-j-dim uppercase tracking-widest block mb-1">Email</label>
            <input
              type="email"
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 text-[11px] text-j-text font-mono outline-none focus:border-j-accent"
              value={email}
              onChange={e => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="text-[10px] text-j-dim uppercase tracking-widest block mb-1">Display Name</label>
            <input
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 text-[11px] text-j-text font-mono outline-none focus:border-j-accent"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
            />
          </div>
          <div>
            <label className="text-[10px] text-j-dim uppercase tracking-widest block mb-1">Password</label>
            <input
              type="password"
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 text-[11px] text-j-text font-mono outline-none focus:border-j-accent"
              value={password}
              onChange={e => setPassword(e.target.value)}
            />
          </div>
        </div>
        <div className="flex gap-2 mt-5">
          <button
            className="flex-1 bg-j-accent text-j-bg font-mono text-[10px] tracking-widest uppercase px-4 py-2 rounded hover:opacity-90 disabled:opacity-40"
            disabled={!email || !displayName || !password || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
          <button
            className="flex-1 border border-j-border font-mono text-[10px] tracking-widest uppercase px-4 py-2 rounded text-j-dim hover:text-j-text"
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tenant Users Drawer ────────────────────────────────────────────────────────

function TenantUsersDrawer({ tenant, onClose }: { tenant: PlatformTenant; onClose: () => void }) {
  const { data: users = [], isLoading } = useQuery<TenantUser[]>({
    queryKey: ['su-tenant-users', tenant.id],
    queryFn: () => api.superuser.listTenantUsers(tenant.id),
  })

  const active = users.filter(u => !u.revoked_at)
  const revoked = users.filter(u => u.revoked_at)

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <div className="w-[480px] bg-j-surface border-l border-j-border flex flex-col font-mono">
        <div className="h-10 flex items-center justify-between px-5 border-b border-j-border bg-j-bg">
          <span className="text-[11px] font-semibold tracking-widest uppercase text-j-bright">
            {tenant.name} · Members
          </span>
          <button className="text-j-dim hover:text-j-text text-[11px]" onClick={onClose}>close</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {isLoading && <p className="text-[11px] text-j-dim">Loading…</p>}
          {!isLoading && active.length === 0 && (
            <p className="text-[11px] text-j-dim">No active members.</p>
          )}
          {active.map(u => (
            <div key={u.id} className="flex items-center justify-between py-2 border-b border-j-border/40">
              <div>
                <div className="text-[11px] text-j-text">{u.display_name}</div>
                <div className="text-[10px] text-j-dim">{u.email}</div>
              </div>
              <Pill>{u.role}</Pill>
            </div>
          ))}
          {revoked.length > 0 && (
            <>
              <p className="text-[10px] text-j-dim tracking-widest uppercase mt-4 mb-1">Revoked</p>
              {revoked.map(u => (
                <div key={u.id} className="flex items-center justify-between py-2 opacity-40">
                  <div>
                    <div className="text-[11px] text-j-text line-through">{u.display_name}</div>
                    <div className="text-[10px] text-j-dim">{u.email}</div>
                  </div>
                  <Pill>{u.role}</Pill>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function SuperUserPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const [showCreateTenant, setShowCreateTenant] = useState(false)
  const [showCreateSU, setShowCreateSU] = useState(false)
  const [selectedTenant, setSelectedTenant] = useState<PlatformTenant | null>(null)

  const { data: tenants = [], isLoading: tenantsLoading } = useQuery<PlatformTenant[]>({
    queryKey: ['su-tenants'],
    queryFn: api.superuser.listTenants,
  })

  const { data: superusers = [], isLoading: suLoading } = useQuery<PlatformSuperUser[]>({
    queryKey: ['su-superusers'],
    queryFn: api.superuser.listSuperUsers,
  })

  const deleteTenant = useMutation({
    mutationFn: (id: string) => api.superuser.deleteTenant(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['su-tenants'] })
      toast('success', 'Tenant deactivated — all memberships revoked')
    },
    onError: (e: Error) => toast('error', e.message),
  })

  const revokeSU = useMutation({
    mutationFn: (id: string) => api.superuser.revokeSuperUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['su-superusers'] })
      toast('success', 'Super user privileges revoked')
    },
    onError: (e: Error) => toast('error', e.message),
  })

  function confirmDeleteTenant(t: PlatformTenant) {
    if (confirm(`Deactivate tenant "${t.name}" and revoke all ${t.active_members} active memberships?`)) {
      deleteTenant.mutate(t.id)
    }
  }

  function confirmRevokeSU(u: PlatformSuperUser) {
    if (confirm(`Remove super user privileges from ${u.email}?`)) {
      revokeSU.mutate(u.id)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 font-mono">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-[13px] font-semibold tracking-widest uppercase text-j-bright mb-1">
          Platform Administration
        </h1>
        <p className="text-[11px] text-j-dim">
          Manage all tenants and platform super users. Changes here affect every tenant.
        </p>
      </div>

      {/* ── Tenants ─────────────────────────────────────────────────────────── */}
      <section className="mb-10">
        <SectionHeader
          title={`Tenants (${tenants.length})`}
          action={
            <button
              className="font-mono text-[10px] tracking-widest uppercase text-j-accent hover:opacity-70 border border-j-accent px-3 py-1 rounded"
              onClick={() => setShowCreateTenant(true)}
            >
              + New Tenant
            </button>
          }
        />

        {tenantsLoading && <p className="text-[11px] text-j-dim">Loading…</p>}

        <div className="border border-j-border rounded overflow-hidden">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-j-border bg-j-bg">
                <th className="text-left px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">Tenant</th>
                <th className="text-left px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">Slug</th>
                <th className="text-right px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">Members</th>
                <th className="text-right px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {tenants.map(t => (
                <tr key={t.id} className="border-b border-j-border/40 hover:bg-j-surface2/50 transition-colors">
                  <td className="px-4 py-3 text-j-text font-medium">{t.name}</td>
                  <td className="px-4 py-3">
                    <Pill>{t.slug}</Pill>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-j-accent hover:underline"
                      onClick={() => setSelectedTenant(t)}
                    >
                      {t.active_members} active
                    </button>
                    {t.total_members > t.active_members && (
                      <span className="text-j-dim ml-1">/ {t.total_members}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-j-dim">
                    {new Date(t.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-j-red hover:opacity-70 text-[10px] tracking-widest uppercase"
                      onClick={() => confirmDeleteTenant(t)}
                      disabled={deleteTenant.isPending}
                    >
                      Deactivate
                    </button>
                  </td>
                </tr>
              ))}
              {!tenantsLoading && tenants.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-j-dim text-[11px]">
                    No tenants yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Super Users ─────────────────────────────────────────────────────── */}
      <section>
        <SectionHeader
          title={`Super Users (${superusers.length})`}
          action={
            <button
              className="font-mono text-[10px] tracking-widest uppercase text-j-accent hover:opacity-70 border border-j-accent px-3 py-1 rounded"
              onClick={() => setShowCreateSU(true)}
            >
              + Add Super User
            </button>
          }
        />

        {suLoading && <p className="text-[11px] text-j-dim">Loading…</p>}

        <div className="border border-j-border rounded overflow-hidden">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-j-border bg-j-bg">
                <th className="text-left px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">User</th>
                <th className="text-left px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">Email</th>
                <th className="text-right px-4 py-2 text-j-dim font-normal tracking-widest uppercase text-[10px]">Since</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {superusers.map(u => (
                <tr key={u.id} className="border-b border-j-border/40 hover:bg-j-surface2/50 transition-colors">
                  <td className="px-4 py-3 text-j-text font-medium">{u.display_name}</td>
                  <td className="px-4 py-3 text-j-dim">{u.email}</td>
                  <td className="px-4 py-3 text-right text-j-dim">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-j-red hover:opacity-70 text-[10px] tracking-widest uppercase"
                      onClick={() => confirmRevokeSU(u)}
                      disabled={revokeSU.isPending}
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
              {!suLoading && superusers.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-j-dim text-[11px]">
                    No super users defined.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="text-[10px] text-j-dim mt-3">
          Super users bypass all tenant RBAC. Pass <code className="text-j-accent">X-Tenant-ID</code> header to act within a specific tenant as admin.
        </p>
      </section>

      {/* Modals */}
      {showCreateTenant && <CreateTenantModal onClose={() => setShowCreateTenant(false)} />}
      {showCreateSU && <CreateSuperUserModal onClose={() => setShowCreateSU(false)} />}
      {selectedTenant && (
        <TenantUsersDrawer tenant={selectedTenant} onClose={() => setSelectedTenant(null)} />
      )}
    </div>
  )
}
