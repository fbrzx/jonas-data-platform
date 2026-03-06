import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import CataloguePage from './pages/CataloguePage'
import ConnectorsPage from './pages/ConnectorsPage'
import TransformsPage from './pages/TransformsPage'
import ChatPage from './pages/ChatPage'
import LineagePage from './pages/LineagePage'
import DashboardPage from './pages/DashboardPage'
import AuditPage from './pages/AuditPage'
import LoginPage from './pages/LoginPage'
import AcceptInvitePage from './pages/AcceptInvitePage'
import TenantConfigPage from './pages/TenantConfigPage'
import TenantUsersPage from './pages/TenantUsersPage'
import { api, getRoleFromToken, getToken, isLoggedIn } from './lib/api'
import type { ChatMessage } from './lib/api'

const navItems = [
  { to: '/',            label: 'Dashboard',  glyph: '◉', adminOnly: false },
  { to: '/chat',        label: 'Chat',       glyph: '◈', adminOnly: false },
  { to: '/catalogue',   label: 'Catalogue',  glyph: '◫', adminOnly: false },
  { to: '/transforms',  label: 'Transforms', glyph: '⟳', adminOnly: false },
  { to: '/connectors',  label: 'Connectors', glyph: '⌥', adminOnly: false },
  { to: '/lineage',     label: 'Lineage',    glyph: '⬡', adminOnly: false },
  { to: '/audit',       label: 'Audit',      glyph: '◎', adminOnly: false },
  { to: '/team',        label: 'Team',       glyph: '⊛', adminOnly: true  },
  { to: '/settings',   label: 'Settings',   glyph: '⊙', adminOnly: true  },
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

function LogoutButton() {
  const navigate = useNavigate()
  function handleLogout() {
    api.auth.logout()
    navigate('/login', { replace: true })
  }
  return (
    <button
      onClick={handleLogout}
      className="font-mono text-[10px] text-j-dim hover:text-j-red transition-colors"
      title="Sign out"
    >
      sign out
    </button>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  const token = getToken()
  const role = getRoleFromToken(token)
  const isAdmin = role === 'admin'

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
          {navItems.filter(({ adminOnly }) => !adminOnly || isAdmin).map(({ to, label, glyph }) => (
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

        {/* Footer — user + sign out */}
        <div className="px-5 py-4 border-t border-j-border space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-j-green animate-pulse-slow" />
            <span className="font-mono text-[10px] text-j-dim">api · localhost:8000</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px]" style={{ color: 'var(--border-bright)' }}>
              {role} · acme
            </span>
            <LogoutButton />
          </div>
        </div>
      </nav>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden">{children}</main>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

export default function App() {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')

  return (
    <BrowserRouter>
      <TokenWatcher />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/accept-invite" element={<AcceptInvitePage />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <Layout>
                <Routes>
                  <Route index             element={<DashboardPage />} />
                  <Route path="chat"       element={
                    <ChatPage
                      messages={chatMessages}
                      setMessages={setChatMessages}
                      input={chatInput}
                      setInput={setChatInput}
                    />
                  } />
                  <Route path="catalogue"  element={<CataloguePage />} />
                  <Route path="transforms" element={<TransformsPage />} />
                  <Route path="connectors" element={<ConnectorsPage />} />
                  <Route path="lineage"    element={<LineagePage />} />
                  <Route path="audit"      element={<AuditPage />} />
                  <Route path="team"       element={<TenantUsersPage />} />
                  <Route path="settings"   element={<TenantConfigPage />} />
                  <Route path="*"          element={<DashboardPage />} />
                </Routes>
              </Layout>
            </RequireAuth>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
