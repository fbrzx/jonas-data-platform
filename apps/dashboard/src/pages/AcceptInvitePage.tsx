import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, setToken } from '../lib/api'

export default function AcceptInvitePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''

  const [form, setForm] = useState({ display_name: '', password: '', confirm: '' })
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-j-bg">
        <p className="font-mono text-xs text-j-red">Invalid invite link — no token found.</p>
      </div>
    )
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)

    if (form.password.length < 8) {
      setErr('Password must be at least 8 characters')
      return
    }
    if (form.password !== form.confirm) {
      setErr('Passwords do not match')
      return
    }
    if (!form.display_name.trim()) {
      setErr('Display name is required')
      return
    }

    setLoading(true)
    try {
      const data = await api.auth.acceptInvite(token, form.display_name.trim(), form.password)
      setToken(data.access_token, data.refresh_token)
      navigate('/', { replace: true })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to accept invite')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-j-bg px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="font-mono font-semibold text-j-bright tracking-widest text-lg">JONAS</div>
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mt-1">
            Data Platform
          </div>
        </div>

        <div className="bg-j-surface border border-j-border rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-j-border">
            <h1 className="font-mono text-[11px] font-semibold text-j-bright tracking-widest uppercase">
              Accept Invite
            </h1>
            <p className="font-mono text-[10px] text-j-dim mt-1">
              Set your display name and password to activate your account.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
            {[
              { label: 'Display Name', key: 'display_name', type: 'text', placeholder: 'Jane Doe' },
              { label: 'Password', key: 'password', type: 'password', placeholder: '••••••••' },
              { label: 'Confirm Password', key: 'confirm', type: 'password', placeholder: '••••••••' },
            ].map(({ label, key, type, placeholder }) => (
              <div key={key}>
                <label className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim block mb-1.5">
                  {label}
                </label>
                <input
                  type={type}
                  placeholder={placeholder}
                  value={form[key as keyof typeof form]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  required
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                />
              </div>
            ))}

            {err && (
              <p className="font-mono text-[10px] text-j-red bg-j-red-dim border border-j-red rounded px-3 py-2">
                {err}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full font-mono text-[10px] tracking-[0.08em] uppercase bg-j-accent text-j-bg py-2.5 rounded hover:opacity-90 disabled:opacity-40 mt-2"
            >
              {loading ? 'Activating…' : 'Activate Account'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
