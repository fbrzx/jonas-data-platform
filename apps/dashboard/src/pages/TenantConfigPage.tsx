import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { TenantConfig } from '../lib/api'

export default function TenantConfigPage() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['tenant-config'],
    queryFn: () => api.tenant.getConfig(),
  })

  const [draft, setDraft] = useState<Partial<TenantConfig>>({})
  const [saved, setSaved] = useState(false)

  const mutation = useMutation({
    mutationFn: (body: Partial<TenantConfig>) => api.tenant.updateConfig(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tenant-config'] })
      setDraft({})
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-j-dim font-mono text-xs">
        Loading…
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-j-red font-mono text-xs">
        {error instanceof Error ? error.message : 'Failed to load config'}
      </div>
    )
  }

  const cfg = { ...data, ...draft }

  function field(key: keyof TenantConfig) {
    return (val: string | boolean | number) =>
      setDraft(d => ({ ...d, [key]: val }))
  }

  function handleSave(e: React.FormEvent) {
    e.preventDefault()
    mutation.mutate(draft)
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="font-mono text-sm font-semibold text-j-bright tracking-widest uppercase">
            Tenant Configuration
          </h1>
          <p className="font-mono text-[11px] text-j-dim mt-1">
            Admin-only settings that control platform behaviour for this tenant.
          </p>
        </div>

        <form onSubmit={handleSave} className="space-y-6">
          {/* Privacy */}
          <section className="bg-j-surface border border-j-border rounded-lg overflow-hidden">
            <div className="px-5 py-3 border-b border-j-border">
              <h2 className="font-mono text-[11px] font-semibold text-j-bright tracking-[0.1em] uppercase">
                Privacy
              </h2>
            </div>
            <div className="px-5 py-4">
              <label className="flex items-center gap-3 cursor-pointer">
                <div
                  onClick={() => field('pii_masking_enabled')(!cfg.pii_masking_enabled)}
                  className={`w-9 h-5 rounded-full transition-colors ${cfg.pii_masking_enabled ? 'bg-j-accent' : 'bg-j-border'} relative cursor-pointer`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${cfg.pii_masking_enabled ? 'translate-x-4' : 'translate-x-0.5'}`}
                  />
                </div>
                <div>
                  <span className="font-mono text-xs text-j-text">PII Masking</span>
                  <p className="font-mono text-[10px] text-j-dim mt-0.5">
                    Mask sensitive fields (email, phone, name) for non-owner roles
                  </p>
                </div>
              </label>
            </div>
          </section>

          {/* Limits */}
          <section className="bg-j-surface border border-j-border rounded-lg overflow-hidden">
            <div className="px-5 py-3 border-b border-j-border">
              <h2 className="font-mono text-[11px] font-semibold text-j-bright tracking-[0.1em] uppercase">
                Limits
              </h2>
            </div>
            <div className="px-5 py-4 grid grid-cols-2 gap-4">
              <div>
                <label className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim block mb-1.5">
                  Max connector runs / day
                </label>
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={cfg.max_connector_runs_per_day}
                  onChange={e => field('max_connector_runs_per_day')(Number(e.target.value))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
                />
              </div>
              <div>
                <label className="font-mono text-[10px] tracking-[0.08em] uppercase text-j-dim block mb-1.5">
                  Data retention (days)
                </label>
                <input
                  type="number"
                  min={1}
                  max={3650}
                  value={cfg.data_retention_days}
                  onChange={e => field('data_retention_days')(Number(e.target.value))}
                  className="w-full bg-j-bg border border-j-border rounded px-3 py-2 font-mono text-xs text-j-bright focus:outline-none focus:border-j-accent"
                />
              </div>
            </div>
          </section>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={mutation.isPending || Object.keys(draft).length === 0}
              className="font-mono text-[10px] tracking-[0.1em] uppercase bg-j-accent text-j-bg px-5 py-2 rounded hover:opacity-90 transition-opacity disabled:opacity-40"
            >
              {mutation.isPending ? 'Saving…' : 'Save changes'}
            </button>
            {saved && (
              <span className="font-mono text-[10px] text-j-green">Saved</span>
            )}
            {mutation.error && (
              <span className="font-mono text-[10px] text-j-red">
                {mutation.error instanceof Error ? mutation.error.message : 'Save failed'}
              </span>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
