import { useEffect, useMemo, useState } from 'react'
import {
  useAccount,
  useAgentAccountsCache,
  useAgentSettings,
  useAgentStatus,
  useAutoSellPreview,
  useAutoSellRunNow,
  useMode,
  useUpdateAgentSettings,
} from '../api/hooks'
import type { AgentSettings, AgentSettingsUpdate } from '../api/types'
import { APP_VERSION } from '../version'

function Row({
  label,
  value,
  hint,
}: {
  label: string
  value: React.ReactNode
  hint?: string
}) {
  return (
    <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border last:border-b-0">
      <div className="text-xs text-muted-foreground uppercase tracking-wider">
        {label}
      </div>
      <div>
        <div className="text-sm">{value}</div>
        {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
      </div>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel p-6 space-y-2">
      <h3 className="text-sm text-muted-foreground uppercase tracking-wider mb-2">
        {title}
      </h3>
      {children}
    </section>
  )
}

function OverrideBadge({
  k,
  overridden,
}: {
  k: string
  overridden: string[]
}) {
  const isOverridden = overridden.includes(k)
  return (
    <span
      className={`inline-block ml-2 px-1.5 py-0.5 text-[10px] rounded border ${
        isOverridden
          ? 'border-primary/40 text-primary bg-primary/10'
          : 'border-border text-muted-foreground'
      }`}
      title={
        isOverridden
          ? 'Saved in DB - overrides .env'
          : 'Using .env default - not yet customised'
      }
    >
      {isOverridden ? 'override' : '.env default'}
    </span>
  )
}

// ----- LLM provider section (editable) -----
function LLMProviderCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [provider, setProvider] = useState(s.llm_provider)
  const [ollamaHost, setOllamaHost] = useState(s.ollama_host)
  const [ollamaModel, setOllamaModel] = useState(s.ollama_model)
  const [openaiKey, setOpenaiKey] = useState('') // empty = leave existing
  const [clearOpenaiKey, setClearOpenaiKey] = useState(false)
  const [openaiModel, setOpenaiModel] = useState(s.openai_model)
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState(s.openai_base_url)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  // Re-sync when server data changes (e.g. after another tab saved).
  useEffect(() => {
    setProvider(s.llm_provider)
    setOllamaHost(s.ollama_host)
    setOllamaModel(s.ollama_model)
    setOpenaiModel(s.openai_model)
    setOpenaiBaseUrl(s.openai_base_url)
  }, [s])

  const save = () => {
    const body: AgentSettingsUpdate = {
      LLM_PROVIDER: provider,
      OLLAMA_HOST: ollamaHost,
      OLLAMA_MODEL: ollamaModel,
      OPENAI_MODEL: openaiModel,
      OPENAI_BASE_URL: openaiBaseUrl,
    }
    if (clearOpenaiKey) {
      body.OPENAI_API_KEY = ''
    } else if (openaiKey.trim()) {
      body.OPENAI_API_KEY = openaiKey.trim()
    }
    upd.mutate(body, {
      onSuccess: () => {
        setOpenaiKey('')
        setClearOpenaiKey(false)
        setSavedAt(Date.now())
      },
    })
  }

  return (
    <Card title="LLM provider (editable)">
      <p className="text-xs text-muted-foreground mb-4">
        Switch between local Ollama and hosted OpenAI. Saved here, persisted in the
        SQLite DB, used by the next agent run and the Chat page immediately - no
        restart needed.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          PROVIDER
          <OverrideBadge k="LLM_PROVIDER" overridden={s.overridden} />
        </div>
        <div className="flex items-center gap-2">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as 'ollama' | 'openai')}
            className="px-3 py-2 rounded-md text-sm w-48"
          >
            <option value="ollama">Ollama (local)</option>
            <option value="openai">OpenAI (hosted)</option>
          </select>
          <span className="text-xs text-muted-foreground">
            currently active: <code className="text-primary">{s.llm_provider}</code>
          </span>
        </div>
      </div>

      {provider === 'ollama' && (
        <>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OLLAMA_HOST
              <OverrideBadge k="OLLAMA_HOST" overridden={s.overridden} />
            </div>
            <input
              value={ollamaHost}
              onChange={(e) => setOllamaHost(e.target.value)}
              placeholder="http://localhost:11434"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OLLAMA_MODEL
              <OverrideBadge k="OLLAMA_MODEL" overridden={s.overridden} />
            </div>
            <input
              value={ollamaModel}
              onChange={(e) => setOllamaModel(e.target.value)}
              placeholder="llama3.1:8b"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
        </>
      )}

      {provider === 'openai' && (
        <>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OPENAI_API_KEY
              <OverrideBadge k="OPENAI_API_KEY" overridden={s.overridden} />
            </div>
            <div className="space-y-1">
              <input
                type="password"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder={
                  s.openai_api_key_set
                    ? `current: ${s.openai_api_key_preview} (leave blank to keep)`
                    : 'sk-...'
                }
                className="px-3 py-2 rounded-md text-sm w-full max-w-md font-mono"
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={clearOpenaiKey}
                  onChange={(e) => setClearOpenaiKey(e.target.checked)}
                />
                clear stored key (revert to .env / disable OpenAI)
              </label>
              <div className="text-[11px] text-muted-foreground">
                Stored encrypted-at-rest in your local SQLite DB. Never sent anywhere
                except the chosen API endpoint.
              </div>
            </div>
          </div>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OPENAI_MODEL
              <OverrideBadge k="OPENAI_MODEL" overridden={s.overridden} />
            </div>
            <input
              value={openaiModel}
              onChange={(e) => setOpenaiModel(e.target.value)}
              placeholder="gpt-4o-mini"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              OPENAI_BASE_URL
              <OverrideBadge k="OPENAI_BASE_URL" overridden={s.overridden} />
            </div>
            <input
              value={openaiBaseUrl}
              onChange={(e) => setOpenaiBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="px-3 py-2 rounded-md text-sm w-full max-w-md"
            />
          </div>
        </>
      )}

      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save LLM settings'}
        </button>
        {savedAt && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
        {upd.isError && (
          <span className="text-xs text-destructive">
            failed: {(upd.error as any)?.message ?? 'see console'}
          </span>
        )}
      </div>
    </Card>
  )
}

