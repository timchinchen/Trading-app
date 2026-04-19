import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'

const TABS: { to: string; label: string }[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/agent', label: 'Agent' },
  { to: '/chat', label: 'Chat' },
  { to: '/orders', label: 'Orders' },
  { to: '/settings', label: 'Settings' },
]

export function Nav() {
  const loc = useLocation()
  const { logout, mode } = useAuth()

  const isActive = (to: string) =>
    to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(to)

  return (
    <header
      className="border-b border-border-strong bg-background/70 backdrop-blur-xl sticky top-0 z-30"
      style={{
        boxShadow: '0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.5)',
      }}
    >
      <div className="flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          <span className="font-semibold tracking-tight text-transparent bg-clip-text bg-cosmic-text text-lg">
            Trading
          </span>
          <nav className="flex gap-1">
            {TABS.map((t) => {
              const active = isActive(t.to)
              return (
                <Link
                  key={t.to}
                  to={t.to}
                  className={`px-4 py-2 rounded-lg text-sm transition-all ${
                    active
                      ? 'bg-primary/20 text-primary shadow-[inset_0_0_0_1px_rgba(230,106,138,0.55),0_4px_16px_-8px_rgba(230,106,138,0.45)]'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'
                  }`}
                >
                  {t.label}
                </Link>
              )
            })}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-3 py-1.5 rounded-md bg-muted border border-border-strong text-xs text-muted-foreground">
            mode: <span className="text-foreground font-medium">{mode}</span>
          </span>
          <button onClick={logout} className="btn-secondary px-3 py-1.5 rounded-md text-xs">
            logout
          </button>
        </div>
      </div>
    </header>
  )
}
