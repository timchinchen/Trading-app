import { useState } from 'react'
import { api } from '../api/client'
import { PrerequisitesPanel } from '../components/PrerequisitesPanel'
import { useAuth } from '../store/auth'

export function LoginPage() {
  const { setAuth } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    setLoading(true)
    try {
      if (mode === 'register') {
        await api.post('/auth/register', { email, password })
      }
      const form = new URLSearchParams()
      form.append('username', email)
      form.append('password', password)
      const res = await api.post('/auth/login', form, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
      setAuth(res.data.access_token, res.data.mode)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative">
      <PrerequisitesPanel />
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 panel p-8"
      >
        <div className="text-center mb-2">
          <h1 className="text-3xl font-semibold tracking-tight text-transparent bg-clip-text bg-cosmic-text">
            Trading
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Personal trading & signals — paper by default
          </p>
        </div>
        <div className="flex gap-1 p-1 bg-muted/40 rounded-lg">
          <button
            type="button"
            onClick={() => setMode('login')}
            className={`flex-1 py-1.5 text-sm rounded-md transition-all ${
              mode === 'login'
                ? 'bg-primary/20 text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => setMode('register')}
            className={`flex-1 py-1.5 text-sm rounded-md transition-all ${
              mode === 'register'
                ? 'bg-primary/20 text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Register
          </button>
        </div>
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Email</label>
          <input
            required
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full bg-input-bg border border-border text-foreground placeholder:text-muted-foreground px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Password</label>
          <input
            required
            type="password"
            placeholder="min 6 chars"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-input-bg border border-border text-foreground placeholder:text-muted-foreground px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        {err && (
          <div className="text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2">
            {err}
          </div>
        )}
        <button
          disabled={loading}
          className="btn-primary w-full py-2.5 rounded-lg"
        >
          {loading ? '...' : mode === 'login' ? 'Login' : 'Register & Login'}
        </button>
      </form>
    </div>
  )
}
