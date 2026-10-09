import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { Button, Can, Card, Chip, DataTable, EmptyState, Field, HashText, KV, PageHeader, READONLY_HINT, Tabs, TierChip, inputClass, useAsync, useToast } from '../../ui'
import { ACTIVE_RERUN, type EngineCard, type Rerun, validationApi } from './api'
import { Avail, Basis, MetricView, ValidationNav } from './shared'

function ResultsTab() {
  const summary = useAsync(() => validationApi.summary(), [])
  const cards = useAsync(() => validationApi.scorecards(), [])
  const reg = useAsync(() => validationApi.regression(), [])
  return (
    <div className="space-y-6">
      <Avail state={summary} what="Validation results">
        {(s) => (
          <div className="space-y-3">
            <div data-testid="origin-statement" className="rounded border border-amber-400 bg-navy-900 p-3 text-sm">
              <b className="text-amber-300">Reference test data.</b> {s.headline} {s.disclosure}
            </div>
            <KV
              items={[
                ['Seed / trials', `${s.seed} / ${s.trials}`],
                ['Results digest', <span key="d" className="inline-flex items-center gap-2"><HashText value={s.results_digest} label="results digest" /> {s.digest_verified ? <Chip tone="ok">digest verified</Chip> : <Chip tone="bad">digest does NOT verify</Chip>}</span>],
                ['Results file SHA-256', <HashText key="f" value={s.file_sha256} label="results file SHA-256" />],
              ]}
            />
            <p className="text-sm text-slate-300">{s.tier_limit}</p>
            <ul className="list-disc pl-5 text-xs text-slate-300">{s.disclaimer.map((d, i) => <li key={i}>{d}</li>)}</ul>
            <Basis text={s.basis} />
          </div>
        )}
      </Avail>
      <Avail state={reg} what="Regression thresholds">
        {(r) => (
          <section aria-labelledby="reg-h" className="space-y-2">
            <h2 id="reg-h" className="font-medium">Regression thresholds <Chip tone={r.status === 'pass' ? 'ok' : 'bad'}>{r.status}</Chip></h2>
            <DataTable
              testId="regression-table"
              caption="Regression rules and observed values"
              rows={r.rules}
              rowKey={(x) => `${x.scenario}-${x.metric}`}
              columns={[
                { key: 's', header: 'Scenario', sort: (x) => x.scenario, render: (x) => x.scenario },
                { key: 'm', header: 'Metric', sort: (x) => x.metric, render: (x) => x.metric },
                { key: 'r', header: 'Rule', render: (x) => JSON.stringify(x.rule) },
                { key: 'o', header: 'Observed', render: (x) => <MetricView m={x.observed} /> },
                { key: 'p', header: 'Result', sort: (x) => String(x.pass), render: (x) => <Chip tone={x.pass ? 'ok' : 'bad'}>{x.pass ? 'pass' : 'FAIL'}</Chip> },
              ]}
            />
            <Basis text={r.basis} />
          </section>
        )}
      </Avail>
      <Avail state={cards} what="Scorecards">
        {(c) => (
          <section aria-labelledby="sc-h" className="space-y-4">
            <h2 id="sc-h" className="font-medium">Per-scenario scorecards</h2>
            {c.vendors.map((v) =>
              v.engines.map((e: EngineCard) => (
                <div key={`${v.vendor}-${e.engine}`}>
                  <h3 className="mb-1 text-sm font-medium">{v.vendor} · engine {e.engine} · pooled recall <MetricView m={e.pooled_recall} /> · pooled precision <MetricView m={e.pooled_precision} /></h3>
                  <DataTable
                    caption={`${v.vendor} (${e.engine}) scenario results`}
                    rows={e.scenarios}
                    rowKey={(s) => s.id}
                    pageSize={10}
                    columns={[
                      { key: 't', header: 'Scenario', sort: (s) => s.title, render: (s) => s.title },
                      { key: 'n', header: 'Trials', render: (s) => s.trials },
                      { key: 'rc', header: 'Clip recall', render: (s) => <MetricView m={s.recall} /> },
                      { key: 'pr', header: 'Clip precision', render: (s) => <MetricView m={s.precision} /> },
                      { key: 'fr', header: 'Frame recall', render: (s) => <MetricView m={s.frame_recall} /> },
                    ]}
                  />
                </div>
              )),
            )}
            <Basis text={c.basis} />
          </section>
        )}
      </Avail>
    </div>
  )
}

