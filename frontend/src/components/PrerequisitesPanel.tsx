import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { APP_VERSION } from '../version'

/**
 * Setup/prerequisites dock shown only on the Login page. Fixed bottom-left,
 * collapsible, polls the public /health/setup endpoint every 10s so you can
 * watch the dots go green as you configure a fresh box.
 *
 * Deliberately self-contained: no auth, no react-query, no shared store.
 * The Login page mounts it as a sibling of the form.
 */

type Probe = { ok: boolean; detail?: string }
type Health = Record<string, Probe>

type RowKind = 'required' | 'optional'

const ROWS: { key: string; label: string; kind: RowKind }[] = [
  { key: 'backend', label: 'Backend', kind: 'required' },
  { key: 'db', label: 'Database', kind: 'required' },
  { key: 'jwt_secret', label: 'JWT secret', kind: 'required' },
  { key: 'alpaca', label: 'Alpaca', kind: 'required' },
  { key: 'ollama', label: 'Ollama (local LLM)', kind: 'optional' },
  { key: 'openai', label: 'OpenAI key', kind: 'optional' },
  { key: 'huggingface', label: 'Hugging Face key', kind: 'optional' },
  { key: 'cohere', label: 'Cohere key', kind: 'optional' },
  { key: 'playwright', label: 'Playwright chromium', kind: 'optional' },
  { key: 'fmp', label: 'FMP (fundamentals)', kind: 'optional' },
  { key: 'stocktwits', label: 'Stocktwits cookies', kind: 'optional' },
]

function Dot({ ok, kind }: { ok: boolean; kind: RowKind }) {
  if (ok) {
    return (
      <span
        aria-label="green"
        className="inline-block w-2.5 h-2.5 rounded-full bg-success shadow-[0_0_8px_rgba(34,197,94,0.6)]"
      />
    )
  }
  if (kind === 'optional') {
    return (
      <span
        aria-label="grey"
        className="inline-block w-2.5 h-2.5 rounded-full border border-border bg-transparent"
      />
    )
  }
  return (
    <span
      aria-label="red"
      className="inline-block w-2.5 h-2.5 rounded-full bg-destructive shadow-[0_0_8px_rgba(239,68,68,0.6)]"
    />
  )
}

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async (e) => {
        e.stopPropagation()
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        } catch {
          // swallow - insecure origins block clipboard
        }
      }}
      className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground hover:text-primary hover:border-primary/40"
      title="Copy to clipboard"
    >
      {copied ? 'copied' : 'copy'}
    </button>
  )
}

function Step({ n, label, cmd }: { n: number; label: string; cmd?: string }) {
  return (
    <li className="flex gap-2 items-start py-1">
      <span className="text-[10px] text-muted-foreground mt-0.5 font-mono">{n}.</span>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-foreground">{label}</div>
        {cmd && (
          <div className="flex items-center gap-2 mt-0.5">
            <code className="text-[10px] text-primary font-mono truncate max-w-[260px]">
              {cmd}
            </code>
            <CopyBtn text={cmd} />
          </div>
        )}
      </div>
    </li>
  )
}

const REQUIRED_ENV = `APP_MODE=paper
ALPACA_PAPER_KEY=
ALPACA_PAPER_SECRET=
JWT_SECRET=
CORS_ORIGIN=http://localhost:5173`

const OPTIONAL_ENV = `AGENT_ENABLED=false
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OPENAI_API_KEY=
HUGGINGFACE_API_KEY=
HUGGINGFACE_MODEL=mistralai/Mistral-7B-Instruct-v0.3
COHERE_API_KEY=
COHERE_MODEL=command-r-08-2024
FMP_API_KEY=
SEC_USER_AGENT=YourApp (personal) you@example.com
TWITTER_ACCOUNTS=PeterLBrandt,LindaRaschke`