// ----- Deep Analysis LLM (advisor / portfolio recommender) -----
function DeepAnalysisLLMCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [enabled, setEnabled] = useState(s.deep_llm_enabled)
  const [provider, setProvider] = useState<'ollama' | 'openai'>(
    (s.deep_llm_provider || 'openai') as 'ollama' | 'openai',
  )
  const [ollamaHost, setOllamaHost] = useState(s.deep_llm_ollama_host)
  const [ollamaModel, setOllamaModel] = useState(s.deep_llm_ollama_model)
  const [openaiModel, setOpenaiModel] = useState(s.deep_llm_openai_model)
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState(s.deep_llm_openai_base_url)
  const [openaiKey, setOpenaiKey] = useState('')
  const [clearOpenaiKey, setClearOpenaiKey] = useState(false)

  useEffect(() => {
    setEnabled(s.deep_llm_enabled)
    setProvider((s.deep_llm_provider || 'openai') as 'ollama' | 'openai')
    setOllamaHost(s.deep_llm_ollama_host)
    setOllamaModel(s.deep_llm_ollama_model)
    setOpenaiModel(s.deep_llm_openai_model)
    setOpenaiBaseUrl(s.deep_llm_openai_base_url)
  }, [s])

  const save = () => {
    const body: AgentSettingsUpdate = {
      DEEP_LLM_ENABLED: enabled,
      DEEP_LLM_PROVIDER: provider,
      DEEP_LLM_OLLAMA_HOST: ollamaHost,
      DEEP_LLM_OLLAMA_MODEL: ollamaModel,
      DEEP_LLM_OPENAI_MODEL: openaiModel,
      DEEP_LLM_OPENAI_BASE_URL: openaiBaseUrl,
    }
    if (clearOpenaiKey) {
      body.DEEP_LLM_OPENAI_API_KEY = ''
    } else if (openaiKey.trim()) {
      body.DEEP_LLM_OPENAI_API_KEY = openaiKey.trim()
    }
    upd.mutate(body, {
      onSuccess: () => {
        setOpenaiKey('')
        setClearOpenaiKey(false)
      },
    })
  }

  return (
    <Card title="Deep Analysis LLM (advisor)">
      <p className="text-xs text-muted-foreground mb-4">
        The advisor is called <strong>once per agent run</strong> to write the
        portfolio recommendation (Portfolio Today / New Ideas / Watchlist / Risk
        notes). You can point it at a different LLM than the one that analyses
        individual tweets — e.g. run Ollama locally for the ~20-60 tweet calls
        per run, then flip this to OpenAI <code className="text-primary">gpt-4o-mini</code>{' '}
        for the big-picture summary. At ~13 runs / trading day that's roughly{' '}
        <strong>$3/year</strong>. Any field left blank inherits from the Agent LLM above.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          ENABLED
          <OverrideBadge k="DEEP_LLM_ENABLED" overridden={s.overridden} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          Use a different LLM for the advisor / deep analysis
        </label>
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          EFFECTIVE
        </div>
        <div className="text-xs text-muted-foreground">
          The next advisor call will use{' '}
          <code className="text-primary">{s.advisor_effective_provider}</code> /{' '}
          <code className="text-primary">{s.advisor_effective_model}</code>
          {!s.deep_llm_enabled && (
            <span> (inherited from Agent LLM — deep LLM disabled).</span>
          )}
        </div>
      </div>

      {enabled && (
        <>
          <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">
              PROVIDER
              <OverrideBadge k="DEEP_LLM_PROVIDER" overridden={s.overridden} />
            </div>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as 'ollama' | 'openai')}
              className="px-3 py-2 rounded-md text-sm w-48"
            >
              <option value="ollama">Ollama (local)</option>
              <option value="openai">OpenAI (hosted)</option>
            </select>
          </div>

          {provider === 'ollama' && (
            <>
              <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
                <div className="text-xs text-muted-foreground uppercase tracking-wider">
                  OLLAMA_HOST
                  <OverrideBadge
                    k="DEEP_LLM_OLLAMA_HOST"
                    overridden={s.overridden}
                  />
                </div>
                <input
                  value={ollamaHost}
                  onChange={(e) => setOllamaHost(e.target.value)}
                  placeholder={`leave blank to reuse Agent host (${s.ollama_host})`}
                  className="px-3 py-2 rounded-md text-sm w-full max-w-md"
                />
              </div>
              <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
                <div className="text-xs text-muted-foreground uppercase tracking-wider">
                  OLLAMA_MODEL
                  <OverrideBadge
                    k="DEEP_LLM_OLLAMA_MODEL"
                    overridden={s.overridden}
                  />
                </div>
                <input
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  placeholder={`leave blank to reuse Agent model (${s.ollama_model})`}
                  className="px-3 py-2 rounded-md text-sm w-full max-w-md"
                />
              </div>
            </>
          )}

          {provider === 'openai' && (
            <>
              <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
                <div className="text-xs text-muted-foreground uppercase tracking-wider">
                  OPENAI_API_KEY
                  <OverrideBadge
                    k="DEEP_LLM_OPENAI_API_KEY"
                    overridden={s.overridden}
                  />
                </div>
                <div className="space-y-1">
                  <input
                    type="password"
                    value={openaiKey}
                    onChange={(e) => setOpenaiKey(e.target.value)}
                    placeholder={
                      s.deep_llm_openai_api_key_set
                        ? `current: ${s.deep_llm_openai_api_key_preview} (leave blank to keep)`
                        : s.openai_api_key_set
                          ? `blank = reuse Agent key (${s.openai_api_key_preview})`
                          : 'sk-...'
                    }
                    className="px-3 py-2 rounded-md text-sm w-full max-w-md font-mono"
                  />
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={clearOpenaiKey}
                      onChange={(e) => setClearOpenaiKey(e.target.checked)}
                    />
                    clear stored key (revert to Agent LLM key)
                  </label>
                </div>
              </div>
              <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
                <div className="text-xs text-muted-foreground uppercase tracking-wider">
                  OPENAI_MODEL
                  <OverrideBadge
                    k="DEEP_LLM_OPENAI_MODEL"
                    overridden={s.overridden}
                  />
                </div>
                <input
                  value={openaiModel}
                  onChange={(e) => setOpenaiModel(e.target.value)}
                  placeholder="gpt-4o-mini"
                  className="px-3 py-2 rounded-md text-sm w-full max-w-md"
                />
              </div>
              <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
                <div className="text-xs text-muted-foreground uppercase tracking-wider">
                  OPENAI_BASE_URL
                  <OverrideBadge
                    k="DEEP_LLM_OPENAI_BASE_URL"
                    overridden={s.overridden}
                  />
                </div>
                <input
                  value={openaiBaseUrl}
                  onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                  placeholder={`leave blank to reuse Agent base (${s.openai_base_url})`}
                  className="px-3 py-2 rounded-md text-sm w-full max-w-md"
                />
              </div>
            </>
          )}
        </>
      )}

      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save deep-analysis settings'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Data enrichment APIs (FMP + SEC EDGAR) -----
function DataEnrichmentCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [fmpKey, setFmpKey] = useState('')
  const [clearFmpKey, setClearFmpKey] = useState(false)
  const [fmpBaseUrl, setFmpBaseUrl] = useState(s.fmp_base_url)
  const [secUa, setSecUa] = useState(s.sec_user_agent)

  useEffect(() => {
    setFmpBaseUrl(s.fmp_base_url)
    setSecUa(s.sec_user_agent)
  }, [s])

  const save = () => {
    const body: AgentSettingsUpdate = {
      FMP_BASE_URL: fmpBaseUrl,
      SEC_USER_AGENT: secUa,
    }
    if (clearFmpKey) {
      body.FMP_API_KEY = ''
    } else if (fmpKey.trim()) {
      body.FMP_API_KEY = fmpKey.trim()
    }
    upd.mutate(body, {
      onSuccess: () => {
        setFmpKey('')
        setClearFmpKey(false)
      },
    })
  }

  return (
    <Card title="Data enrichment APIs (editable)">
      <p className="text-xs text-muted-foreground mb-4">
        Per-ticker fundamentals + filings data used to corroborate Twitter signals.
        The agent enriches only the shortlist of tickers it wants to trade each run,
        so the free tiers are plenty.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          FMP_API_KEY
          <OverrideBadge k="FMP_API_KEY" overridden={s.overridden} />
        </div>
        <div className="space-y-1">
          <input
            type="password"
            value={fmpKey}
            onChange={(e) => setFmpKey(e.target.value)}
            placeholder={
              s.fmp_api_key_set
                ? `current: ${s.fmp_api_key_preview} (leave blank to keep)`
                : 'Financial Modeling Prep API key'
            }
            className="px-3 py-2 rounded-md text-sm w-full max-w-md font-mono"
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={clearFmpKey}
              onChange={(e) => setClearFmpKey(e.target.checked)}
            />
            clear stored key (disables FMP enrichment)
          </label>
          <div className="text-[11px] text-muted-foreground">
            Free key at{' '}
            <a
              href="https://site.financialmodelingprep.com/register"
              target="_blank"
              rel="noreferrer"
              className="text-primary hover:underline"
            >
              financialmodelingprep.com/register
            </a>{' '}
            (250 calls/day free tier). Pulls quote + profile + ratios-ttm per ticker.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          FMP_BASE_URL
          <OverrideBadge k="FMP_BASE_URL" overridden={s.overridden} />
        </div>
        <input
          value={fmpBaseUrl}
          onChange={(e) => setFmpBaseUrl(e.target.value)}
          placeholder="https://financialmodelingprep.com/api/v3"
          className="px-3 py-2 rounded-md text-sm w-full max-w-md"
        />
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          SEC_USER_AGENT
          <OverrideBadge k="SEC_USER_AGENT" overridden={s.overridden} />
        </div>
        <div className="space-y-1">
          <input
            value={secUa}
            onChange={(e) => setSecUa(e.target.value)}
            placeholder="YourApp (personal) you@email.com"
            className="px-3 py-2 rounded-md text-sm w-full max-w-md"
          />
          <div className="text-[11px] text-muted-foreground">
            SEC EDGAR full-text search is free but requires a User-Agent identifying
            you (name + contact email). No API key.
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save enrichment settings'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Stocktwits session cookies (editable) -----
function StocktwitsCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [cookies, setCookies] = useState('')
  const [clearCookies, setClearCookies] = useState(false)

  const save = () => {
    const body: AgentSettingsUpdate = {}
    if (clearCookies) {
      body.STOCKTWITS_COOKIES = ''
    } else if (cookies.trim()) {
      body.STOCKTWITS_COOKIES = cookies.trim()
    } else {
      return
    }
    upd.mutate(body, {
      onSuccess: () => {
        setCookies('')
        setClearCookies(false)
      },
    })
  }

  return (
    <Card title="Stocktwits session (editable)">
      <p className="text-xs text-muted-foreground mb-4">
        Stocktwits is behind Cloudflare, so the agent drives headless Chromium
        using your own logged-in browser cookies. Paste either a JSON dict (
        <code className="text-primary">{`{"name":"value", ...}`}</code>), a JSON
        array of cookie objects, or Netscape cookies.txt content. Cookies are
        stored as a secret and only used by the scraper.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-3 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider">
          STOCKTWITS_COOKIES
          <OverrideBadge k="STOCKTWITS_COOKIES" overridden={s.overridden} />
        </div>
        <div className="space-y-1">
          <textarea
            value={cookies}
            onChange={(e) => setCookies(e.target.value)}
            rows={6}
            placeholder={
              s.stocktwits_cookies_set
                ? `current: ${s.stocktwits_cookies_preview} (leave blank to keep)`
                : '{"stocktwits_session":"...", "csrftoken":"..."}'
            }
            className="px-3 py-2 rounded-md text-sm w-full font-mono"
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={clearCookies}
              onChange={(e) => setClearCookies(e.target.checked)}
            />
            clear stored cookies (disables Stocktwits scraping)
          </label>
          <div className="text-[11px] text-muted-foreground">
            To grab cookies: open stocktwits.com in a logged-in browser, open
            DevTools &rarr; Application &rarr; Cookies &rarr; https://stocktwits.com,
            then copy the rows (any export extension works) or the raw JSON.
            Scraper pulls per-ticker bull/bear sentiment from
            <code className="text-primary"> /symbol/&lt;SYM&gt;</code> and
            headlines from <code className="text-primary">/news-articles</code>.
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save Stocktwits cookies'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Twitter accounts (editable) -----
function TwitterAccountsCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [text, setText] = useState(s.twitter_accounts)
  useEffect(() => setText(s.twitter_accounts), [s.twitter_accounts])

  const handles = useMemo(
    () =>
      text
        .split(/[\s,]+/)
        .map((h) => h.trim().replace(/^@/, ''))
        .filter(Boolean),
    [text],
  )

  const save = () => {
    upd.mutate({ TWITTER_ACCOUNTS: handles.join(',') })
  }

  return (
    <Card title={`Followed X accounts (${handles.length})`}>
      <div className="text-xs text-muted-foreground mb-2">
        Comma- or whitespace-separated list of X handles (no <code>@</code>). Saved
        live - the next agent run picks up the new list.
        <OverrideBadge k="TWITTER_ACCOUNTS" overridden={s.overridden} />
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="PeterLBrandt, LindaRaschke, MarkMinervini"
        className="w-full px-3 py-2 rounded-md text-sm font-mono"
      />
      <div className="flex items-center gap-3 pt-3">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save handles'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Agent budget / cadence (editable) -----
function AgentBudgetCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [enabled, setEnabled] = useState(s.agent_enabled)
  const [autoLive, setAutoLive] = useState(s.agent_auto_execute_live)
  const [budget, setBudget] = useState(s.agent_budget_usd)
  const [weekly, setWeekly] = useState(s.agent_weekly_budget_usd)
  const [minPos, setMinPos] = useState(s.agent_min_position_usd)
  const [maxPos, setMaxPos] = useState(s.agent_max_position_usd)
  const [dailyLoss, setDailyLoss] = useState(s.agent_daily_loss_cap_usd)
  const [maxOpen, setMaxOpen] = useState(s.agent_max_open_positions)
  const [cron, setCron] = useState(s.agent_cron_minutes)
  const [intelBoost, setIntelBoost] = useState(s.agent_intel_boost)
  const [takeProfit, setTakeProfit] = useState(s.agent_take_profit_pct)
  const [recentWindow, setRecentWindow] = useState(s.agent_recent_trade_window_hours)

  useEffect(() => {
    setEnabled(s.agent_enabled)
    setAutoLive(s.agent_auto_execute_live)
    setBudget(s.agent_budget_usd)
    setWeekly(s.agent_weekly_budget_usd)
    setMinPos(s.agent_min_position_usd)
    setMaxPos(s.agent_max_position_usd)
    setDailyLoss(s.agent_daily_loss_cap_usd)
    setMaxOpen(s.agent_max_open_positions)
    setCron(s.agent_cron_minutes)
    setIntelBoost(s.agent_intel_boost)
    setTakeProfit(s.agent_take_profit_pct)
    setRecentWindow(s.agent_recent_trade_window_hours)
  }, [s])

  const save = () => {
    upd.mutate({
      AGENT_ENABLED: enabled,
      AGENT_AUTO_EXECUTE_LIVE: autoLive,
      AGENT_BUDGET_USD: Number(budget),
      AGENT_WEEKLY_BUDGET_USD: Number(weekly),
      AGENT_MIN_POSITION_USD: Number(minPos),
      AGENT_MAX_POSITION_USD: Number(maxPos),
      AGENT_DAILY_LOSS_CAP_USD: Number(dailyLoss),
      AGENT_MAX_OPEN_POSITIONS: Number(maxOpen),
      AGENT_CRON_MINUTES: Number(cron),
      AGENT_INTEL_BOOST: Number(intelBoost),
      AGENT_TAKE_PROFIT_PCT: Number(takeProfit),
      AGENT_RECENT_TRADE_WINDOW_HOURS: Number(recentWindow),
    })
  }

  const NumInput = ({
    value,
    onChange,
    step = '1',
  }: {
    value: number
    onChange: (n: number) => void
    step?: string
  }) => (
    <input
      type="number"
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-3 py-2 rounded-md text-sm w-32"
    />
  )

  return (
    <Card title="Agent budget & cadence (editable)">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            AGENT_ENABLED
            <OverrideBadge k="AGENT_ENABLED" overridden={s.overridden} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            scheduler runs every cron interval
          </label>
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            AUTO_EXECUTE_LIVE
            <OverrideBadge k="AGENT_AUTO_EXECUTE_LIVE" overridden={s.overridden} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={autoLive}
              onChange={(e) => setAutoLive(e.target.checked)}
            />
            <span className={autoLive ? 'text-destructive font-semibold' : ''}>
              auto-execute in LIVE mode (real money!)
            </span>
          </label>
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            BUDGET_USD
            <OverrideBadge k="AGENT_BUDGET_USD" overridden={s.overridden} />
          </div>
          <NumInput value={budget} onChange={setBudget} step="10" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            WEEKLY_BUDGET_USD
            <OverrideBadge k="AGENT_WEEKLY_BUDGET_USD" overridden={s.overridden} />
          </div>
          <NumInput value={weekly} onChange={setWeekly} step="10" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MIN_POSITION_USD
            <OverrideBadge k="AGENT_MIN_POSITION_USD" overridden={s.overridden} />
          </div>
          <NumInput value={minPos} onChange={setMinPos} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MAX_POSITION_USD
            <OverrideBadge k="AGENT_MAX_POSITION_USD" overridden={s.overridden} />
          </div>
          <NumInput value={maxPos} onChange={setMaxPos} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            DAILY_LOSS_CAP
            <OverrideBadge k="AGENT_DAILY_LOSS_CAP_USD" overridden={s.overridden} />
          </div>
          <NumInput value={dailyLoss} onChange={setDailyLoss} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MAX_OPEN_POSITIONS
            <OverrideBadge k="AGENT_MAX_OPEN_POSITIONS" overridden={s.overridden} />
          </div>
          <NumInput value={maxOpen} onChange={setMaxOpen} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            CRON_MINUTES
            <OverrideBadge k="AGENT_CRON_MINUTES" overridden={s.overridden} />
          </div>
          <NumInput value={cron} onChange={setCron} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            INTEL_BOOST
            <OverrideBadge k="AGENT_INTEL_BOOST" overridden={s.overridden} />
          </div>
          <NumInput value={intelBoost} onChange={setIntelBoost} step="0.05" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            TAKE_PROFIT_PCT
            <OverrideBadge k="AGENT_TAKE_PROFIT_PCT" overridden={s.overridden} />
          </div>
          <div className="flex items-center gap-2">
            <NumInput value={takeProfit} onChange={setTakeProfit} step="0.01" />
            <span className="text-xs text-muted-foreground">
              = {(Number(takeProfit) * 100).toFixed(1)}% (auto-sell when up this much vs entry; 0 disables)
            </span>
          </div>
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            RECENT_TRADE_WINDOW
            <OverrideBadge k="AGENT_RECENT_TRADE_WINDOW_HOURS" overridden={s.overridden} />
          </div>
          <div className="flex items-center gap-2">
            <NumInput value={recentWindow} onChange={setRecentWindow} step="1" />
            <span className="text-xs text-muted-foreground">
              hours - skip re-buying any symbol bought within this window
            </span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3 pt-4">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save agent settings'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved (rescheduler refreshed)</span>
        )}
      </div>
    </Card>
  )
}

