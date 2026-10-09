import type { ReactNode } from 'react'

export type Tone = 'neutral' | 'ok' | 'warn' | 'bad' | 'info' | 'accent'
const TONES: Record<Tone, string> = {
  neutral: 'bg-navy-700 text-slate-200',
  ok: 'bg-emerald-900 text-emerald-200',
  warn: 'bg-amber-400 text-navy-900',
  bad: 'bg-red-900 text-red-200',
  info: 'bg-sky-900 text-sky-200',
  accent: 'bg-accent text-navy-900',
}

export function Chip({ tone = 'neutral', children, title, testId }: { tone?: Tone; children: ReactNode; title?: string; testId?: string }) {
  return (
    <span title={title} data-testid={testId} className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  )
}

const FIELD_TONE: Record<string, Tone> = { parsed: 'ok', inferred: 'warn', unknown: 'bad' }
/** parsed / inferred / unknown: the three states a field value can be in (never blended). */
export const FieldStatusChip = ({ status }: { status: string }) => (
  <Chip tone={FIELD_TONE[status] ?? 'neutral'}>{status}</Chip>
)

const TIER_TONE: Record<string, Tone> = { A: 'ok', B: 'info', C: 'warn', D: 'neutral' }
/** Support tier. Nothing in this product is above Tier B. */
export const TierChip = ({ tier }: { tier: string }) => (
  <Chip tone={TIER_TONE[tier.replace(/^tier[\s_-]*/i, '').toUpperCase()] ?? 'neutral'} title="Support tier (nothing is above Tier B)">
    Tier {tier.replace(/^tier[\s_-]*/i, '').toUpperCase()}
  </Chip>
)

const JOB_TONE: Record<string, Tone> = {
  queued: 'neutral', running: 'info', cancelling: 'warn', cancelled: 'neutral', failed: 'bad', completed: 'ok',
}
export const StatusChip = ({ status }: { status: string }) => <Chip tone={JOB_TONE[status] ?? 'neutral'}>{status}</Chip>

/** "Triage, not identification" label that every analytics-derived view carries. */
export const TriageLabel = () => <Chip tone="info">triage, not identification</Chip>