export function PrerequisitesPanel() {
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem('prereqsCollapsed') !== '1'
    } catch {
      return true
    }
  })
  const [health, setHealth] = useState<Health | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem('prereqsCollapsed', open ? '0' : '1')
    } catch {
      // ignore
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    const load = async () => {
      try {
        const r = await api.get('/health/setup')
        if (!cancelled) {
          setHealth(r.data)
          setErr(null)
        }
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || 'health check failed')
      }
    }
    load()
    pollRef.current = window.setInterval(load, 10000)
    return () => {
      cancelled = true
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [open])

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed top-4 left-4 z-40 px-3 py-2 rounded-lg panel text-xs text-muted-foreground hover:text-primary border border-border-strong"
        title="Show prerequisites / setup guide"
      >
        Prerequisites & setup
      </button>
    )
  }

  return (
    <aside
      className="fixed top-4 left-4 z-40 panel p-4 w-[360px] max-h-[calc(100vh-2rem)] overflow-auto text-xs space-y-3 border border-border-strong"
      style={{ boxShadow: '0 8px 32px -12px rgba(0,0,0,0.6)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Prerequisites & setup
          </h3>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border text-muted-foreground">
            v{APP_VERSION}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Collapse"
        >
          ×
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground -mt-1">
        Deploy this app on a fresh machine. Follow the steps, then watch the
        health dots flip green.
      </p>

      <section>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
          1. Requirements
        </div>
        <ul className="list-disc pl-5 text-[11px] space-y-0.5">
          <li>Python 3.11+ and Node 18+</li>
          <li>
            Alpaca account:{' '}
            <a
              className="text-primary hover:underline"
              href="https://alpaca.markets/"
              target="_blank"
              rel="noreferrer"
            >
              alpaca.markets
            </a>{' '}
            (free paper trading)
          </li>
          <li className="text-muted-foreground">
            Optional: Ollama (local LLM), OpenAI key, FMP key, Stocktwits cookies
          </li>
        </ul>
      </section>

      <section>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
          2. Get Alpaca keys
        </div>
        <ul className="list-disc pl-5 text-[11px] space-y-0.5">
          <li>
            Paper:{' '}
            <a
              className="text-primary hover:underline"
              href="https://app.alpaca.markets/paper/dashboard/overview"
              target="_blank"
              rel="noreferrer"
            >
              paper dashboard
            </a>{' '}
            → "View API Keys"
          </li>
          <li>
            Live:{' '}
            <a
              className="text-primary hover:underline"
              href="https://app.alpaca.markets/brokerage/dashboard/overview"
              target="_blank"
              rel="noreferrer"
            >
              brokerage dashboard
            </a>{' '}
            → "View API Keys"
          </li>
          <li className="text-muted-foreground">
            Paper keys are free and unfunded; start there.
          </li>
        </ul>
      </section>

      <section>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 flex items-center justify-between">
          <span>3. Required env vars</span>
          <CopyBtn text={REQUIRED_ENV} />
        </div>
        <pre className="bg-background-soft border border-border rounded p-2 font-mono text-[10px] leading-snug overflow-auto">
          {REQUIRED_ENV}
        </pre>
        <details className="mt-1">
          <summary className="cursor-pointer text-muted-foreground text-[11px]">
            optional env vars (agent, LLMs, enrichment)
          </summary>
          <div className="flex justify-end mt-1">
            <CopyBtn text={OPTIONAL_ENV} />
          </div>
          <pre className="bg-background-soft border border-border rounded p-2 font-mono text-[10px] leading-snug overflow-auto mt-1">
            {OPTIONAL_ENV}
          </pre>
        </details>
      </section>

      <section>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
          4. Setup
        </div>
        <ol className="pl-0">
          <Step n={1} label="Clone the repo" cmd="git clone https://github.com/timchinchen/Trading-app.git && cd Trading-app" />
          <Step n={2} label="Backend venv + deps" cmd="cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" />
          <Step n={3} label="Fill .env (Alpaca + JWT)" cmd="cp .env.example .env" />
          <Step n={4} label="Run backend" cmd=".venv/bin/uvicorn app.main:app --reload" />
          <Step n={5} label="Frontend deps + dev server" cmd="cd ../frontend && npm install && npm run dev" />
          <Step n={6} label="Open the UI, register, log in" cmd="open http://localhost:5173" />
        </ol>
      </section>

      <section>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
          5. Health check
        </div>
        {err && (
          <div className="text-[11px] text-destructive mb-1">
            {err} - is the backend running on :8000?
          </div>
        )}
        {!health && !err && (
          <div className="text-[11px] text-muted-foreground">checking...</div>
        )}
        {health && (
          <ul className="space-y-1">
            {ROWS.map((r) => {
              const p: Probe = health[r.key] || { ok: false }
              return (
                <li
                  key={r.key}
                  className="flex items-center gap-2 text-[11px]"
                  title={p.detail || ''}
                >
                  <Dot ok={!!p.ok} kind={r.kind} />
                  <span className="min-w-[120px]">{r.label}</span>
                  <span className="text-muted-foreground truncate flex-1">
                    {p.detail || (p.ok ? 'ok' : r.kind === 'optional' ? '-' : 'not ready')}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
        <div className="text-[10px] text-muted-foreground mt-2">
          <span className="inline-block w-2 h-2 rounded-full bg-success mr-1" />
          ready
          <span className="inline-block w-2 h-2 rounded-full bg-destructive ml-3 mr-1" />
          needs attention
          <span className="inline-block w-2 h-2 rounded-full border border-border ml-3 mr-1" />
          optional
        </div>
      </section>

      <section className="flex items-center justify-between text-[11px] pt-1 border-t border-border">
        <a
          href="https://github.com/timchinchen/Trading-app#readme"
          target="_blank"
          rel="noreferrer"
          className="text-primary hover:underline"
        >
          Full README
        </a>
        <a
          href={`https://github.com/timchinchen/Trading-app/releases/tag/v${APP_VERSION}`}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-primary font-mono"
        >
          v{APP_VERSION}
        </a>
      </section>
    </aside>
  )
}
