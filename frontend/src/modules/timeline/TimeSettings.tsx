import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { EvidencePicker } from '../../shell/EvidencePicker'
import { refreshStatusBanners } from '../../shell/CaseStatus'
import {
  Button, Card, DataTable, EmptyState, ErrorState, Field, Loadable, PageHeader, READONLY_HINT, Skeleton, Tabs, inputClass, useAsync, useToast,
} from '../../ui'
import { type DriftModel, ianaZones, tl } from './api'
import { TimelineNav } from './TimelineNav'

const METHODS: [string, string][] = [
  ['photo_dvr_clock', 'Photo of the DVR clock vs reference'],
  ['ntp_phone', 'NTP-synced phone/clock'],
  ['known_event', 'Known event'],
  ['other', 'Other (describe in notes)'],
]
const f = (n: number, d = 3) => n.toFixed(d)

export function ModelView({ m }: { m: DriftModel }) {
  return (
    <div className="space-y-1 rounded bg-navy-900 p-3 text-sm" data-testid="fit-result">
      <div>
        Model #{m.id} · {m.method === 'offset_only' ? 'offset only (drift ASSUMED zero, not measured)' : 'linear drift'} · n = {m.n} · 95 % intervals
        {m.timezone_used ? ` · device timezone used: ${m.timezone_used}` : ''}
      </div>
      <div data-testid="fit-offset">
        Offset (true - device) at {m.x0}: <b>{f(m.offset_s)} s</b> [{f(m.offset_ci_s[0])}, {f(m.offset_ci_s[1])}]
      </div>
      <div data-testid="fit-drift">
        Drift: <b>{f(m.drift_ppm, 2)} ppm</b>
        {m.drift_ci_ppm ? ` [${f(m.drift_ci_ppm[0], 2)}, ${f(m.drift_ci_ppm[1], 2)}]` : ' (no interval: single point)'}
        {m.drift_assumed_zero && `; interval widened by an assumed bound of ${m.assumed_max_drift_ppm} ppm x time distance`}
      </div>
      {m.residuals_s.length > 0 && <div>Residuals (s): {m.residuals_s.map((r) => f(r, 2)).join(', ')}</div>}
      {m.assumptions.map((a, i) => <div key={i} className="text-slate-300">Assumption: {a}</div>)}
      {m.warnings.map((w, i) => <div key={i} className="text-amber-300">Warning: {w}</div>)}
      {!m.usable && <div className="text-red-300">This model is NOT applied to the timeline.</div>}
    </div>
  )
}

