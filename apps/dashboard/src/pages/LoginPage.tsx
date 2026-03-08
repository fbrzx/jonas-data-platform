import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../lib/api'

export default function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await api.auth.login(email, password)
      setToken(result.access_token, result.refresh_token)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-j-bg flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo / wordmark */}
        <div className="text-center mb-8">
          <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-j-dim mb-1">Jonas</div>
          <h1 className="font-mono text-xl font-semibold text-j-bright">Data Platform</h1>
        </div>

        <div className="bg-j-surface border border-j-border rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-j-border">
            <p className="font-mono text-[11px] text-j-dim">Sign in to continue</p>
          </div>

          <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
            <div>
              <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1.5">
                Email
              </label>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                placeholder="admin@acme.io"
              />
            </div>

            <div>
              <label className="font-mono text-[10px] tracking-[0.1em] uppercase text-j-dim block mb-1.5">
                Password
              </label>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright placeholder:text-j-dim focus:outline-none focus:border-j-accent"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="font-mono text-[11px] text-j-red bg-j-red-dim border border-j-red rounded px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full font-mono text-[10px] tracking-[0.1em] uppercase bg-j-accent text-j-bg py-2.5 rounded hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {/* Demo mode hint */}
          <div className="px-6 pb-5">
            <div className="border-t border-j-border pt-4">
              <p className="font-mono text-[10px] text-j-dim text-center mb-2">
                Demo credentials
              </p>
              <button
                type="button"
                onClick={() => { setEmail('superuser@platform.io'); setPassword('admin123') }}
                className="w-full font-mono text-[9px] tracking-[0.05em] uppercase text-j-dim border border-j-border rounded py-1.5 hover:border-j-accent hover:text-j-accent transition-colors"
              >
                Super User — superuser@platform.io
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