function TierTab() {
  const cards = useAsync(() => validationApi.scorecards(), [])
  return (
    <Avail state={cards} what="Tier table">
      {(c) => (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">Tier B is the ceiling: a public byte-level signature we read ourselves plus a parser written from published research, unvalidated on any real device. No vendor is above Tier B.</p>
          <DataTable
            testId="tier-table"
            caption="Support tier per vendor"
            filterable={false}
            rows={c.vendors}
            rowKey={(v) => v.vendor}
            columns={[
              { key: 'v', header: 'Vendor', sort: (v) => v.vendor, render: (v) => v.vendor },
              { key: 't', header: 'Tier', render: (v) => (/^[ABCD]$/i.test(v.tier) ? <TierChip tier={v.tier} /> : <span className="text-sm">{v.tier}</span>) },
              { key: 'e', header: 'Engines', render: (v) => v.engines.map((e) => e.engine).join(', ') },
              { key: 'r', header: 'Pooled clip recall', render: (v) => <MetricView m={v.engines[0]?.pooled_recall} /> },
              { key: 'p', header: 'Pooled clip precision', render: (v) => <MetricView m={v.engines[0]?.pooled_precision} /> },
            ]}
          />
          <p className="text-xs text-slate-300">Pooled values add successes and trials across scenarios; they are descriptive only.</p>
          <Basis text={c.basis} />
        </div>
      )}
    </Avail>
  )
}

function ErrorRatesTab() {
  const fr = useAsync(() => validationApi.falseRates(), [])
  const cc = useAsync(() => validationApi.crosscheck(), [])
  return (
    <div className="space-y-6">
      <Avail state={fr} what="False-accept rates">
        {(f) => (
          <section aria-labelledby="neg-h" className="space-y-2">
            <h2 id="neg-h" className="font-medium">False accepts and false positives</h2>
            <DataTable
              testId="negative-table"
              caption="Negative scenarios: images with no valid video"
              rows={f.negative_scenarios}
              rowKey={(x) => `${x.id}-${x.engine}`}
              columns={[
                { key: 't', header: 'Scenario', render: (x) => x.title, sort: (x) => x.title },
                { key: 'i', header: 'Images', render: (x) => x.images },
                { key: 'c', header: 'Clips emitted', render: (x) => <MetricView m={x.clips_emitted} /> },
                { key: 'd', header: 'Decodable clips (false accepts)', render: (x) => <MetricView m={x.false_accept_decodable_clips} /> },
                { key: 'fl', header: 'Emitted but flagged failed', render: (x) => <MetricView m={x.emitted_but_flagged_failed} /> },
              ]}
            />
            <DataTable
              caption="Fragment reassembler false and true accepts"
              rows={f.reassembler}
              rowKey={(x) => `${x.id}-${x.engine}`}
              columns={[
                { key: 't', header: 'Scenario', render: (x) => x.id },
                { key: 'fa', header: 'False accept', render: (x) => <MetricView m={x.reassembler_false_accept} /> },
                { key: 'ta', header: 'True accept', render: (x) => <MetricView m={x.reassembler_true_accept} /> },
              ]}
            />
            <DataTable
              caption="False-positive clips in positive scenarios"
              rows={f.positive_scenario_false_positives}
              rowKey={(x) => `${x.id}-${x.engine}`}
              columns={[
                { key: 't', header: 'Scenario', render: (x) => `${x.id} (${x.engine})`, sort: (x) => x.id },
                { key: 'fp', header: 'False-positive clips', render: (x) => <MetricView m={x.false_positive_clips} /> },
                { key: 'm', header: 'Mixed clips', render: (x) => <MetricView m={x.mixed_clips} /> },
              ]}
            />
            {f.notes.map((n, i) => <p key={i} className="text-xs text-slate-300">{n}</p>)}
            <Basis text={f.basis} />
          </section>
        )}
      </Avail>
      <Avail state={cc} what="Parser vs generic carver cross-check">
        {(c) => (
          <section aria-labelledby="cc-h" className="space-y-2">
            <h2 id="cc-h" className="font-medium">Parser versus generic carver disagreements</h2>
            <p className="text-sm text-slate-300">{c.explanation}</p>
            <DataTable
              testId="crosscheck-table"
              caption="Disagreement counts by vendor and kind"
              rows={Object.entries(c.totals_by_vendor).flatMap(([vendor, kinds]) => Object.entries(kinds).map(([kind, m]) => ({ vendor, kind, m })))}
              rowKey={(x) => `${x.vendor}-${x.kind}`}
              columns={[
                { key: 'v', header: 'Vendor', sort: (x) => x.vendor, render: (x) => x.vendor },
                { key: 'k', header: 'Kind', sort: (x) => x.kind, render: (x) => x.kind },
                { key: 'b', header: 'Benign', render: (x) => (c.benign_definition.includes(x.kind) ? 'yes' : 'no') },
                { key: 'n', header: 'Count', sort: (x) => x.m.count ?? 0, render: (x) => <MetricView m={x.m} /> },
              ]}
            />
            <Basis text={c.basis} />
          </section>
        )}
      </Avail>
    </div>
  )
}

