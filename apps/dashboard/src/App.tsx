import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ToastProvider } from './lib/toast'
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
import DashboardsPage from './pages/DashboardsPage'
import CollectionsPage from './pages/CollectionsPage'
import QueryWorkbenchPage from './pages/QueryWorkbenchPage'
import { api, getRoleFromToken, getToken, isLoggedIn } from './lib/api'
import type { ChatMessage } from './lib/api'

const navItems = [
  { to: '/',            label: 'Overview',   glyph: '◉', adminOnly: false },
  { to: '/chat',        label: 'Chat',       glyph: '◈', adminOnly: false },
  { to: '/query',       label: 'Workbench',  glyph: '⌗', adminOnly: false },
  { to: '/collections', label: 'Collections', glyph: '◧', adminOnly: false },
  { to: '/catalogue',   label: 'Catalogue',  glyph: '◫', adminOnly: false },
  { to: '/transforms',  label: 'Transforms', glyph: '⟳', adminOnly: false },
  { to: '/connectors',  label: 'Connectors', glyph: '⌥', adminOnly: false },
  { to: '/lineage',     label: 'Lineage',    glyph: '⬡', adminOnly: false },
  { to: '/dashboards',  label: 'Dashboards', glyph: '▦', adminOnly: false },
  { to: '/audit',       label: 'Audit',      glyph: '◎', adminOnly: false },
  { to: '/team',        label: 'Team',       glyph: '⊛', adminOnly: true  },
  { to: '/settings',    label: 'Settings',   glyph: '⊙', adminOnly: true  },
]

const ROUTE_LABELS: Record<string, string> = {
  '/':            'Overview',
  '/chat':        'Chat with Jonas',
  '/query':       'Query Workbench',
  '/collections': 'Collections',
  '/catalogue':   'Catalogue',
  '/transforms':  'Transforms',
  '/connectors':  'Connectors',
  '/lineage':     'Data Lineage',
  '/dashboards':  'Dashboards',
  '/audit':       'Audit',
  '/team':        'Team',
  '/settings':    'Settings',
}

const ROLE_BADGE: Record<string, string> = {
  admin:   'text-j-purple border-j-purple bg-j-purple-dim',
  analyst: 'text-j-accent border-j-accent bg-j-accent-dim',
  viewer:  'text-j-dim   border-j-border  bg-j-surface2',
}

const SIDEBAR_KEY = 'jonas_sidebar_open'

