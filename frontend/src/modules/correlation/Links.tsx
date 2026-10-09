import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { Button, Chip, DataTable, Field, KV, Loadable, READONLY_HINT, inputClass, useAsync, useToast, type Tone } from '../../ui'
import { type Link, type Snapshot, corrApi } from './api'

export const SUGGESTION_LABEL = 'suggestion: time/topology/class rule match, triage, not identification'
const STATUS_TONE: Record<string, Tone> = { suggested: 'warn', accepted: 'ok', rejected: 'neutral' }

const describe = (s: Snapshot) =>
  s.type === 'event_segment'
    ? `clip ${s.clip_id}, camera ${s.camera_node}, class ${s.class_name}`
    : `external log row ${s.row_number}, node ${s.camera_node}${s.event_text ? `, "${s.event_text}"` : ''}`
const when = (s: Snapshot) => (s.utc_lo ? `${s.utc_lo.replace('T', ' ').slice(0, 19)} .. ${(s.utc_hi ?? '').replace('T', ' ').slice(11, 19)} UTC` : 'no UTC')

function Side({ s, caseId }: { s: Snapshot; caseId: number }) {
  return (
    <div className="rounded bg-navy-900 p-2">
      <div>{describe(s)}</div>
      <div className="text-slate-300">{when(s)} (uncertainty bounds)</div>
      {s.type === 'event_segment' && s.clip_id != null && (
        <RouterLink className="text-accent underline" to={`/cases/${caseId}/recovery/clips/${s.clip_id}`}>Open clip</RouterLink>
      )}
    </div>
  )
}

function Decision({ link, caseId, onDone }: { link: Link; caseId: number; onDone: () => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const decide = async (d: 'accept' | 'reject') => {
    setBusy(true)
    try {
      await corrApi.decide(link.id, d, note)
      toast.ok(`Link ${link.id} ${d === 'accept' ? 'accepted' : 'rejected'} (custody entry written).`)
      onDone()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-3" data-testid="link-detail">
      <Chip tone="info">{SUGGESTION_LABEL}</Chip>
      <p>{link.explanation}</p>
      <div className="grid gap-2"><Side s={link.a} caseId={caseId} /><Side s={link.b} caseId={caseId} /></div>
      <KV
        items={[
          ['Separation', `${link.gap_s_min.toFixed(1)} s to ${link.gap_s_max.toFixed(1)} s`],
          ['Rules that fired', link.rules.map((r) => r.rule).join(', ')],
          ['Status', <Chip key="s" tone={STATUS_TONE[link.status]}>{link.status}</Chip>],
          ['Decision', link.decided_by ? `${link.decided_by}: ${link.decision_note}` : 'none yet'],
        ]}
      />
      <p className="text-xs text-slate-300">A link rests on time, the camera layout you entered and the detection class only. Nothing compares how anything looks.</p>
      {can('case.write') ? (
        <div className="space-y-2">
          <Field label="Decision note (required)"><input aria-label="Decision note" className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <div className="flex gap-2">
            <Button variant="primary" busy={busy} disabled={!note.trim()} onClick={() => decide('accept')}>Accept link</Button>
            <Button variant="danger" busy={busy} disabled={!note.trim()} onClick={() => decide('reject')}>Reject link</Button>
          </div>
        </div>
      ) : (
        <p>{READONLY_HINT}</p>
      )}
    </div>
  )
}

export function SuggestedLinks({ caseId }: { caseId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const drawer = useDetailDrawer()
  const [status, setStatus] = useState('')
  const links = useAsync(() => corrApi.links(caseId, status || undefined), [caseId, status])
  const [f, setF] = useState({ window_s: 60, segment_gap_s: 2, require_same_class: true, include_external_logs: true })
  const [busy, setBusy] = useState(false)
  const generate = async () => {
    setBusy(true)
    try {
      const r = await corrApi.generate(caseId, f)
      toast.ok(`${r.candidates} candidate link(s): ${r.created} new, ${r.updated} updated, ${r.dropped_stale_suggestions} stale suggestion(s) dropped, ${r.decided_links_kept} decided link(s) kept.`)
      links.reload()
    } catch (e) {
      toast.error(errorText(e)) // includes "define a camera topology first"
    } finally {
      setBusy(false)
    }
  }
  const open = (l: Link) => drawer.show(`Link ${l.id}`, <Decision link={l} caseId={caseId} onDone={() => { drawer.hide(); links.reload() }} />)
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-300" data-testid="no-appearance">
        Links are suggestions built from time windows, the camera layout you define and detection class only. No appearance, face or re-identification matching is performed anywhere.
      </p>
      {can('case.write') && (
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Time window (s)"><input aria-label="Time window (s)" type="number" min={1} className={`${inputClass} w-28`} value={f.window_s} onChange={(e) => setF({ ...f, window_s: Number(e.target.value) })} /></Field>
          <Field label="Segment gap (s)"><input aria-label="Segment gap (s)" type="number" min={0} className={`${inputClass} w-28`} value={f.segment_gap_s} onChange={(e) => setF({ ...f, segment_gap_s: Number(e.target.value) })} /></Field>
          <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={f.require_same_class} onChange={(e) => setF({ ...f, require_same_class: e.target.checked })} /> Same detection class</label>
          <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={f.include_external_logs} onChange={(e) => setF({ ...f, include_external_logs: e.target.checked })} /> Include external logs</label>
          <Button variant="primary" busy={busy} onClick={generate}>Generate suggestions</Button>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm">
        <span className="text-slate-300">Show</span>
        <select aria-label="Link status" value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md bg-navy-900 px-3 py-1.5 ring-1 ring-navy-600">
          <option value="">all</option><option value="suggested">suggested</option><option value="accepted">accepted</option><option value="rejected">rejected</option>
        </select>
      </label>
      <Loadable state={links}>
        {(d) => (
          <DataTable
            testId="links-table"
            caption="Suggested cross-camera links"
            rows={d.links}
            rowKey={(l) => l.id}
            onRowClick={open}
            empty={{ title: 'No links yet', hint: can('case.write') ? 'Define the camera layout on the Camera map tab, run analytics so events are indexed, then generate suggestions.' : 'An examiner generates suggestions after defining the camera layout.' }}
            columns={[
              { key: 'id', header: '#', sort: (l) => l.id, render: (l) => <button className="text-accent underline" onClick={(e) => { e.stopPropagation(); open(l) }}>Link {l.id}</button> },
              { key: 'a', header: 'From', render: (l) => `${describe(l.a)}`, text: (l) => describe(l.a) },
              { key: 'b', header: 'To', render: (l) => `${describe(l.b)}`, text: (l) => describe(l.b) },
              { key: 'gap', header: 'Separation (s)', sort: (l) => l.gap_s_min, render: (l) => `${l.gap_s_min.toFixed(1)} – ${l.gap_s_max.toFixed(1)}` },
              { key: 'why', header: 'Why', render: (l) => l.explanation, text: (l) => l.explanation },
              { key: 'st', header: 'Status', sort: (l) => l.status, render: (l) => <Chip tone={STATUS_TONE[l.status]}>{l.status}</Chip> },
            ]}
          />
        )}
      </Loadable>
    </div>
  )
}
