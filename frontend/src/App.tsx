import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ModeBanner } from './components/ModeBanner'
import { Nav } from './components/Nav'
import { AgentPage } from './pages/Agent'
import { ChatPage } from './pages/Chat'
import { DashboardPage } from './pages/Dashboard'
import { LoginPage } from './pages/Login'
import { OrdersPage } from './pages/Orders'
import { SettingsPage } from './pages/Settings'
import { SymbolPage } from './pages/Symbol'
import { useAuth } from './store/auth'

function RouteBoundary({ children, label }: { children: React.ReactNode; label: string }) {
  // Re-key the boundary on pathname so a crash on /symbol/AAPL doesn't
  // keep showing the fallback after the user navigates elsewhere.
  const { pathname } = useLocation()
  return (
    <ErrorBoundary key={pathname} label={label}>
      {children}
    </ErrorBoundary>
  )
}

export default function App() {
  const token = useAuth((s) => s.token)
  if (!token) return <LoginPage />
  return (
    <div className="min-h-screen flex flex-col text-foreground">
      <ModeBanner />
      <Nav />
      <main className="flex-1">
        <Routes>
          <Route
            path="/"
            element={<RouteBoundary label="Dashboard"><DashboardPage /></RouteBoundary>}
          />
          <Route
            path="/agent"
            element={<RouteBoundary label="Agent"><AgentPage /></RouteBoundary>}
          />
          <Route
            path="/chat"
            element={<RouteBoundary label="Chat"><ChatPage /></RouteBoundary>}
          />
          <Route
            path="/orders"
            element={<RouteBoundary label="Orders"><OrdersPage /></RouteBoundary>}
          />
          <Route
            path="/settings"
            element={<RouteBoundary label="Settings"><SettingsPage /></RouteBoundary>}
          />
          <Route
            path="/symbol/:symbol"
            element={<RouteBoundary label="Symbol detail"><SymbolPage /></RouteBoundary>}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