function EvidenceTime({ evidenceId }: { evidenceId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const writable = can('case.write')
  const zones = ianaZones()
  const asm = useAsync(() => tl.getAssumption(evidenceId), [evidenceId])
  const refs = useAsync(() => tl.listRefs(evidenceId), [evidenceId])
  const model = useAsync(() => tl.getModel(evidenceId), [evidenceId])
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<{ tz?: string; basis?: string; kind?: string; notes?: string }>({})
  const [r, setR] = useState({ device_time_raw: '', true_time_utc: '', method: 'photo_dvr_clock', notes: '', photo_path: '', reading_uncertainty_s: 1 })

  const run = async (fn: () => Promise<unknown>, ok: string): Promise<boolean> => {
    setBusy(true)
    try {
      await fn()
      toast.ok(ok)
      asm.reload(); refs.reload(); model.reload()
      refreshStatusBanners()
      return true
    } catch (e) {
      toast.error(errorText(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  return (
    <Tabs
      label="Time settings"
      tabs={[
        {
          id: 'timezone',
          label: 'Device timezone',
          render: () => (
            <Loadable state={asm}>
              {(a) => {
                const tz = draft.tz ?? a.timezone ?? ''
                const unknown = a.tz_status !== 'examiner_assumed'
                return (
                  <div className="space-y-4">
                    {unknown ? (
                      <div role="alert" data-testid="tz-unknown-banner" className="rounded border border-red-400 bg-red-950 p-3 text-sm font-medium text-red-100">
                        TIMEZONE UNKNOWN. No UTC value is computed for this evidence and its clips are listed as unplaceable. Nothing is defaulted to UTC or
                        local time. Enter the device timezone and the evidence for it below.
                      </div>
                    ) : (
                      <div data-testid="tz-assumed-banner" className="rounded border border-emerald-600 bg-emerald-950 p-3 text-sm text-emerald-100">
                        Timezone ASSUMED by examiner {a.examiner}: {a.timezone ?? '(none)'}
                        {a.epoch_basis ? `, epoch basis ${a.epoch_basis}` : ''}. This is an assumption, not an observation.
                      </div>
                    )}
                    <div className="grid gap-3 md:grid-cols-2">
                      <Field label="Device timezone (IANA)">
                        <select aria-label="IANA timezone" disabled={!writable} className={inputClass} value={tz} onChange={(e) => setDraft({ ...draft, tz: e.target.value })}>
                          <option value="">(unknown)</option>
                          {(tz && !zones.includes(tz) ? [tz, ...zones] : zones).map((z) => <option key={z} value={z}>{z}</option>)}
                        </select>
                      </Field>
                      <Field label="Epoch basis (for unix-second/microsecond fields)">
                        <select aria-label="Epoch basis" disabled={!writable} className={inputClass} value={draft.basis ?? a.epoch_basis ?? ''} onChange={(e) => setDraft({ ...draft, basis: e.target.value })}>
                          <option value="">(not stated)</option>
                          <option value="utc">true UTC (Han: Hikvision init/HIKBTREE)</option>
                          <option value="device_local">device local wall clock (Dragonas: Hikvision logs)</option>
                        </select>
                      </Field>
                      <Field label="Evidence kind">
                        <select aria-label="Evidence kind" disabled={!writable} className={inputClass} value={draft.kind ?? a.evidence_kind ?? 'examiner_entered'} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                          <option value="examiner_entered">examiner entered</option>
                          <option value="device_setting_note">device setting note</option>
                        </select>
                      </Field>
                      <Field label="Timezone notes: how do you know? (required)">
                        <input aria-label="Timezone notes" disabled={!writable} className={inputClass} value={draft.notes ?? a.notes} placeholder="e.g. DVR menu photo IMG_0042 shows GMT+05:30" onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
                      </Field>
                    </div>
                    {writable ? (
                      <Button
                        variant="primary"
                        busy={busy}
                        onClick={() =>
                          run(
                            () => tl.putAssumption(evidenceId, { timezone: tz || null, epoch_basis: (draft.basis ?? a.epoch_basis) || null, evidence_kind: draft.kind ?? a.evidence_kind ?? 'examiner_entered', notes: draft.notes ?? a.notes }),
                            'Time assumption saved (custody entry written).',
                          ).then((done) => done && setDraft({}))
                        }
                      >
                        Save time assumption
                      </Button>
                    ) : (
                      <p className="text-sm text-slate-300">{READONLY_HINT}</p>
                    )}
                  </div>
                )
              }}
            </Loadable>
          ),
        },
        {
          id: 'references',
          label: 'Reference times',
          render: () => (
            <div className="space-y-4">
              <p className="text-sm text-slate-300">
                Enter what the DVR clock showed (wall clock, no timezone) and the true UTC time you established (for example photographed against an NTP-synced
                phone). Do not change the DVR clock.
              </p>
              {writable && (
                <div className="grid gap-3 md:grid-cols-3">
                  <Field label="Device clock reading"><input aria-label="Device clock reading" className={inputClass} placeholder="2025-06-01 10:00:00" value={r.device_time_raw} onChange={(e) => setR({ ...r, device_time_raw: e.target.value })} /></Field>
                  <Field label="True time UTC"><input aria-label="True time UTC" className={inputClass} placeholder="2025-06-01T04:31:00Z" value={r.true_time_utc} onChange={(e) => setR({ ...r, true_time_utc: e.target.value })} /></Field>
                  <Field label="Method">
                    <select aria-label="Reference method" className={inputClass} value={r.method} onChange={(e) => setR({ ...r, method: e.target.value })}>
                      {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </Field>
                  <div className="md:col-span-2"><Field label="Notes (required): how was this established?"><input aria-label="Reference notes" className={inputClass} value={r.notes} onChange={(e) => setR({ ...r, notes: e.target.value })} /></Field></div>
                  <Field label="Photo file path (reference only)"><input aria-label="Photo path" className={inputClass} value={r.photo_path} onChange={(e) => setR({ ...r, photo_path: e.target.value })} /></Field>
                  <Field label="Reading uncertainty (s)"><input aria-label="Reading uncertainty (s)" type="number" min={0} step={0.5} className={inputClass} value={r.reading_uncertainty_s} onChange={(e) => setR({ ...r, reading_uncertainty_s: Number(e.target.value) })} /></Field>
                  <div className="flex items-end">
                    <Button busy={busy} onClick={() => run(() => tl.addRef(evidenceId, r), 'Reference observation added (custody entry written).')}>Add reference observation</Button>
                  </div>
                </div>
              )}
              {!writable && <p className="text-sm text-slate-300">{READONLY_HINT}</p>}
              <Loadable state={refs}>
                {(rows) => (
                  <DataTable
                    testId="refs-table"
                    caption={`Reference observations for evidence ${evidenceId}`}
                    rows={rows}
                    rowKey={(x) => x.id}
                    empty={{ title: 'No reference observations yet', hint: writable ? 'Add one above; a fit needs at least one.' : 'An examiner adds these.' }}
                    columns={[
                      { key: 'id', header: '#', render: (x) => x.id, sort: (x) => x.id },
                      { key: 'dev', header: 'Device shows', render: (x) => <span className="font-mono">{x.device_time_raw}</span>, sort: (x) => x.device_time_raw },
                      { key: 'true', header: 'True UTC', render: (x) => <span className="font-mono">{x.true_time_utc}</span>, sort: (x) => x.true_time_utc },
                      { key: 'method', header: 'Method', render: (x) => x.method, sort: (x) => x.method },
                      { key: 'unc', header: 'Reading ±s', render: (x) => x.reading_uncertainty_s },
                      { key: 'notes', header: 'Notes', render: (x) => x.notes, text: (x) => x.notes },
                    ]}
                  />
                )}
              </Loadable>
            </div>
          ),
        },
        {
          id: 'fit',
          label: 'Drift fit',
          render: () => (
            <div className="space-y-3">
              <p className="text-sm text-slate-300">
                The fit uses the reference observations only. With a single observation the drift is assumed zero (stated, never measured) and the interval is
                widened by an assumed bound.
              </p>
              <Loadable state={refs}>
                {(rows) =>
                  writable ? (
                    <Button variant="primary" busy={busy} disabled={rows.length === 0} onClick={() => run(() => tl.fit(evidenceId), 'Time model fitted and stored.')}>
                      Fit offset / drift model
                    </Button>
                  ) : (
                    <p className="text-sm text-slate-300">{READONLY_HINT}</p>
                  )
                }
              </Loadable>
              {model.error ? <ErrorState error={model.error} onRetry={model.reload} /> : model.loading && !model.data ? <Skeleton rows={2} /> : model.data ? <ModelView m={model.data} /> : <EmptyState title="No time model yet" hint="Add a reference observation, then fit." />}
            </div>
          ),
        },
      ]}
    />
  )
}

export default function TimeSettingsScreen() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Time settings" subtitle="Per-evidence device timezone, reference observations and the clock-drift fit. Nothing is defaulted; reference test data only." />
      <TimelineNav caseId={caseId} />
      <Card>
        <EvidencePicker caseId={caseId}>{(ev) => <EvidenceTime key={ev.id} evidenceId={ev.id} />}</EvidencePicker>
      </Card>
    </div>
  )
}
