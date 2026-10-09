import { type FormEvent, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import {
  Button, Card, Chip, DataTable, EmptyState, ErrorState, KV, Loadable, PageHeader, Tabs, TriageLabel, Unavailable, inputClass, useAsync, useToast,
} from '../../ui'
import { type EventHit, type SearchResult, analyticsApi, reasonOf } from './api'
import { TriageNav } from './TriageNav'

function Grammar() {
  const g = useAsync(() => analyticsApi.grammar(), [])
  return (
    <details className="rounded bg-navy-900 p-3 text-sm" data-testid="grammar-help">
      <summary className="cursor-pointer font-medium">Query grammar (deterministic, offline)</summary>
      <Loadable state={g} rows={2}>
        {(x) => (
          <div className="mt-2 space-y-2">
            <p className="text-slate-300">{x.summary}</p>
            <ul className="space-y-1">
              {x.clauses.map((c) => (
                <li key={c.form}>
                  <code className="font-mono">{c.form}</code> · e.g. <code className="font-mono">{c.example}</code> · {c.meaning}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Loadable>
    </details>
  )
}

function HitDetail({ h, caseId }: { h: EventHit; caseId: number }) {
  return (
    <div className="space-y-3">
      <TriageLabel />
      <KV
        items={[
          ['Event', h.event_id],
          ['Class', h.class_name],
          ['Kind', h.kind],
          ['Clip', <Link key="c" className="text-accent underline" to={`/cases/${caseId}/recovery/clips/${h.clip_id}`}>#{h.clip_id}</Link>],
          ['Camera (channel)', h.camera ?? 'unknown'],
          ['Frame', h.frame_index],
          ['Nominal time in clip', `${h.nominal_time_s.toFixed(2)} s (NOMINAL)`],
          ['Confidence', h.confidence != null ? h.confidence.toFixed(2) : h.motion_score_peak != null ? `motion peak ${h.motion_score_peak.toFixed(3)}` : '—'],
          ['Absolute time', h.utc ? `${h.utc.lo} .. ${h.utc.hi} (UTC, uncertainty bounds)` : `not placed: ${h.unplaceable_reason ?? h.tz_status}`],
          ['Model', h.model.name ? `${h.model.name} ${h.model.sha256?.slice(0, 12) ?? ''}` : 'none (motion)'],
          ['Clip byte range', `${h.source.clip_start_offset ?? '?'} .. ${h.source.clip_end_offset ?? '?'} in the evidence image`],
        ]}
      />
      <p className="text-xs text-slate-300">{h.source.note}</p>
      <Unavailable what="Per-frame byte offset" reason={h.source.frame_byte_offset.reason} />
      <div className="flex gap-3">
        <Link className="text-accent underline" to={`/cases/${caseId}/triage/results?clip=${h.clip_id}&tab=${h.kind}`}>Open run results</Link>
      </div>
    </div>
  )
}

function EventSearch({ caseId }: { caseId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const drawer = useDetailDrawer()
  const [sp, setSp] = useSearchParams()
  const status = useAsync(() => analyticsApi.status(caseId), [caseId])
  const [q, setQ] = useState(sp.get('q') ?? '')
  const [res, setRes] = useState<SearchResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async (text: string) => {
    setBusy(true)
    setErr(null)
    try {
      setRes(await analyticsApi.search(caseId, text))
    } catch (e) {
      setRes(null)
      setErr(reasonOf(e))
    } finally {
      setBusy(false)
    }
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const next = new URLSearchParams(sp)
    next.set('q', q)
    setSp(next, { replace: true })
    void run(q)
  }
  const reindex = async () => {
    try {
      await analyticsApi.reindex(caseId)
      toast.ok('Event index rebuilt from stored analytics rows (custody entry written).')
      status.reload()
    } catch (e) {
      toast.error(reasonOf(e))
    }
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="index-status">
        <TriageLabel />
        <Loadable state={status} rows={1}>
          {(s) => (
            <span>
              {s.events} events indexed{s.indexed_at ? ` (last ${s.indexed_at.replace('T', ' ').slice(0, 19)})` : ''} · full-text backend {s.fulltext_backend}
            </span>
          )}
        </Loadable>
        {can('case.write') && <Button onClick={reindex}>Reindex events</Button>}
      </div>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2" role="search">
        <label className="min-w-64 flex-1 text-sm">
          <span className="mb-1 block text-slate-300">Search detections and motion</span>
          <input aria-label="Event query" value={q} onChange={(e) => setQ(e.target.value)} placeholder="person camera 2 between 10:00 and 11:00 confidence>0.5" className={inputClass} />
        </label>
        <Button type="submit" variant="primary" busy={busy}>Search</Button>
      </form>
      <Grammar />
      {err && <div role="alert" data-testid="query-error" className="rounded border border-red-400 bg-red-950 p-3 text-sm text-red-100">Query not understood: {err}. See the grammar above.</div>}
      {res && (
        <div className="space-y-2" data-testid="search-results">
          <p className="text-sm" role="status">
            {res.total} hit{res.total === 1 ? '' : 's'}. Interpreted as: <code className="font-mono text-xs">{JSON.stringify(res.interpreted)}</code>
          </p>
          {res.excluded_unplaceable_clips > 0 && (
            <p className="text-sm text-amber-300">
              {res.excluded_unplaceable_clips} clip(s) with no absolute time (ids {res.excluded_unplaceable_clip_ids.join(', ')}) were left out of the time clause; set their device timezone on the Timeline.
            </p>
          )}
          {res.notes.map((n, i) => <p key={i} className="text-xs text-slate-300">{n}</p>)}
          <DataTable
            testId="hits-table"
            caption="Event search hits"
            rows={res.hits}
            rowKey={(h) => h.event_id}
            onRowClick={(h) => drawer.show(`Event ${h.event_id}`, <HitDetail h={h} caseId={caseId} />)}
            empty={{ title: 'No events match this query', hint: 'Broaden the query, or run analytics and reindex.' }}
            columns={[
              { key: 'cls', header: 'Class', sort: (h) => h.class_name, render: (h) => (
                  <button className="text-accent underline" onClick={(e) => { e.stopPropagation(); drawer.show(`Event ${h.event_id}`, <HitDetail h={h} caseId={caseId} />) }}>{h.class_name}</button>
              ) },
              { key: 'kind', header: 'Kind', sort: (h) => h.kind, render: (h) => h.kind },
              { key: 'clip', header: 'Clip', sort: (h) => h.clip_id, render: (h) => `#${h.clip_id}` },
              { key: 'cam', header: 'Camera', sort: (h) => h.camera ?? -1, render: (h) => h.camera ?? 'unknown' },
              { key: 'nt', header: 'Nominal time', sort: (h) => h.nominal_time_s, render: (h) => `${h.nominal_time_s.toFixed(2)} s` },
              { key: 'conf', header: 'Confidence', sort: (h) => h.confidence ?? -1, render: (h) => (h.confidence != null ? h.confidence.toFixed(2) : '—') },
              { key: 'utc', header: 'UTC', render: (h) => (h.utc ? <span className="font-mono text-xs">{h.utc.lo}</span> : <Chip tone="warn" title={h.unplaceable_reason ?? ''}>unplaced</Chip>), text: (h) => h.utc?.lo ?? 'unplaced' },
              { key: 'bytes', header: 'Clip bytes', render: (h) => `${h.source.clip_start_offset ?? '?'}–${h.source.clip_end_offset ?? '?'}` },
              { key: 'fb', header: 'Frame byte offset', render: (h) => <span title={h.source.frame_byte_offset.reason}>not available</span> },
            ]}
          />
          <p className="text-xs text-slate-300">Frame byte offsets are not available: {res.hits[0]?.source.frame_byte_offset.reason ?? 'decoded frames are not mapped back to evidence byte offsets.'}</p>
        </div>
      )}
      {!res && !err && <EmptyState title="Search the indexed detections" hint="Try: person, or motion camera 1. Index a clip by running analytics first." />}
    </div>
  )
}

function Summaries({ caseId }: { caseId: number }) {
  const [by, setBy] = useState<'clip' | 'camera'>('clip')
  const s = useAsync(() => analyticsApi.summaries(caseId, by), [caseId, by])
  return (
    <div className="space-y-3">
      <div role="radiogroup" aria-label="Group summaries by" className="flex gap-2 text-sm">
        {(['clip', 'camera'] as const).map((b) => (
          <label key={b} className="flex items-center gap-1">
            <input type="radio" name="by" checked={by === b} onChange={() => setBy(b)} /> by {b}
          </label>
        ))}
      </div>
      {s.error ? (
        <ErrorState error={s.error} onRetry={s.reload} />
      ) : (
        <Loadable state={s} rows={3}>
          {(d) => (
            <div className="space-y-2" data-testid="summaries">
              <p className="flex flex-wrap items-center gap-2 text-sm"><Chip tone="info">{d.label}</Chip><TriageLabel /> {d.events_indexed} events indexed</p>
              {d.summaries.length === 0 && <EmptyState title="Nothing to summarise yet" hint="Run analytics on a clip; the event index fills automatically." />}
              <ul className="space-y-2">
                {d.summaries.map((g, i) => <li key={i} className="rounded bg-navy-900 p-3 text-sm">{g.text}</li>)}
              </ul>
              <p className="text-xs text-slate-300">Template: {d.template}</p>
            </div>
          )}
        </Loadable>
      )}
    </div>
  )
}

export default function Search() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Event search and summaries" subtitle={<span className="inline-flex flex-wrap items-center gap-2"><TriageLabel /> Face events are detections only: no recognition, no matching.</span>} />
      <TriageNav caseId={caseId} />
      <Card>
        <Tabs
          label="Event search and summaries"
          tabs={[
            { id: 'search', label: 'Event search', render: () => <EventSearch caseId={caseId} /> },
            { id: 'summaries', label: 'Summaries', render: () => <Summaries caseId={caseId} /> },
          ]}
        />
      </Card>
    </div>
  )
}
