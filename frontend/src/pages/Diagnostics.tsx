import { useState } from 'react'
import {
  OPTIONAL_ENV,
  REQUIRED_ENV,
  SETUP_HEALTH_ROWS,
  type RowKind,
} from '../components/PrerequisitesPanel'
import { useAgentDiagnostics, useAgentSettings, useSetupHealth } from '../api/hooks'

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

async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {}

  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-1000px'
    ta.style.left = '-1000px'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, ta.value.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return !!ok
  } catch {
    return false
  }
}

export function DiagnosticsPage() {
  const setup = useSetupHealth()
  const diagnostics = useAgentDiagnostics()
  const agentSettings = useAgentSettings()
  const [copyAllStatus, setCopyAllStatus] = useState<'idle' | 'copied' | 'error'>('idle')

  const copyAllPrompts = async () => {
    if (!diagnostics.data) return
    const d = diagnostics.data
    const s = agentSettings.data
    const settingsHeader = [
      '=== KEY SETTINGS SNAPSHOT ===',
      '(for prompt/settings consistency checks)',
      `AGENT_PROMPT_TIME_STOP_DAYS=${s?.agent_prompt_time_stop_days ?? 'n/a'}`,
      `SWING_TIME_STOP_DAYS=${s?.swing_time_stop_days ?? 'n/a'}`,
      `SWING_MOVE_STOP_BE_PCT=${s?.swing_move_stop_be_pct ?? 'n/a'}`,
      `SWING_PARTIAL_PCT=${s?.swing_partial_pct ?? 'n/a'}`,
      `AGENT_MAX_HOLD_DAYS=${s?.agent_max_hold_days ?? 'n/a'}`,
      `AUTO_SELL_MAX_HOLD_DAYS=${s?.auto_sell_max_hold_days ?? 'n/a'}`,
      `AGENT_PARTIAL_TAKE_PCT=${s?.agent_partial_take_pct ?? 'n/a'}`,
      `AGENT_PARTIAL_TAKE_FRACTION=${s?.agent_partial_take_fraction ?? 'n/a'}`,
      `AGENT_TAKE_PROFIT_PCT=${s?.agent_take_profit_pct ?? 'n/a'}`,
      `AGENT_STOP_LOSS_PCT=${s?.agent_stop_loss_pct ?? 'n/a'}`,
      `AGENT_TRAIL_ARM_PCT=${s?.agent_trail_arm_pct ?? 'n/a'}`,
      `AGENT_TRAIL_RETRACE_PCT=${s?.agent_trail_retrace_pct ?? 'n/a'}`,
      `AGENT_REGIME_RISK_ON_MULT=${s?.agent_regime_risk_on_mult ?? 'n/a'}`,
      `AGENT_REGIME_NEUTRAL_MULT=${s?.agent_regime_neutral_mult ?? 'n/a'}`,
      `AGENT_REGIME_RISK_OFF_MULT=${s?.agent_regime_risk_off_mult ?? 'n/a'}`,
      `AGENT_RISK_OFF_BLOCK_NEW_BUYS=${s?.agent_risk_off_block_new_buys ?? 'n/a'}`,
      '',
    ]
    const chunks: string[] = [
      ...settingsHeader,
      '=== ROLE PREAMBLE (EFFECTIVE) ===',
      d.prompts.role_preamble || '',
      '',
      '=== ROLE PREAMBLE (BASE) ===',
      d.prompts.role_preamble_base || '',
      '',
      '=== TWEET ANALYSIS SYSTEM PROMPT ===',
      d.prompts.tweet_system_prompt || '',
      '',
      '=== ADVISOR SYSTEM PROMPT ===',
      d.prompts.advisor_system_prompt || '',
    ]
    if (d.prompts.weekly_lessons) {
      chunks.push('', `=== WEEKLY LESSONS (${d.prompts.weekly_lessons_week_key ?? 'latest'}) ===`, d.prompts.weekly_lessons)
    }
    if (d.weekly_stats) {
      chunks.push('', '=== WEEKLY STATS (DETERMINISTIC) ===', d.weekly_stats)
    }
    const payload = chunks.join('\n')
    try {
      const ok = await copyTextToClipboard(payload)
      if (!ok) throw new Error('copy failed')
      setCopyAllStatus('copied')
      setTimeout(() => setCopyAllStatus('idle'), 1600)
    } catch {
      setCopyAllStatus('error')
      setTimeout(() => setCopyAllStatus('idle'), 2200)
    }
  }

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
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm uppercase tracking-wider text-muted-foreground">
            Agent instructions (system prompts)
          </h2>
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 rounded-lg text-xs"
            onClick={() => void copyAllPrompts()}
            disabled={!diagnostics.data}
            title="Copy all prompt blocks for external validation"
          >
            {copyAllStatus === 'copied'
              ? 'Copied all prompts'
              : copyAllStatus === 'error'
                ? 'Copy failed'
                : 'Copy all prompts'}
          </button>
        </div>
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
              title="Role preamble (effective)"
              text={diagnostics.data.prompts.role_preamble}
            />
            {diagnostics.data.prompts.weekly_lessons && (
              <PromptCard
                title={`Weekly lessons (${diagnostics.data.prompts.weekly_lessons_week_key ?? 'latest'})`}
                text={diagnostics.data.prompts.weekly_lessons}
              />
            )}
            <PromptCard
              title="Role preamble (base)"
              text={diagnostics.data.prompts.role_preamble_base}
            />
            {diagnostics.data.weekly_stats && (
              <PromptCard
                title="Weekly stats (deterministic)"
                text={diagnostics.data.weekly_stats}
              />
            )}
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
