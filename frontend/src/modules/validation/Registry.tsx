import { Card, Chip, DataTable, EmptyState, Loadable, PageHeader, Tabs, TierChip, useAsync, type Tone } from '../../ui'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { type Oem, type OemRegistry, validationApi } from './api'
import { Basis, ValidationNav } from './shared'

const CONF_TONE: Record<string, Tone> = { high: 'ok', medium: 'warn', low: 'bad' }
const ORDER = ['low', 'medium', 'high']

/** Weakest source behind an OEM row: the honest summary of how well its claims are supported. */
const weakest = (o: Oem, reg: OemRegistry) => {
  const cs = o.sources.map((s) => reg.sources[s]?.confidence).filter(Boolean) as string[]
  return cs.sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))[0] ?? 'none cited'
}

function OemDetail({ o, reg }: { o: Oem; reg: OemRegistry }) {
  return (
    <div className="space-y-3">
      <div className="flex gap-2"><TierChip tier={o.tier} /> {o.parser_version && <Chip>parser {o.parser_version}</Chip>}</div>
      <section><h3 className="font-medium">Standard export ingest</h3><p>{o.standard_export_support.level}: {o.standard_export_support.detail}</p></section>
      <section><h3 className="font-medium">Proprietary storage parsing</h3><p>{o.proprietary_storage_parsing.level}: {o.proprietary_storage_parsing.detail}</p></section>
      <section><h3 className="font-medium">Deleted-video recovery</h3><p>{o.deleted_video_recovery.level}: {o.deleted_video_recovery.detail}</p></section>
      <section><h3 className="font-medium">Limitations</h3><ul className="list-disc pl-5">{o.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></section>
      <section>
        <h3 className="font-medium">Sources</h3>
        {o.sources.length === 0 && <p>None cited.</p>}
        <ul className="space-y-1">
          {o.sources.map((id) => {
            const s = reg.sources[id]
            return s ? (
              <li key={id}><b>{id}</b> <Chip tone={CONF_TONE[s.confidence]}>{s.confidence} confidence</Chip> {s.title}, retrieved {s.retrieved}. Says: {s.says}. Does not say: {s.does_not_say}.</li>
            ) : <li key={id}>{id}</li>
          })}
        </ul>
      </section>
      <section><h3 className="font-medium">Evidence in this repository</h3><p>Tests: {o.evidence.tests.join(', ') || 'none'}. Docs: {o.evidence.docs.join(', ') || 'none'}.</p></section>
    </div>
  )
}

function Matrix({ reg }: { reg: OemRegistry }) {
  const drawer = useDetailDrawer()
  return (
    <div className="space-y-3">
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">{reg.policy.map((p, i) => <li key={i}>{p}</li>)}</ul>
      <p className="text-sm">
        Generic path for every target: <b>standard-export ingest</b> ({reg.generic.standard_export_ingest}) and <b>generic carving</b> ({reg.generic.generic_carving})
      </p>
      <DataTable
        testId="oem-matrix"
        caption={`OEM support matrix, ${reg.targets} targets`}
        pageSize={25}
        rows={reg.oems}
        rowKey={(o) => o.name}
        onRowClick={(o) => drawer.show(o.name, <OemDetail o={o} reg={reg} />)}
        columns={[
          { key: 'n', header: 'OEM', sort: (o) => o.name, render: (o) => <button className="text-accent underline" onClick={(e) => { e.stopPropagation(); drawer.show(o.name, <OemDetail o={o} reg={reg} />) }}>{o.name}</button> },
          { key: 't', header: 'Tier', sort: (o) => o.tier, render: (o) => <TierChip tier={o.tier} /> },
          { key: 'e', header: 'Standard export ingest', render: (o) => o.standard_export_support.level, text: (o) => o.standard_export_support.level },
          { key: 'p', header: 'Proprietary storage parsing', render: (o) => o.proprietary_storage_parsing.level, text: (o) => o.proprietary_storage_parsing.level },
          { key: 'd', header: 'Deleted-video recovery', render: (o) => o.deleted_video_recovery.level },
          { key: 'c', header: 'Weakest source confidence', sort: (o) => ORDER.indexOf(weakest(o, reg)), render: (o) => { const w = weakest(o, reg); return <Chip tone={CONF_TONE[w] ?? 'neutral'}>{w}</Chip> } },
        ]}
      />
      <p className="text-xs text-slate-300">
        {reg.consistent_with_code ? 'This registry is consistent with the parser registry in code.' : `Registry and code disagree: ${reg.consistency_problems.join('; ')}`} Registry version {reg.registry_version}, updated {reg.updated}. Nothing here has been validated on a real device.
      </p>
    </div>
  )
}

function Conflicts({ reg }: { reg: OemRegistry }) {
  const rows = reg.oems.flatMap((o) => o.limitations.filter((l) => /conflict/i.test(l)).map((l) => ({ oem: o.name, text: l })))
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-300">Where public sources disagree or are silent, the parser reports the conflict as a field instead of choosing. The registry lists the ones it records; the parser documents give the full detail (for example docs/parsers/hikvision.md, section Open conflicts).</p>
      <DataTable
        testId="conflicts-table"
        caption="Open source conflicts recorded in the registry"
        rows={rows}
        rowKey={(r) => `${r.oem}-${r.text}`}
        empty={{ title: 'No conflicts recorded in the registry' }}
        columns={[
          { key: 'o', header: 'OEM', render: (r) => r.oem, sort: (r) => r.oem },
          { key: 't', header: 'Conflict', render: (r) => r.text, text: (r) => r.text },
        ]}
      />
    </div>
  )
}

function Versions({ reg }: { reg: OemRegistry }) {
  const rows = reg.oems.filter((o) => o.parser_version)
  return (
    <div className="space-y-3">
      <DataTable
        testId="parser-versions"
        caption="Parser versions"
        rows={rows}
        rowKey={(o) => o.name}
        empty={{ title: 'No parsers registered' }}
        columns={[
          { key: 'o', header: 'Parser', render: (o) => o.name, sort: (o) => o.name },
          { key: 'v', header: 'Version', render: (o) => <span className="font-mono">{o.parser_version}</span> },
          { key: 't', header: 'Tier', render: (o) => <TierChip tier={o.tier} /> },
          { key: 'tests', header: 'Tests', render: (o) => o.evidence.tests.join(', ') },
        ]}
      />
      <p className="text-xs text-slate-300">{reg.targets - rows.length} other targets have no parser: standard-export ingest and generic carving only.</p>
    </div>
  )
}

export default function Registry() {
  const reg = useAsync(() => validationApi.registry(), [])
  return (
    <div>
      <PageHeader title="Compatibility Registry" subtitle="What Nirikshan can and cannot do for each of the 16 recorder targets, with the confidence of the sources behind each claim." />
      <ValidationNav />
      <Card>
        <Loadable state={reg} rows={5}>
          {(r) =>
            r.oems.length === 0 ? (
              <EmptyState title="The registry is empty" />
            ) : (
              <>
                <Tabs
                  label="Compatibility registry"
                  tabs={[
                    { id: 'matrix', label: 'OEM matrix', render: () => <Matrix reg={r} /> },
                    { id: 'conflicts', label: 'Open conflicts', render: () => <Conflicts reg={r} /> },
                    { id: 'versions', label: 'Parser versions', render: () => <Versions reg={r} /> },
                  ]}
                />
                <Basis text="Tier B means a parser exists, written from published research and tested only on reference images generated from the same layout (a circular check). Tier C means standard-export ingest and generic carving only. Nothing is validated on a real device." />
              </>
            )
          }
        </Loadable>
      </Card>
    </div>
  )
}
