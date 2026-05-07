import {
  OPTIONAL_ENV,
  REQUIRED_ENV,
  SETUP_HEALTH_ROWS,
  type RowKind,
} from '../components/PrerequisitesPanel'
import { useAgentDiagnostics, useSetupHealth } from '../api/hooks'

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

function PromptCard({ title, text }: { title: string; text: string }) {
  return (
    <details className="border border-border rounded-lg bg-card-elevated/40" open>
      <summary className="cursor-pointer px-3 py-2 text-sm text-muted-foreground uppercase tracking-wider">
        {title}
      </summary>
      <pre className="px-3 pb-3 text-[11px] text-foreground whitespace-pre-wrap overflow-auto max-h-[50vh]">
        {text}
      </pre>
    </details>
  )
}

export function DiagnosticsPage() {
  const setup = useSetupHealth()
  const diagnostics = useAgentDiagnostics()

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <section className="panel p-6 space-y-4">
        <h1 className="text-2xl font-semibold">Diagnostics</h1>
        <p className="text-sm text-muted-foreground">
          Consolidated operator view of login setup checks plus the agent&apos;s active
          prompt instructions and trading assumptions.
        </p>
      </section>

      <section className="panel p-6 space-y-4">
        <h2 className="text-sm uppercase tracking-wider text-muted-foreground">
          Login setup health and env snippets
        </h2>
        {setup.isError && (
          <div className="text-sm text-destructive">
            Failed to load setup health: {(setup.error as Error)?.message}
          </div>
        )}
        {!setup.data && !setup.isError && (
          <div className="text-sm text-muted-foreground">Loading setup health...</div>
        )}
        {setup.data && (
          <div className="overflow-hidden rounded-md border border-border">
            <table className="w-full">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Check</th>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Status</th>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Detail</th>
                </tr>
              </thead>
              <tbody>
                {SETUP_HEALTH_ROWS.map((row) => {
                  const probe = setup.data?.[row.key] ?? { ok: false, detail: '' }
                  return (
                    <tr key={row.key} className="border-t border-border">
                      <td className="px-3 py-2 text-sm">{row.label}</td>
                      <td className="px-3 py-2">
                        <Dot ok={!!probe.ok} kind={row.kind} />
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {probe.detail || (row.kind === 'optional' ? '-' : 'not ready')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
              Required env template
            </div>
            <pre className="bg-background-soft border border-border rounded p-3 text-[11px] overflow-auto">
              {REQUIRED_ENV}
            </pre>
          </div>
          <div>
            <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
              Optional env template
            </div>
            <pre className="bg-background-soft border border-border rounded p-3 text-[11px] overflow-auto">
              {OPTIONAL_ENV}
            </pre>
          </div>
        </div>
      </section>

      <section className="panel p-6 space-y-4">
        <h2 className="text-sm uppercase tracking-wider text-muted-foreground">
          Agent instructions (system prompts)
        </h2>
        {diagnostics.isError && (
          <div className="text-sm text-destructive">
            Failed to load diagnostics: {(diagnostics.error as Error)?.message}
          </div>
        )}
        {!diagnostics.data && !diagnostics.isError && (
          <div className="text-sm text-muted-foreground">Loading agent diagnostics...</div>
        )}
        {diagnostics.data && (
          <div className="space-y-3">
            <PromptCard
              title="Role preamble"
              text={diagnostics.data.prompts.role_preamble}
            />
            <PromptCard
              title="Tweet analysis system prompt"
              text={diagnostics.data.prompts.tweet_system_prompt}
            />
            <PromptCard
              title="Advisor system prompt"
              text={diagnostics.data.prompts.advisor_system_prompt}
            />
          </div>
        )}
      </section>

      <section className="panel p-6 space-y-4">
        <h2 className="text-sm uppercase tracking-wider text-muted-foreground">
          Trading logic assumptions
        </h2>
        {diagnostics.data && (
          <div className="overflow-hidden rounded-md border border-border">
            <table className="w-full">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Assumption</th>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Current value</th>
                  <th className="px-3 py-2 text-left text-xs text-muted-foreground">Source</th>
                </tr>
              </thead>
              <tbody>
                {diagnostics.data.assumptions.map((item) => (
                  <tr key={item.name} className="border-t border-border align-top">
                    <td className="px-3 py-2 text-sm">{item.name}</td>
                    <td className="px-3 py-2 text-xs text-foreground">{item.value}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{item.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
