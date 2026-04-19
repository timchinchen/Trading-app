import { Navigate, Route, Routes } from 'react-router-dom'
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

export default function App() {
  const token = useAuth((s) => s.token)
  if (!token) return <LoginPage />
  return (
    <div className="min-h-screen flex flex-col text-foreground">
      <ModeBanner />
      <Nav />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/agent" element={<AgentPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/symbol/:symbol" element={<SymbolPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
