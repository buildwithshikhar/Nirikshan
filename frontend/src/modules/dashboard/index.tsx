import { Link } from 'react-router-dom'
import { type CustodyEntry, api } from '../../api'
import { apiJobs } from '../../api_jobs'
import { reportApi } from '../../api_report'
import { Button, Card, Chip, DataTable, EmptyState, HashText, KV, Loadable, PageHeader, Tabs, fmtTime, useAsync } from '../../ui'
import { useCase } from '../../shell/CaseContext'
import { type AuditRow, type Performance, dashApi } from './api'

const pct = (r?: { available: boolean; rate?: number; numerator?: number; denominator?: number; reason?: string }) =>
  r?.available ? `${Math.round((r.rate ?? 0) * 100)}% (${r.numerator} of ${r.denominator})` : `not available: ${r?.reason ?? 'no data'}`

function System() {
  const sys = useAsync(() => api.system(), [])
  return (
    <Card title="System">
      <Loadable state={sys} rows={2}>
        {(s) => (
          <ul className="space-y-1 text-sm text-slate-300">
            <li>Tool version {s.tool_version}</li>
            <li data-testid="ffmpeg-status">ffmpeg: {s.ffmpeg.available ? s.ffmpeg.version : 'not installed (degraded mode)'}</li>
            <li>Clock NTP sync: {s.ntp_status}</li>
            <li className="font-mono text-xs">Custody signing key id {s.signing_key_id}</li>
          </ul>
        )}
      </Loadable>
    </Card>
  )
}

function Stat({ label, value, hint, to }: { label: string; value: string | number; hint?: string; to?: string }) {
  const body = (
    <>
      <div className="text-sm text-slate-400">{label}</div>
      <div className="mt-1 text-3xl font-bold text-accent">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </>
  )
  return to ? <Link to={to} className="block rounded-lg bg-navy-800 p-4 hover:bg-navy-700">{body}</Link> : <div className="rounded-lg bg-navy-800 p-4">{body}</div>
}

function CaseStats({ caseId }: { caseId: number }) {
  const s = useAsync(async () => {
    const [evidence, jobs, reports, perf] = await Promise.all([
      api.listEvidence(caseId),
      apiJobs.list(caseId),
      reportApi.list(caseId),
      dashApi.performance(caseId).catch(() => null as Performance | null),
    ])
    const runs = (await Promise.all(evidence.map((e) => api.runs(e.id).catch(() => [])))).flat()
    const clips = runs.flatMap((r) => r.clips)
    return { evidence, jobs, reports, perf, runs, clips }
  }, [caseId])
  return (
    <Loadable state={s} rows={5}>
      {({ evidence, jobs, reports, perf, runs, clips }) => (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Evidence items" value={evidence.length} hint={`${evidence.filter((e) => e.last_verify_ok).length} verified`} to={`/cases/${caseId}/evidence`} />
            <Stat label="Carve runs" value={runs.length} to={`/cases/${caseId}/recovery`} />
            <Stat label="Recovered clips" value={clips.filter((c) => c.kind === 'clip').length} hint={`${clips.filter((c) => c.kind === 'orphan').length} orphan ranges`} to={`/cases/${caseId}/recovery`} />
            <Stat label="Jobs" value={jobs.length} hint={`${jobs.filter((j) => j.active).length} active, ${jobs.filter((j) => j.status === 'failed').length} failed`} to={`/cases/${caseId}/jobs`} />
            <Stat label="Reports" value={reports.length} to={`/cases/${caseId}/reports`} />
          </div>
          <Card title="Success rates (this tool's own output, not accuracy)">
            {perf?.success_rates.available ? (
              <KV
                items={[
                  ['Segments recovered as clips', pct(perf.success_rates.segment_recovery)],
                  ['Clips extracted and decoded cleanly', pct(perf.success_rates.extraction_clean)],
                  ['Analytics runs completed', pct(perf.success_rates.analytics_completed)],
                  ['Note', perf.success_rates.note ?? ''],
                ]}
              />
            ) : (
              <EmptyState title="No completed runs yet" hint={perf?.success_rates.reason ?? 'Run an analysis from Recovery Lab.'} action={<Link className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/recovery`}>Open Recovery Lab</Link>} />
            )}
          </Card>
          {perf && perf.runs.length > 0 && (
            <Card title="Per-run bottleneck">
              <DataTable
                caption="Per-run bottleneck"
                rows={perf.runs}
                rowKey={(r) => r.run_id}
                columns={[
                  { key: 'run', header: 'Run', render: (r) => `#${r.run_id}`, sort: (r) => r.run_id },
                  { key: 'ev', header: 'Evidence', render: (r) => `#${r.evidence_id}`, sort: (r) => r.evidence_id },
                  { key: 'sec', header: 'Seconds', render: (r) => r.total_seconds?.toFixed(2) ?? '—', sort: (r) => r.total_seconds ?? 0 },
                  { key: 'bn', header: 'Bottleneck', render: (r) => (r.bottleneck.available ? `${r.bottleneck.stage} (${Math.round((r.bottleneck.share ?? 0) * 100)}%${r.bottleneck.dominant ? ', dominant' : ''})` : r.bottleneck.reason ?? 'none'), text: (r) => r.bottleneck.stage ?? '' },
                  { key: 'iso', header: 'Worker', render: (r) => (r.isolated_worker ? 'subprocess worker' : 'in-process'), sort: (r) => String(r.isolated_worker) },
                ]}
              />
            </Card>
          )}
        </div>
      )}
    </Loadable>
  )
}

