import { useState, type ReactNode } from 'react'

interface Props {
  label: string
  title: string
  children: ReactNode // filter controls
}

export default function PageHeader({ label, title, children }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mb-5 pb-4 border-b border-j-border">
      <div className="flex items-start justify-between gap-4">
        <div className="shrink-0">
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mb-1">{label}</div>
          <h2 className="text-j-bright font-semibold">{title}</h2>
        </div>

        {/* Desktop: inline filters */}
        <div className="hidden md:flex items-center gap-2 flex-wrap justify-end">
          {children}
        </div>

        {/* Mobile: hamburger toggle */}
        <button
          onClick={() => setOpen(!open)}
          className="md:hidden shrink-0 font-mono text-[10px] text-j-dim hover:text-j-accent border border-j-border hover:border-j-accent w-8 h-8 flex items-center justify-center rounded transition-colors"
          aria-label="Toggle filters"
        >
          {open ? '✕' : '☰'}
        </button>
      </div>

      {/* Mobile: expanded filter panel */}
      {open && (
        <div className="md:hidden mt-3 flex items-center gap-2 flex-wrap">
          {children}
        </div>
      )}
    </div>
  )
}