function useCurrentUser() {
  return useQuery({
    queryKey: ['current-user'],
    queryFn: api.auth.me,
    staleTime: 5 * 60_000,
    retry: false,
    enabled: isLoggedIn(),
  })
}

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
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    if (window.innerWidth < 768) return false
    try { return localStorage.getItem(SIDEBAR_KEY) !== 'false' } catch { return true }
  })

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const handler = (e: MediaQueryListEvent) => { if (e.matches) setSidebarOpen(false) }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  const navigate = useNavigate()
  const location = useLocation()
  const token = getToken()
  const role = getRoleFromToken(token)
  const isAdmin = role === 'admin'
  const { data: currentUser } = useCurrentUser()

  const pageTitle = ROUTE_LABELS[location.pathname] ?? 'Jonas'
  const displayEmail = currentUser?.email ?? ''
  const tenantId = currentUser?.tenant_id ?? 'acme'

  function toggleSidebar() {
    setSidebarOpen((prev) => {
      const next = !prev
      try { localStorage.setItem(SIDEBAR_KEY, String(next)) } catch { /* */ }
      return next
    })
  }

  function handleLogout() {
    api.auth.logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen bg-j-bg overflow-hidden">

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <nav
        className={`${sidebarOpen ? 'w-52' : 'w-14'} shrink-0 flex flex-col border-r border-j-border transition-[width] duration-200`}
        style={{ background: 'linear-gradient(180deg, #0d1117 0%, #0a0c10 100%)' }}
      >
        {/* Tenant name + collapse toggle */}
        <div
          className={`h-10 flex items-center border-b border-j-border grid-bg cursor-pointer select-none group
            ${sidebarOpen ? 'px-5 gap-3' : 'justify-center px-3'}`}
          onClick={toggleSidebar}
          title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          <div className="font-mono font-semibold text-j-bright tracking-widest text-sm shrink-0 uppercase truncate">
            {sidebarOpen ? tenantId : tenantId.slice(0, 1).toUpperCase()}
          </div>
          {sidebarOpen && (
            <span className="font-mono text-[11px] text-j-dim group-hover:text-j-accent transition-colors shrink-0 ml-auto">‹</span>
          )}
        </div>

        {/* Nav items */}
        <ul className="flex-1 py-2 overflow-y-auto">
          {navItems.filter(({ adminOnly }) => !adminOnly || isAdmin).map(({ to, label, glyph }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                title={!sidebarOpen ? label : undefined}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 py-2.5 font-mono text-[11px] font-medium
                   tracking-[0.12em] uppercase transition-all duration-150 border-l-2
                   ${sidebarOpen ? 'px-5' : 'px-0 justify-center'} ${
                    isActive
                      ? 'text-j-accent bg-j-accent-dim border-j-accent'
                      : 'text-j-dim hover:text-j-text hover:bg-j-surface border-transparent'
                  }`
                }
              >
                <span className="opacity-70 text-base leading-none shrink-0">{glyph}</span>
                {sidebarOpen && label}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* Sidebar footer */}
        <div className={`h-9 shrink-0 border-t border-j-border flex items-center ${sidebarOpen ? 'px-5 gap-2' : 'justify-center'}`}>
          <span className="w-1.5 h-1.5 rounded-full bg-j-green animate-pulse-slow shrink-0" />
          {sidebarOpen && (
            <span className="font-mono text-[10px] text-j-dim truncate">api · localhost:8000</span>
          )}
        </div>
      </nav>

      {/* ── Content column ──────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* Global top header */}
        <header className="shrink-0 h-10 flex items-center gap-3 px-4 border-b border-j-border bg-j-surface">
          {/* Expand button (only shown when sidebar collapsed) */}
          {!sidebarOpen && (
            <button
              onClick={toggleSidebar}
              className="font-mono text-[11px] text-j-dim hover:text-j-accent transition-colors shrink-0"
              title="Expand sidebar"
            >
              ›
            </button>
          )}

          {/* Page title */}
          <span className="font-mono text-[11px] font-medium text-j-bright tracking-wide truncate flex-1">
            {pageTitle}
          </span>

          {/* User info */}
          <div className="flex items-center gap-2.5 shrink-0 font-mono text-[10px]">
            {displayEmail && (
              <span className="text-j-dim hidden lg:block truncate max-w-[180px]">{displayEmail}</span>
            )}
            <span className={`px-1.5 py-0.5 rounded border ${ROLE_BADGE[role] ?? ROLE_BADGE.viewer}`}>
              {role}
            </span>
            <button
              onClick={handleLogout}
              className="text-j-dim hover:text-j-red transition-colors"
              title="Sign out"
            >
              sign out
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 flex flex-col overflow-hidden">{children}</main>

        {/* Page footer */}
        <footer className="shrink-0 h-9 flex items-center justify-center border-t border-j-border bg-j-surface">
          <span className="font-mono text-[9px] text-j-border tracking-[0.14em] uppercase text-j-bright">Jonas Data Platform</span>
        </footer>
      </div>
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
      <ToastProvider>
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
                  <Route path="query"       element={<QueryWorkbenchPage />} />
                  <Route path="collections" element={<CollectionsPage />} />
                  <Route path="catalogue"   element={<CataloguePage />} />
                  <Route path="transforms" element={<TransformsPage />} />
                  <Route path="connectors" element={<ConnectorsPage />} />
                  <Route path="lineage"    element={<LineagePage />} />
                  <Route path="dashboards" element={<DashboardsPage />} />
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
      </ToastProvider>
    </BrowserRouter>
  )
}