function Activity({ caseId }: { caseId: number }) {
  const s = useAsync(async () => ({ custody: await api.custody(caseId), audit: await dashApi.audit(caseId).catch(() => [] as AuditRow[]) }), [caseId])
  return (
    <Loadable state={s}>
      {({ custody, audit }) => (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Latest custody entries" actions={<Link className="text-sm underline" to={`/cases/${caseId}/integrity`}>Integrity Center</Link>}>
            {custody.length === 0 ? <EmptyState title="No custody entries yet" /> : (
              <ul className="space-y-1 text-sm">
                {[...custody].reverse().slice(0, 10).map((e: CustodyEntry) => (
                  <li key={e.seq} className="flex justify-between gap-3"><span><span className="font-mono text-xs text-slate-400">#{e.seq}</span> {e.action}</span><span className="text-xs text-slate-400">{fmtTime(e.timestamp_utc)}</span></li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Latest API requests (audit)">
            {audit.length === 0 ? <EmptyState title="No audit rows for this case" /> : (
              <ul className="space-y-1 text-sm">
                {audit.slice(0, 10).map((a) => (
                  <li key={a.id} className="flex justify-between gap-3"><span className="min-w-0 truncate"><span className="font-mono text-xs">{a.method}</span> {a.path} <span className="text-slate-400">({a.status_code})</span></span><span className="shrink-0 text-xs text-slate-400">{fmtTime(a.timestamp_utc)}</span></li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </Loadable>
  )
}

function Health({ caseId }: { caseId: number }) {
  const s = useAsync(async () => ({ chain: await api.verifyChain(caseId), evidence: await api.listEvidence(caseId) }), [caseId])
  return (
    <Loadable state={s}>
      {({ chain, evidence }) => (
        <div className="space-y-4">
          <Card title="Custody chain">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <Chip tone={chain.ok ? 'ok' : 'bad'}>{chain.ok ? 'CHAIN VALID' : 'CHAIN BROKEN'}</Chip>
              <span>{chain.entries} entries, key {chain.key_id}</span>
              <HashText value={chain.head_hash} label="head hash" head={20} />
            </div>
            {chain.failures.length > 0 && <ul className="mt-2 text-sm text-red-300">{chain.failures.map((f) => <li key={f.seq}>#{f.seq}: {f.reason}</li>)}</ul>}
          </Card>
          <Card title="Evidence hash status">
            <DataTable
              caption="Evidence hash status"
              rows={evidence}
              rowKey={(e) => e.id}
              empty={{ title: 'No evidence acquired', hint: 'Acquire an image to start the chain.' }}
              columns={[
                { key: 'l', header: 'Evidence', render: (e) => `#${e.id} ${e.label}`, sort: (e) => e.id },
                { key: 's', header: 'Last verification', render: (e) => (e.last_verified_at ? <Chip tone={e.last_verify_ok ? 'ok' : 'bad'}>{e.last_verify_ok ? 'hashes match' : 'MISMATCH'}</Chip> : <Chip>never re-verified</Chip>), sort: (e) => e.last_verified_at },
                { key: 'w', header: 'When', render: (e) => fmtTime(e.last_verified_at) },
              ]}
            />
          </Card>
        </div>
      )}
    </Loadable>
  )
}

export default function DashboardModule() {
  const { caseId, kase, cases } = useCase()
  const needCase = (render: (id: number) => React.ReactNode) =>
    caseId == null ? (
      <EmptyState title="No case selected" hint={cases.length ? 'Pick a case in the top bar.' : 'Create your first case to start.'} action={<Link className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to="/cases">Go to Cases</Link>} />
    ) : (
      render(caseId)
    )
  return (
    <div className="space-y-5">
      <PageHeader title="Dashboard" subtitle={kase ? `${kase.case_number}: ${kase.title}` : `${cases.length} case${cases.length === 1 ? '' : 's'} in this workspace`} actions={<Link to="/cases"><Button>All cases</Button></Link>} />
      <Tabs
        label="Dashboard sections"
        tabs={[
          { id: 'stats', label: 'Case stats', render: () => needCase((id) => <CaseStats caseId={id} />) },
          { id: 'activity', label: 'Recent activity', render: () => needCase((id) => <Activity caseId={id} />) },
          { id: 'health', label: 'Integrity health', render: () => needCase((id) => <Health caseId={id} />) },
        ]}
      />
      <System />
    </div>
  )
}
