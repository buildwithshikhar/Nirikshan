import { useCallback, useEffect, useState } from 'react'
import {
  type DriftModel,
  type TimeAssumption,
  type TimeReference,
  apiTimeline,
  ianaZones,
} from '../api_timeline'

const METHODS = [
  ['photo_dvr_clock', 'Photo of the DVR clock vs reference'],
  ['ntp_phone', 'NTP-synced phone/clock'],
  ['known_event', 'Known event'],
  ['other', 'Other (describe in notes)'],
]

const fmt = (n: number, d = 3) => n.toFixed(d)

function ModelView({ m }: { m: DriftModel }) {
  return (
    <div className="space-y-1 rounded bg-navy-900 p-3 text-xs" data-testid="fit-result">
      <div>
        Model #{m.id} · {m.method === 'offset_only' ? 'offset only (drift ASSUMED zero, not measured)' : 'linear drift'} ·
        n = {m.n} · 95 % intervals{m.timezone_used ? ` · device timezone used: ${m.timezone_used}` : ''}
      </div>
      <div data-testid="fit-offset">
        Offset (true - device) at {m.x0}: <b>{fmt(m.offset_s)} s</b> [{fmt(m.offset_ci_s[0])}, {fmt(m.offset_ci_s[1])}]
      </div>
      <div data-testid="fit-drift">
        Drift: <b>{fmt(m.drift_ppm, 2)} ppm</b>
        {m.drift_ci_ppm ? ` [${fmt(m.drift_ci_ppm[0], 2)}, ${fmt(m.drift_ci_ppm[1], 2)}]` : ' (no interval: single point)'}
        {m.drift_assumed_zero && `; interval widened by an assumed bound of ${m.assumed_max_drift_ppm} ppm x time distance`}
      </div>
      {m.residuals_s.length > 0 && <div>Residuals (s): {m.residuals_s.map((r) => fmt(r, 2)).join(', ')}</div>}
      {m.assumptions.map((a, i) => <div key={i} className="text-slate-400">Assumption: {a}</div>)}
      {m.warnings.map((w, i) => <div key={i} className="text-amber-300" role="alert">Warning: {w}</div>)}
      {!m.usable && <div className="text-red-400">This model is NOT applied to the timeline.</div>}
    </div>
  )
}