function RerunTab() {
  const { can } = useAuth()
  const toast = useToast()
  const list = useAsync(() => validationApi.reruns(), [])
  const [trials, setTrials] = useState(2)
  const [exp, setExp] = useState(false)
  const [busy, setBusy] = useState(false)
  const active = list.data?.some((r) => ACTIVE_RERUN.includes(r.status))
  useEffect(() => {
    if (!active) return
    const t = setInterval(list.reload, 3000)
    return () => clearInterval(t)
  }, [active, list.reload])
  const start = async () => {
    setBusy(true)
    try {
      const r = await validationApi.startRerun({ trials, export: exp })
      toast.ok(`Re-run ${r.id} started in a time-limited subprocess.`)
      list.reload()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const show = (r: Rerun) => {
    const cmp = r.comparison ?? {}
    return (
    <div className="space-y-1 text-xs" data-testid={`rerun-${r.id}`}>
      <div>Command: <code className="font-mono">{r.command.join(' ')}</code></div>
      {cmp.comparable != null && <div>Comparable to baseline: {String(cmp.comparable)} · digest match: {String(cmp.digest_match)} · baseline file unchanged: {String(r.baseline_unchanged)}</div>}
      {cmp.parameter_or_version_differences && cmp.parameter_or_version_differences.length > 0 && <div>Differences from baseline: <code>{JSON.stringify(cmp.parameter_or_version_differences)}</code></div>}
      {r.error && <div className="text-red-300">{r.error}</div>}
      {r.status === 'completed' && cmp.comparable == null && <div>Finished; no comparison recorded.</div>}
    </div>
    )
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-300">
        A re-run regenerates the reference images and re-measures every scenario in one subprocess (time limit {list.data?.[0]?.timeout_s ?? 3600} s, best-effort limits, not a sandbox). It never overwrites the committed baseline; the comparison says what differs. It repeats the same self-consistency check, so it does not make the numbers independent.
      </p>
      <Can perm="validation.rerun" fallback={<p className="text-sm text-slate-300">{READONLY_HINT}</p>}>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Trials per scenario"><input aria-label="Trials" type="number" min={1} max={50} value={trials} onChange={(e) => setTrials(Number(e.target.value))} className={`${inputClass} w-28`} /></Field>
          <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={exp} onChange={(e) => setExp(e.target.checked)} /> Include export and decode tests (slower)</label>
          <Button variant="primary" busy={busy || !!active} disabled={!can('validation.rerun')} onClick={start}>Start re-run</Button>
        </div>
      </Can>
      {list.data && list.data.length === 0 && <EmptyState title="No re-run yet" hint="The baseline in the Results tab is the committed `make validate` output." />}
      {list.data && list.data.length > 0 && (
        <DataTable
          testId="rerun-table"
          caption="Validation re-runs"
          rows={list.data}
          rowKey={(r) => r.id}
          columns={[
            { key: 'id', header: '#', sort: (r) => r.id, render: (r) => r.id },
            { key: 'st', header: 'Status', sort: (r) => r.status, render: (r) => <Chip tone={r.status === 'completed' ? 'ok' : ACTIVE_RERUN.includes(r.status) ? 'info' : 'bad'} testId={`rerun-status-${r.id}`}>{r.status}</Chip> },
            { key: 'p', header: 'Trials / seed', render: (r) => `${r.params.trials} / ${r.params.seed}` },
            { key: 'by', header: 'By', render: (r) => r.examiner },
            { key: 'd', header: 'Detail', render: show },
          ]}
        />
      )}
    </div>
  )
}

export default function ValidationCenter() {
  return (
    <div>
      <PageHeader
        title="Validation Center"
        subtitle="Self-consistency of the parsers and carver against reference test data built from published research and open-source format documentation. Not real-device validation."
      />
      <ValidationNav />
      <Card>
        <Tabs
          label="Validation Center"
          tabs={[
            { id: 'results', label: 'Results', render: () => <ResultsTab /> },
            { id: 'tiers', label: 'Tier table', render: () => <TierTab /> },
            { id: 'errors', label: 'Error rates', render: () => <ErrorRatesTab /> },
            { id: 'rerun', label: 'Re-run', render: () => <RerunTab /> },
          ]}
        />
      </Card>
    </div>
  )
}
