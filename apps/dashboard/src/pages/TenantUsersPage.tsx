import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { TenantUser, InviteResponse } from '../lib/api'

const ROLES = ['admin', 'analyst', 'viewer'] as const

function RoleBadge({ role }: { role: string }) {
  const color =
    role === 'admin' ? 'text-j-accent border-j-accent' :
    role === 'analyst' ? 'text-j-green border-j-green' :
    'text-j-dim border-j-border'
  return (
    <span className={`font-mono text-[9px] tracking-[0.08em] uppercase border rounded px-1.5 py-0.5 ${color}`}>
      {role}
    </span>
  )
}

function InviteModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ email: '', role: 'analyst' })
  const [err, setErr] = useState<string | null>(null)
  const [sent, setSent] = useState<InviteResponse | null>(null)

  const mutation = useMutation({
    mutationFn: () => api.tenant.inviteUser(form),
    onSuccess: (data) => setSent(data),
    onError: (e) => setErr(e instanceof Error ? e.message : 'Failed to send invite'),
  })

  if (sent) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="w-full max-w-sm bg-j-surface border border-j-border rounded-lg overflow-hidden shadow-2xl">
          <div className="px-6 py-4 border-b border-j-border flex items-center justify-between">
            <h2 className="font-mono text-[11px] font-semibold text-j-bright tracking-widest uppercase">
              Invite Sent
            </h2>
            <button onClick={onClose} className="font-mono text-j-dim hover:text-j-text text-xs">✕</button>
          </div>
          <div className="px-6 py-5 space-y-4">
            <p className="font-mono text-[11px] text-j-text">
              Invite sent to <span className="text-j-bright">{sent.email}</span> as <span className="text-j-accent">{sent.role}</span>.
            </p>
            <p className="font-mono text-[10px] text-j-dim">
              Check Mailpit at <span className="text-j-text">http://localhost:8025</span> in dev, or share the link below:
            </p>
            <div className="bg-j-bg border border-j-border rounded px-3 py-2">
              <p className="font-mono text-[9px] text-j-dim break-all">{sent.invite_link}</p>
            </div>
            <p className="font-mono text-[10px] text-j-dim">Expires: {new Date(sent.expires_at).toLocaleString()}</p>
            <button
              onClick={onClose}
              className="w-full font-mono text-[10px] tracking-[0.08em] uppercase bg-j-accent text-j-bg py-2 rounded hover:opacity-90"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-sm bg-j-surface border border-j-border rounded-lg overflow-hidden shadow-2xl">
        <div className="px-6 py-4 border-b border-j-border flex items-center justify-between">
          <h2 className="font-mono text-[11px] font-semibold text-j-bright tracking-widest uppercase">
            Invite User
          </h2>
          <button onClick={onClose} className="font-mono text-j-dim hover:text-j-text text-xs">✕</button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim block mb-1.5">
              Email
            </label>
            <input
              type="email"
              placeholder="user@acme.io"
              value={form.email}
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
            />
          </div>

          <div>
            <label className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim block mb-1.5">
              Role
            </label>
            <select
              value={form.role}
              onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
              className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
            >
              {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>

          <p className="font-mono text-[10px] text-j-dim">
            An invite link will be sent. The user sets their own password.
          </p>

          {err && (
            <p className="font-mono text-[10px] text-j-red bg-j-red-dim border border-j-red rounded px-3 py-2">
              {err}
            </p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || !form.email}
              className="flex-1 font-mono text-[10px] tracking-[0.08em] uppercase bg-j-accent text-j-bg py-2 rounded hover:opacity-90 disabled:opacity-40"
            >
              {mutation.isPending ? 'Sending…' : 'Send Invite'}
            </button>
            <button
              onClick={onClose}
              className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim border border-j-border rounded px-4 py-2 hover:border-j-text"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function TenantUsersPage() {
  const qc = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [editingRole, setEditingRole] = useState<string | null>(null)

  const { data: users = [], isLoading, error } = useQuery({
    queryKey: ['tenant-users'],
    queryFn: () => api.tenant.listUsers(),
  })

  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      api.tenant.changeRole(userId, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tenant-users'] })
      setEditingRole(null)
    },
  })

  const revokeUser = useMutation({
    mutationFn: (userId: string) => api.tenant.revokeUser(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tenant-users'] }),
  })

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-j-dim font-mono text-xs">
        Loading…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-j-red font-mono text-xs">
        {error instanceof Error ? error.message : 'Failed to load users'}
      </div>
    )
  }

  const active = users.filter((u: TenantUser) => !u.revoked_at)
  const revoked = users.filter((u: TenantUser) => u.revoked_at)

  return (
    <div className="flex-1 overflow-y-auto">
      {showModal && <InviteModal onClose={() => setShowModal(false)} />}

      <div className="max-w-3xl mx-auto px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="font-mono text-sm font-semibold text-j-bright tracking-widest uppercase">
              Team Members
            </h1>
            <p className="font-mono text-[11px] text-j-dim mt-1">
              {active.length} active · {revoked.length} revoked
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="font-mono text-[10px] tracking-[0.08em] uppercase bg-j-accent text-j-bg px-4 py-2 rounded hover:opacity-90"
          >
            + Add User
          </button>
        </div>

        {/* Active users */}
        <div className="bg-j-surface border border-j-border rounded-lg overflow-hidden mb-6">
          <div className="px-5 py-3 border-b border-j-border">
            <h2 className="font-mono text-[10px] font-semibold text-j-dim tracking-[0.12em] uppercase">
              Active Members
            </h2>
          </div>
          {active.length === 0 ? (
            <div className="px-5 py-8 text-center font-mono text-[11px] text-j-dim">
              No active members
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-j-border">
                  {['User', 'Role', 'Joined', ''].map(h => (
                    <th key={h} className="px-5 py-2.5 text-left font-mono text-[9px] tracking-[0.1em] uppercase text-j-dim">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {active.map((u: TenantUser) => (
                  <tr key={u.id} className="border-b border-j-border last:border-0 hover:bg-j-bg/40">
                    <td className="px-5 py-3">
                      <div className="font-mono text-xs text-j-bright">{u.display_name}</div>
                      <div className="font-mono text-[10px] text-j-dim">{u.email}</div>
                    </td>
                    <td className="px-5 py-3">
                      {editingRole === u.id ? (
                        <div className="flex items-center gap-1.5">
                          <select
                            defaultValue={u.role}
                            onChange={e => changeRole.mutate({ userId: u.id, role: e.target.value })}
                            className="bg-j-bg border border-j-accent rounded px-2 py-1 font-mono text-[10px] text-j-bright focus:outline-none"
                            autoFocus
                          >
                            {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                          </select>
                          <button
                            onClick={() => setEditingRole(null)}
                            className="font-mono text-[9px] text-j-dim hover:text-j-text"
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setEditingRole(u.id)}
                          title="Click to change role"
                        >
                          <RoleBadge role={u.role} />
                        </button>
                      )}
                    </td>
                    <td className="px-5 py-3 font-mono text-[10px] text-j-dim">
                      {u.granted_at ? new Date(u.granted_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button
                        onClick={() => {
                          if (confirm(`Revoke access for ${u.email}?`)) {
                            revokeUser.mutate(u.id)
                          }
                        }}
                        className="font-mono text-[9px] tracking-[0.06em] uppercase text-j-dim hover:text-j-red transition-colors"
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Revoked users */}
        {revoked.length > 0 && (
          <div className="bg-j-surface border border-j-border rounded-lg overflow-hidden opacity-60">
            <div className="px-5 py-3 border-b border-j-border">
              <h2 className="font-mono text-[10px] font-semibold text-j-dim tracking-[0.12em] uppercase">
                Revoked
              </h2>
            </div>
            <table className="w-full">
              <tbody>
                {revoked.map((u: TenantUser) => (
                  <tr key={u.id} className="border-b border-j-border last:border-0">
                    <td className="px-5 py-3">
                      <div className="font-mono text-xs text-j-dim line-through">{u.display_name}</div>
                      <div className="font-mono text-[10px] text-j-dim">{u.email}</div>
                    </td>
                    <td className="px-5 py-3">
                      <RoleBadge role={u.role} />
                    </td>
                    <td className="px-5 py-3 font-mono text-[10px] text-j-dim">
                      Revoked {u.revoked_at ? new Date(u.revoked_at).toLocaleDateString() : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
