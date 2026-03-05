import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import CataloguePage from './pages/CataloguePage'
import IntegrationsPage from './pages/IntegrationsPage'
import TransformsPage from './pages/TransformsPage'
import ChatPage from './pages/ChatPage'
import LineagePage from './pages/LineagePage'
import DashboardPage from './pages/DashboardPage'
import type { ChatMessage } from './lib/api'

const navItems = [
  { to: '/',             label: 'Dashboard',    glyph: '◉' },
  { to: '/chat',         label: 'Chat',         glyph: '◈' },
  { to: '/catalogue',   label: 'Catalogue',    glyph: '◫' },
  { to: '/transforms',  label: 'Transforms',   glyph: '⟳' },
  { to: '/integrations',label: 'Integrations', glyph: '⌥' },
  { to: '/lineage',     label: 'Lineage',      glyph: '⬡' },
]

function TokenWatcher() {
  const queryClient = useQueryClient()
  useEffect(() => {
    const handler = () => queryClient.invalidateQueries()
    window.addEventListener('jonas_token_changed', handler)
    return () => window.removeEventListener('jonas_token_changed', handler)
  }, [queryClient])
  return null
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen bg-j-bg overflow-hidden">
      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <nav
        className="w-52 shrink-0 flex flex-col border-r border-j-border"
        style={{ background: 'linear-gradient(180deg, #0d1117 0%, #0a0c10 100%)' }}
      >
        {/* Logo */}
        <div className="px-5 py-5 border-b border-j-border grid-bg">
          <div className="font-mono font-semibold text-j-bright tracking-widest text-sm">
            JONAS
          </div>
          <div className="font-mono text-[10px] text-j-dim tracking-[0.18em] uppercase mt-0.5">
            Data Platform
          </div>
        </div>

        {/* Nav items */}
        <ul className="flex-1 py-2">
          {navItems.map(({ to, label, glyph }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-5 py-2.5 font-mono text-[11px] font-medium
                   tracking-[0.12em] uppercase transition-all duration-150 border-l-2 ${
                    isActive
                      ? 'text-j-accent bg-j-accent-dim border-j-accent'
                      : 'text-j-dim hover:text-j-text hover:bg-j-surface border-transparent'
                  }`
                }
              >
                <span className="opacity-60 text-base leading-none">{glyph}</span>
                {label}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* Footer status */}
        <div className="px-5 py-4 border-t border-j-border">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-j-green animate-pulse-slow" />
            <span className="font-mono text-[10px] text-j-dim">api · localhost:8000</span>
          </div>
          <div className="font-mono text-[10px] mt-1" style={{ color: 'var(--border-bright)' }}>
            tenant / acme · v0.1.0
          </div>
        </div>
      </nav>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden">{children}</main>
    </div>
  )
}

export default function App() {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')

  return (
    <BrowserRouter>
      <TokenWatcher />
      <Routes>
        <Route
          path="/*"
          element={
            <Layout>
              <Routes>
                <Route index             element={<DashboardPage />} />
                <Route path="chat"         element={
                  <ChatPage
                    messages={chatMessages}
                    setMessages={setChatMessages}
                    input={chatInput}
                    setInput={setChatInput}
                  />
                } />
                <Route path="catalogue"   element={<CataloguePage />} />
                <Route path="transforms"  element={<TransformsPage />} />
                <Route path="integrations" element={<IntegrationsPage />} />
                <Route path="lineage"     element={<LineagePage />} />
                <Route path="*"           element={<DashboardPage />} />
              </Routes>
            </Layout>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