export default function TimeSettings({
  evidenceId,
  label,
  onChanged,
}: {
  evidenceId: number
  label: string
  onChanged: () => void
}) {
  const zones = ianaZones()
  const [a, setA] = useState<TimeAssumption | null>(null)
  const [tz, setTz] = useState('')
  const [basis, setBasis] = useState('')
  const [kind, setKind] = useState('examiner_entered')
  const [notes, setNotes] = useState('')
  const [refs, setRefs] = useState<TimeReference[]>([])
  const [model, setModel] = useState<DriftModel | null>(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [r, setR] = useState({
    device_time_raw: '',
    true_time_utc: '',
    method: 'photo_dvr_clock',
    notes: '',
    photo_path: '',
    reading_uncertainty_s: 1,
  })

  const load = useCallback(() => {
    apiTimeline.getAssumption(evidenceId).then((x) => {
      setA(x)
      setTz(x.timezone ?? '')
      setBasis(x.epoch_basis ?? '')
      setKind(x.evidence_kind ?? 'examiner_entered')
      setNotes(x.notes)
    }).catch((e) => setError(e.message))
    apiTimeline.listRefs(evidenceId).then(setRefs).catch((e) => setError(e.message))
    apiTimeline.getModel(evidenceId).then(setModel).catch(() => undefined)
  }, [evidenceId])
  useEffect(load, [load])

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setError('')
    setMsg('')
    try {
      await fn()
      setMsg(ok)
      load()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const unknown = a?.tz_status !== 'examiner_assumed'
  return (
    <section className="space-y-4 rounded-lg bg-navy-800 p-5" data-testid={`time-settings-${evidenceId}`}>
      <h2 className="font-medium">Evidence #{evidenceId}: {label}</h2>
      {unknown ? (
        <div role="alert" data-testid="tz-unknown-banner"
          className="rounded border border-red-500 bg-red-950 p-3 text-sm font-medium text-red-200">
          TIMEZONE UNKNOWN. No UTC value is computed for this evidence and its clips are listed as unplaceable.
          Nothing is defaulted to UTC or local time. Enter the device timezone and the evidence for it below.
        </div>
      ) : (
        <div className="rounded border border-emerald-700 bg-emerald-950 p-3 text-sm text-emerald-200" data-testid="tz-assumed-banner">
          Timezone ASSUMED by examiner {a?.examiner}: {a?.timezone ?? '(none)'}
          {a?.epoch_basis ? `, epoch basis ${a.epoch_basis}` : ''}. This is an assumption, not an observation.
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs text-slate-400">
          Device timezone (IANA)
          <select aria-label="Device timezone" value={tz} onChange={(e) => setTz(e.target.value)}
            className="mt-1 block w-full rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700">
            <option value="">(unknown)</option>
            {zones.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Epoch basis (for unix-second/microsecond fields)
          <select aria-label="Epoch basis" value={basis} onChange={(e) => setBasis(e.target.value)}
            className="mt-1 block w-full rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700">
            <option value="">(not stated)</option>
            <option value="utc">true UTC (Han: Hikvision init/HIKBTREE)</option>
            <option value="device_local">device local wall clock (Dragonas: Hikvision logs)</option>
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Evidence kind
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Evidence kind"
            className="mt-1 block w-full rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700">
            <option value="examiner_entered">examiner entered</option>
            <option value="device_setting_note">device setting note</option>
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Notes: how do you know? (required)
          <input aria-label="Timezone notes" value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. DVR menu photo IMG_0042 shows GMT+05:30"
            className="mt-1 block w-full rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700" />
        </label>
      </div>
      <button
        onClick={() => run(() => apiTimeline.putAssumption(evidenceId, {
          timezone: tz || null, epoch_basis: basis || null, evidence_kind: kind, notes,
        }), 'Time assumption saved (custody entry written).')}
        className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover">
        Save time assumption
      </button>

      <div className="space-y-2 border-t border-navy-700 pt-4">
        <h3 className="text-sm font-medium">Reference observations (device clock vs true time)</h3>
        <p className="text-xs text-slate-400">
          Enter what the DVR clock showed (wall clock, no timezone) and the true UTC time you established
          (e.g. photographed against an NTP-synced phone). Do not change the DVR clock.
        </p>
        <div className="grid gap-2 md:grid-cols-3">
          <input aria-label="Device clock reading" placeholder="Device shows: 2025-06-01 10:00:00"
            value={r.device_time_raw} onChange={(e) => setR({ ...r, device_time_raw: e.target.value })}
            className="rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700" />
          <input aria-label="True time UTC" placeholder="True UTC: 2025-06-01T04:31:00Z"
            value={r.true_time_utc} onChange={(e) => setR({ ...r, true_time_utc: e.target.value })}
            className="rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700" />
          <select aria-label="Reference method" value={r.method} onChange={(e) => setR({ ...r, method: e.target.value })}
            className="rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700">
            {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <input aria-label="Reference notes" placeholder="Notes (required): how was this established?"
            value={r.notes} onChange={(e) => setR({ ...r, notes: e.target.value })}
            className="rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700 md:col-span-2" />
          <input aria-label="Photo path" placeholder="Photo file path (reference only)"
            value={r.photo_path} onChange={(e) => setR({ ...r, photo_path: e.target.value })}
            className="rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700" />
          <label className="text-xs text-slate-400">
            Reading uncertainty (s){' '}
            <input type="number" min={0} step={0.5} value={r.reading_uncertainty_s}
              onChange={(e) => setR({ ...r, reading_uncertainty_s: Number(e.target.value) })}
              className="w-20 rounded bg-navy-900 px-2 py-1 text-sm ring-1 ring-navy-700" />
          </label>
        </div>
        <button onClick={() => run(() => apiTimeline.addRef(evidenceId, r), 'Reference observation added (custody entry written).')}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm hover:bg-navy-600">
          Add reference observation
        </button>
        {refs.length > 0 && (
          <table className="w-full text-left text-xs" data-testid="refs-table">
            <thead className="text-slate-400"><tr><th>#</th><th>Device shows</th><th>True UTC</th><th>Method</th><th>Notes</th></tr></thead>
            <tbody>
              {refs.map((x) => (
                <tr key={x.id} className="border-t border-navy-700">
                  <td>{x.id}</td><td className="font-mono">{x.device_time_raw}</td>
                  <td className="font-mono">{x.true_time_utc}</td><td>{x.method}</td><td>{x.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button disabled={refs.length === 0}
          onClick={() => run(async () => setModel(await apiTimeline.fit(evidenceId)), 'Time model fitted and stored.')}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50">
          Fit offset / drift model
        </button>
        {model && <ModelView m={model} />}
      </div>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {msg && <p className="text-sm text-emerald-300">{msg}</p>}
    </section>
  )
}