// ----- Agent signal thresholds (previously hard-coded) -----
function AgentThresholdsCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [minScore, setMinScore] = useState(s.agent_min_score)
  const [minConf, setMinConf] = useState(s.agent_min_confidence)
  const [topN, setTopN] = useState(s.agent_top_n_candidates)
  const [llmConc, setLlmConc] = useState(s.agent_llm_concurrency)

  useEffect(() => {
    setMinScore(s.agent_min_score)
    setMinConf(s.agent_min_confidence)
    setTopN(s.agent_top_n_candidates)
    setLlmConc(s.agent_llm_concurrency)
  }, [s])

  const save = () =>
    upd.mutate({
      AGENT_MIN_SCORE: Number(minScore),
      AGENT_MIN_CONFIDENCE: Number(minConf),
      AGENT_TOP_N_CANDIDATES: Number(topN),
      AGENT_LLM_CONCURRENCY: Number(llmConc),
    })

  const Num = ({
    value,
    onChange,
    step = '1',
  }: {
    value: number
    onChange: (n: number) => void
    step?: string
  }) => (
    <input
      type="number"
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-3 py-2 rounded-md text-sm w-32"
    />
  )

  return (
    <Card title="Agent signal thresholds (editable)">
      <p className="text-xs text-muted-foreground mb-3">
        These were previously hard-coded in the allocator. Raising the min
        score/confidence makes the agent pickier (fewer but higher-quality
        proposals). Top-N caps how many candidates are sized per run.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MIN_SCORE
            <OverrideBadge k="AGENT_MIN_SCORE" overridden={s.overridden} />
          </div>
          <Num value={minScore} onChange={setMinScore} step="0.05" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MIN_CONFIDENCE
            <OverrideBadge k="AGENT_MIN_CONFIDENCE" overridden={s.overridden} />
          </div>
          <Num value={minConf} onChange={setMinConf} step="0.05" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            TOP_N_CANDIDATES
            <OverrideBadge k="AGENT_TOP_N_CANDIDATES" overridden={s.overridden} />
          </div>
          <Num value={topN} onChange={setTopN} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            LLM_CONCURRENCY
            <OverrideBadge k="AGENT_LLM_CONCURRENCY" overridden={s.overridden} />
          </div>
          <Num value={llmConc} onChange={setLlmConc} step="1" />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-4">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save thresholds'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Scraper cadence (previously hard-coded) -----
function ScraperCadenceCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [maxTweets, setMaxTweets] = useState(s.agent_max_tweets_per_account)
  const [lookback, setLookback] = useState(s.agent_lookback_hours)
  const [timeout, setTimeoutS] = useState(s.agent_per_account_timeout_s)
  const [poll, setPoll] = useState(s.poll_interval_seconds)

  useEffect(() => {
    setMaxTweets(s.agent_max_tweets_per_account)
    setLookback(s.agent_lookback_hours)
    setTimeoutS(s.agent_per_account_timeout_s)
    setPoll(s.poll_interval_seconds)
  }, [s])

  const save = () =>
    upd.mutate({
      AGENT_MAX_TWEETS_PER_ACCOUNT: Number(maxTweets),
      AGENT_LOOKBACK_HOURS: Number(lookback),
      AGENT_PER_ACCOUNT_TIMEOUT_S: Number(timeout),
      POLL_INTERVAL_SECONDS: Number(poll),
    })

  const Num = ({
    value,
    onChange,
  }: {
    value: number
    onChange: (n: number) => void
  }) => (
    <input
      type="number"
      step="1"
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-3 py-2 rounded-md text-sm w-32"
    />
  )

  return (
    <Card title="Scraper cadence (editable)">
      <p className="text-xs text-muted-foreground mb-3">
        X/Twitter scraper windows + REST quote poll interval. Previously
        hard-coded; edit here instead of touching .env.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MAX_TWEETS_PER_ACCOUNT
            <OverrideBadge k="AGENT_MAX_TWEETS_PER_ACCOUNT" overridden={s.overridden} />
          </div>
          <Num value={maxTweets} onChange={setMaxTweets} />
        </div>
        <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            LOOKBACK_HOURS
            <OverrideBadge k="AGENT_LOOKBACK_HOURS" overridden={s.overridden} />
          </div>
          <Num value={lookback} onChange={setLookback} />
        </div>
        <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            PER_ACCOUNT_TIMEOUT_S
            <OverrideBadge k="AGENT_PER_ACCOUNT_TIMEOUT_S" overridden={s.overridden} />
          </div>
          <Num value={timeout} onChange={setTimeoutS} />
        </div>
        <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            POLL_INTERVAL_SECONDS
            <OverrideBadge k="POLL_INTERVAL_SECONDS" overridden={s.overridden} />
          </div>
          <Num value={poll} onChange={setPoll} />
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground mt-2">
        Note: POLL_INTERVAL_SECONDS changes take effect on process restart (the
        REST polling loop reads it at startup).
      </p>
      <div className="flex items-center gap-3 pt-4">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save cadence'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Swing-trading skill (1-2 week horizon) -----
function SwingTradingCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [enabled, setEnabled] = useState(s.swing_enabled)
  const [riskPct, setRiskPct] = useState(s.swing_risk_per_trade_pct)
  const [minRR, setMinRR] = useState(s.swing_min_rr)
  const [timeStop, setTimeStop] = useState(s.swing_time_stop_days)
  const [moveBe, setMoveBe] = useState(s.swing_move_stop_be_pct)
  const [partial, setPartial] = useState(s.swing_partial_pct)
  const [filterSym, setFilterSym] = useState(s.swing_market_filter_symbol)
  const [filterMa, setFilterMa] = useState(s.swing_market_filter_ma)
  const [lookback, setLookback] = useState(s.swing_bar_lookback_days)

  useEffect(() => {
    setEnabled(s.swing_enabled)
    setRiskPct(s.swing_risk_per_trade_pct)
    setMinRR(s.swing_min_rr)
    setTimeStop(s.swing_time_stop_days)
    setMoveBe(s.swing_move_stop_be_pct)
    setPartial(s.swing_partial_pct)
    setFilterSym(s.swing_market_filter_symbol)
    setFilterMa(s.swing_market_filter_ma)
    setLookback(s.swing_bar_lookback_days)
  }, [s])

  const save = () =>
    upd.mutate({
      SWING_ENABLED: enabled,
      SWING_RISK_PER_TRADE_PCT: Number(riskPct),
      SWING_MIN_RR: Number(minRR),
      SWING_TIME_STOP_DAYS: Number(timeStop),
      SWING_MOVE_STOP_BE_PCT: Number(moveBe),
      SWING_PARTIAL_PCT: Number(partial),
      SWING_MARKET_FILTER_SYMBOL: filterSym,
      SWING_MARKET_FILTER_MA: Number(filterMa),
      SWING_BAR_LOOKBACK_DAYS: Number(lookback),
    })

  const Num = ({
    value,
    onChange,
    step = '1',
  }: {
    value: number
    onChange: (n: number) => void
    step?: string
  }) => (
    <input
      type="number"
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-3 py-2 rounded-md text-sm w-32"
    />
  )

  return (
    <Card title="Swing-trading skill (1-2 week horizon)">
      <p className="text-xs text-muted-foreground mb-3">
        Layer the four approved setups (trend pullback, breakout,
        oversold bounce, earnings/news momentum) on top of the tweet pipeline.
        Every run applies the setup scanner to every watchlist symbol, sizes
        positions by 1% risk against a concrete stop, and enforces the
        market-regime filter + trade-management rules (stop hit / time stop /
        breakeven bump). When <strong>regime = no-go</strong>, all BUYs
        become watch-only.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
          SWING_ENABLED
          <OverrideBadge k="SWING_ENABLED" overridden={s.overridden} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          Run the swing scanner on every agent run
        </label>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            RISK_PER_TRADE
            <OverrideBadge k="SWING_RISK_PER_TRADE_PCT" overridden={s.overridden} />
          </div>
          <Num value={riskPct} onChange={setRiskPct} step="0.005" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MIN_R/R
            <OverrideBadge k="SWING_MIN_RR" overridden={s.overridden} />
          </div>
          <Num value={minRR} onChange={setMinRR} step="0.25" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            TIME_STOP_DAYS
            <OverrideBadge k="SWING_TIME_STOP_DAYS" overridden={s.overridden} />
          </div>
          <Num value={timeStop} onChange={setTimeStop} step="1" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            MOVE_STOP_BE_PCT
            <OverrideBadge k="SWING_MOVE_STOP_BE_PCT" overridden={s.overridden} />
          </div>
          <Num value={moveBe} onChange={setMoveBe} step="0.01" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            PARTIAL_PCT
            <OverrideBadge k="SWING_PARTIAL_PCT" overridden={s.overridden} />
          </div>
          <Num value={partial} onChange={setPartial} step="0.01" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            FILTER_SYMBOL
            <OverrideBadge k="SWING_MARKET_FILTER_SYMBOL" overridden={s.overridden} />
          </div>
          <input
            type="text"
            value={filterSym}
            onChange={(e) => setFilterSym(e.target.value.toUpperCase())}
            className="px-3 py-2 rounded-md text-sm w-32"
          />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            FILTER_MA
            <OverrideBadge k="SWING_MARKET_FILTER_MA" overridden={s.overridden} />
          </div>
          <Num value={filterMa} onChange={setFilterMa} step="5" />
        </div>
        <div className="grid grid-cols-[180px_1fr] gap-2 py-2 border-b border-border">
          <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
            BAR_LOOKBACK_DAYS
            <OverrideBadge k="SWING_BAR_LOOKBACK_DAYS" overridden={s.overridden} />
          </div>
          <Num value={lookback} onChange={setLookback} step="10" />
        </div>
      </div>

      <div className="flex items-center gap-3 pt-4">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save swing rules'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

// ----- Auto-sell (max-hold window) -----
function AutoSellCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const { data: preview } = useAutoSellPreview()
  const runNow = useAutoSellRunNow()
  const [enabled, setEnabled] = useState(s.auto_sell_enabled)
  const [days, setDays] = useState(s.auto_sell_max_hold_days)

  useEffect(() => {
    setEnabled(s.auto_sell_enabled)
    setDays(s.auto_sell_max_hold_days)
  }, [s])

  const save = () =>
    upd.mutate({
      AUTO_SELL_ENABLED: enabled,
      AUTO_SELL_MAX_HOLD_DAYS: Number(days),
    })

  const candidates = preview?.candidates ?? []
  const wouldSell = preview?.would_sell_count ?? 0

  return (
    <Card title="Auto-sell (max-hold window)">
      <p className="text-xs text-muted-foreground mb-3">
        Daily safety scan at <strong>09:45 US/Eastern</strong> (15 min after
        market open): any open position held longer than the cap is closed
        at market. Paper auto-executes; live proposes unless{' '}
        <code className="text-primary">AGENT_AUTO_EXECUTE_LIVE</code> is also
        true. Guardrails: we only touch long positions with a local buy
        history, and we dedupe sells within a 6-hour window so manual
        re-triggers don&apos;t double-fire.
      </p>

      <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
          AUTO_SELL_ENABLED
          <OverrideBadge k="AUTO_SELL_ENABLED" overridden={s.overridden} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          run the daily max-hold scan
        </label>
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
          MAX_HOLD_DAYS
          <OverrideBadge
            k="AUTO_SELL_MAX_HOLD_DAYS"
            overridden={s.overridden}
          />
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            step="1"
            min="1"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="px-3 py-2 rounded-md text-sm w-24"
          />
          <span className="text-xs text-muted-foreground">
            days - close anything held longer than this at the next 09:45 ET scan
          </span>
        </div>
      </div>

      {/* Live preview of what would be sold on the next scan */}
      <div className="mt-3">
        <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
          Next scan preview
        </div>
        {!preview && (
          <div className="text-xs text-muted-foreground italic">
            loading positions...
          </div>
        )}
        {preview && candidates.length === 0 && (
          <div className="text-xs text-muted-foreground italic">
            no open positions - nothing to auto-sell.
          </div>
        )}
        {preview && candidates.length > 0 && (
          <div className="space-y-1">
            <div className="text-[11px] text-muted-foreground">
              {wouldSell === 0
                ? `${candidates.length} open positions, none over the ${preview.max_hold_days}-day cap yet.`
                : `${wouldSell} of ${candidates.length} positions would be sold on the next scan.`}
            </div>
            <div className="overflow-hidden rounded-md border border-border">
              <table className="w-full text-xs">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-2 py-1 text-left text-muted-foreground">Symbol</th>
                    <th className="px-2 py-1 text-right text-muted-foreground">Qty</th>
                    <th className="px-2 py-1 text-right text-muted-foreground">Held</th>
                    <th className="px-2 py-1 text-right text-muted-foreground">Opened</th>
                    <th className="px-2 py-1 text-left text-muted-foreground">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.symbol} className="border-t border-border">
                      <td className="px-2 py-1 font-medium">{c.symbol}</td>
                      <td className="px-2 py-1 text-right">{c.qty}</td>
                      <td className="px-2 py-1 text-right">
                        {c.held_days.toFixed(1)}d
                      </td>
                      <td className="px-2 py-1 text-right text-muted-foreground">
                        {new Date(c.opened_at).toLocaleDateString()}
                      </td>
                      <td className="px-2 py-1">
                        {c.over_cap ? (
                          <span className="text-destructive font-medium">
                            would sell
                          </span>
                        ) : (
                          <span className="text-muted-foreground">
                            holding
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 pt-4 flex-wrap">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save'}
        </button>
        <button
          onClick={() => runNow.mutate(false)}
          disabled={runNow.isPending}
          className="btn-secondary px-4 py-2 rounded-lg text-sm"
          title="Run the max-hold scan right now (honours the enabled toggle)"
        >
          {runNow.isPending ? 'Running...' : 'Run scan now'}
        </button>
        <button
          onClick={() => {
            if (confirm('Force-run the scan even if auto-sell is disabled?'))
              runNow.mutate(true)
          }}
          disabled={runNow.isPending}
          className="btn-secondary px-4 py-2 rounded-lg text-xs"
          title="Bypass the enabled toggle (one-off)"
        >
          Force run
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
        {runNow.isSuccess && !runNow.isPending && (
          <span className="text-xs text-success">
            scan complete: {(runNow.data as any)?.executed ?? 0} executed,{' '}
            {(runNow.data as any)?.proposed ?? 0} proposed,{' '}
            {(runNow.data as any)?.skipped ?? 0} skipped
          </span>
        )}
        {runNow.isError && (
          <span className="text-xs text-destructive">
            {(runNow.error as any)?.message ?? 'scan failed'}
          </span>
        )}
      </div>
    </Card>
  )
}


// ----- Manual-order safety cap (replaces MAX_ORDER_NOTIONAL) -----
function ManualOrderSafetyCard({ s }: { s: AgentSettings }) {
  const upd = useUpdateAgentSettings()
  const [cap, setCap] = useState(s.manual_order_max_notional)
  useEffect(() => setCap(s.manual_order_max_notional), [s])

  const save = () =>
    upd.mutate({ MANUAL_ORDER_MAX_NOTIONAL: Number(cap) })

  return (
    <Card title="Manual order safety (editable)">
      <p className="text-xs text-muted-foreground mb-3">
        Fat-finger cap for <strong>manual</strong> orders placed via the Trade
        page. Applied in addition to Alpaca's live buying power, so you are
        always bounded by both. Default is intentionally small to match the
        $20-$30 trade style — raise temporarily if you want to place a larger
        manual order.
      </p>
      <div className="grid grid-cols-[220px_1fr] gap-2 py-2 border-b border-border">
        <div className="text-xs text-muted-foreground uppercase tracking-wider self-center">
          MANUAL_ORDER_MAX_NOTIONAL
          <OverrideBadge k="MANUAL_ORDER_MAX_NOTIONAL" overridden={s.overridden} />
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            step="1"
            value={cap}
            onChange={(e) => setCap(Number(e.target.value))}
            className="px-3 py-2 rounded-md text-sm w-32"
          />
          <span className="text-xs text-muted-foreground">
            USD. Broker buying power still applies on top.
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3 pt-4">
        <button
          onClick={save}
          disabled={upd.isPending}
          className="btn-primary px-4 py-2 rounded-lg"
        >
          {upd.isPending ? 'Saving...' : 'Save cap'}
        </button>
        {upd.isSuccess && !upd.isPending && (
          <span className="text-xs text-success">saved</span>
        )}
      </div>
    </Card>
  )
}

export function SettingsPage() {
  const { data: mode } = useMode()
  const { data: account } = useAccount()
  const { data: agent } = useAgentStatus()
  const { data: cache } = useAgentAccountsCache()
  const { data: agentSettings } = useAgentSettings()

  const fmtDt = (s?: string | null) => (s ? new Date(s).toLocaleString() : '-')
  const isLive = mode?.mode === 'live'

  const resolved = cache?.filter((c) => c.user_id && !c.not_found) || []
  const notFound = cache?.filter((c) => c.not_found) || []
  const pending = cache?.filter((c) => !c.user_id && !c.not_found && c.in_config) || []
  const orphaned = cache?.filter((c) => !c.in_config) || []

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <h1 className="text-2xl font-semibold">Settings & Configuration</h1>
          <a
            href={`https://github.com/timchinchen/Trading-app/releases/tag/v${APP_VERSION}`}
            target="_blank"
            rel="noreferrer"
            title="GitHub release tag matching this build (X.Y human-controlled, Z droid-controlled)"
            className="text-xs font-mono px-2 py-1 rounded border border-border text-muted-foreground hover:text-primary hover:border-primary/40"
          >
            v{APP_VERSION}
          </a>
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          Defaults come from <code className="text-primary">backend/.env</code> at
          startup. Anything you change in the editable cards below is persisted in
          the SQLite database and overrides the env file - no restart required.
          Broker keys and <code className="text-primary">APP_MODE</code> still live in{' '}
          <code className="text-primary">.env</code> for safety.
        </p>
      </div>

      <Card title="Runtime mode">
        <Row
          label="APP_MODE"
          value={
            <span
              className={`font-semibold ${
                isLive ? 'text-destructive' : 'text-success'
              }`}
            >
              {mode?.mode ?? '...'}
            </span>
          }
          hint={
            isLive
              ? 'LIVE - orders go to Alpaca and use real money.'
              : 'PAPER - simulated trades, no real money.'
          }
        />
        <Row
          label="MARKET_DATA_MODE"
          value={mode?.market_data_mode ?? '...'}
          hint='"ws" all-websocket, "poll" all-REST, "mixed" = per-symbol (default).'
        />
        <Row
          label="MAX_ORDER_NOTIONAL"
          value={`$${mode?.max_order_notional?.toFixed?.(2) ?? '-'}`}
          hint="Hard server-side cap applied to EVERY order (including agent + manual)."
        />
      </Card>

      <Card title="Broker account (Alpaca)">
        {account ? (
          <>
            <Row label="Broker mode" value={account.mode} />
            <Row label="Currency" value={account.currency} />
            <Row label="Cash" value={`$${account.cash.toFixed(2)}`} />
            <Row label="Buying power" value={`$${account.buying_power.toFixed(2)}`} />
            <Row
              label="Portfolio value"
              value={`$${account.portfolio_value.toFixed(2)}`}
            />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            No broker data. Check{' '}
            <code className="text-primary">ALPACA_PAPER_KEY</code> /{' '}
            <code className="text-primary">ALPACA_PAPER_SECRET</code> in{' '}
            <code className="text-primary">.env</code>.
          </p>
        )}
      </Card>

      {agentSettings ? (
        <>
          <LLMProviderCard s={agentSettings} />
          <DeepAnalysisLLMCard s={agentSettings} />
          <DataEnrichmentCard s={agentSettings} />
          <StocktwitsCard s={agentSettings} />
          <AgentBudgetCard s={agentSettings} />
          <AgentThresholdsCard s={agentSettings} />
          <SwingTradingCard s={agentSettings} />
          <AutoSellCard s={agentSettings} />
          <ScraperCadenceCard s={agentSettings} />
          <ManualOrderSafetyCard s={agentSettings} />
          <TwitterAccountsCard s={agentSettings} />
        </>
      ) : (
        <Card title="LLM + agent settings">
          <p className="text-sm text-muted-foreground">Loading editable settings...</p>
        </Card>
      )}

      <Card title="Agent status">
        <Row
          label="Last run"
          value={
            <span
              className={
                agent?.last_run_status === 'ok'
                  ? 'text-success'
                  : agent?.last_run_status === 'error'
                    ? 'text-destructive'
                    : 'text-muted-foreground'
              }
            >
              {agent?.last_run_status ?? 'never'}
              {agent?.last_run_started_at
                ? ` @ ${fmtDt(agent.last_run_started_at)}`
                : ''}
            </span>
          }
        />
        <Row label="Next run" value={fmtDt(agent?.next_run_at)} />
        <Row
          label="Active LLM"
          value={
            <code className="text-primary">
              {agent?.ollama_model} @ {agent?.ollama_host}
            </code>
          }
          hint="Resolved from your provider override above."
        />
      </Card>

      <Card title={`Resolution status (${agent?.accounts.length ?? 0} handles)`}>
        <p className="text-xs text-muted-foreground mb-3">
          Cached resolution status for the handles above. Resolved IDs persist
          forever; unresolved handles are retried monthly.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Resolved ({resolved.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[320px] overflow-auto pr-2">
              {resolved.map((c) => (
                <li key={c.handle} className="flex justify-between gap-2">
                  <a
                    href={`https://x.com/${c.handle}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-success hover:underline"
                  >
                    @{c.handle}
                  </a>
                  <span className="text-muted-foreground">id {c.user_id}</span>
                </li>
              ))}
              {resolved.length === 0 && (
                <li className="text-muted-foreground italic">
                  none yet (agent hasn't resolved any)
                </li>
              )}
            </ul>
          </div>

          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Pending / not resolved ({pending.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[320px] overflow-auto pr-2">
              {pending.map((c) => (
                <li key={c.handle}>
                  <a
                    href={`https://x.com/${c.handle}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground hover:underline"
                  >
                    @{c.handle}
                  </a>
                </li>
              ))}
              {pending.length === 0 && (
                <li className="text-muted-foreground italic">all resolved</li>
              )}
            </ul>
          </div>

          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Not found on X ({notFound.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[200px] overflow-auto pr-2">
              {notFound.map((c) => (
                <li key={c.handle} className="flex justify-between gap-2">
                  <span className="text-destructive">@{c.handle}</span>
                  <span className="text-muted-foreground">{fmtDt(c.resolved_at)}</span>
                </li>
              ))}
              {notFound.length === 0 && (
                <li className="text-muted-foreground italic">none</li>
              )}
            </ul>
          </div>

          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2">
              Cached but removed from config ({orphaned.length})
            </div>
            <ul className="text-xs space-y-1 max-h-[200px] overflow-auto pr-2">
              {orphaned.map((c) => (
                <li key={c.handle} className="text-muted-foreground">
                  @{c.handle} ({c.not_found ? 'not-found' : 'resolved'})
                </li>
              ))}
              {orphaned.length === 0 && (
                <li className="text-muted-foreground italic">none</li>
              )}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  )
}
