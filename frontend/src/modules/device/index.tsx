import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { EvidencePicker } from '../../shell/EvidencePicker'
import { Button, Card, Chip, DataTable, KV, Loadable, PageHeader, Tabs, TierChip, Unavailable, fmtBytes, useAsync, useToast } from '../../ui'
import { type IdField, type Identification, type OemEntry, type ParserIdentification, deviceApi } from './api'

const hex = (n: number) => `0x${n.toString(16)}`

/** Never guesses: a field the API reports as unknown is shown as "unknown" with the API's reason. */
function IdValue({ f }: { f: IdField }) {
  const known = f.value != null && f.status !== 'unknown'
  return (
    <span data-testid={`idfield-${known ? 'known' : 'unknown'}`}>
      {known ? <b>{f.value}</b> : <b className="text-red-200">unknown</b>}{' '}
      <Chip tone={known ? 'info' : 'bad'}>{f.status}</Chip>
      <span className="mt-0.5 block text-xs text-slate-400">{f.note}{f.source ? ` (${f.source})` : ''}</span>
    </span>
  )
}

function SignatureTab({ id }: { id: Identification }) {
  const drawer = useDetailDrawer()
  const show = (p: ParserIdentification) =>
    drawer.show(`${p.vendor} signatures`, (
      <div className="space-y-3 text-sm">
        <KV items={[['Tier', <TierChip key="t" tier={p.tier} />], ['Confidence', p.confidence], ['Parser version', p.parser_version], ['Rule', p.confidence_rule ?? '—']]} />
        <ul className="space-y-2">
          {p.signatures.map((s) => (
            <li key={s.name} className="rounded bg-navy-900 p-2">
              <b className="font-mono text-xs">{s.name}</b> <Chip tone={s.matched ? 'ok' : 'neutral'}>{s.matched ? `matched x${s.count}` : 'not matched'}</Chip>
              {s.offsets.length > 0 && <p className="text-xs">offsets: {s.offsets.map(hex).join(', ')}</p>}
              {s.details.map((d) => <p key={d} className="text-xs text-slate-300">{d}</p>)}
              {s.reason && <p className="text-xs text-slate-400">{s.reason}</p>}
            </li>
          ))}
        </ul>
        {p.basis.map((b) => <p key={b} className="text-xs text-slate-400">{b}</p>)}
        {p.notes.map((n) => <p key={n} className="text-xs text-amber-300">{n}</p>)}
      </div>
    ))
  return (
    <Card title="Signature matches with confidence">
      <p className="mb-2 text-xs text-slate-400">Public byte-level signatures only, read from published research. Confidence is at most "medium": no vendor is above Tier B and none is validated on a real device.</p>
      <DataTable
        rows={id.parsers}
        caption="Vendor signature matches"
        rowKey={(p) => p.vendor}
        columns={[
          { key: 'v', header: 'Vendor', sort: (p) => p.vendor, render: (p) => <button className="text-accent underline" onClick={() => show(p)} aria-label={`Show signatures for ${p.vendor}`}>{p.vendor}</button>, text: (p) => p.vendor },
          { key: 't', header: 'Tier', sort: (p) => p.tier, render: (p) => <TierChip tier={p.tier} /> },
          { key: 'c', header: 'Confidence', sort: (p) => p.confidence, render: (p) => <Chip tone={p.matched ? 'info' : 'neutral'}>{p.confidence}</Chip> },
          { key: 'm', header: 'Signatures matched', sort: (p) => p.signatures_matched, render: (p) => `${p.signatures_matched} of ${p.signatures_total}` },
        ]}
        empty={{ title: 'No parsers reported' }}
      />
    </Card>
  )
}

function SelectionTab({ id }: { id: Identification }) {
  const reg = useAsync((s) => deviceApi.registry(s), [])
  return (
    <div className="space-y-4">
      <Card title="Parser selection">
        <KV items={[['Routing', <b key="r" data-testid="routing-engine">{id.routing.engine}</b>], ['Reason', id.routing.reason], ['Matches', id.matches.length ? id.matches.map((m) => `${m.vendor} (Tier ${m.tier}, ${m.confidence})`).join('; ') : 'none'], ['Ambiguous', id.ambiguous ? 'yes: more than one vendor matched' : 'no']]} />
      </Card>
      <Card title="OEM registry: support level per vendor">
        <Loadable state={reg} rows={3}>
          {(r) => (
            <>
              <ul className="mb-2 list-disc pl-5 text-xs text-slate-300">{r.policy.map((p) => <li key={p}>{p}</li>)}</ul>
              <DataTable<OemEntry>
                rows={r.oems}
                caption="OEM registry support levels"
                rowKey={(o) => o.name}
                columns={[
                  { key: 'n', header: 'Vendor', sort: (o) => o.name, render: (o) => o.name },
                  { key: 't', header: 'Tier', sort: (o) => o.tier, render: (o) => <TierChip tier={o.tier} /> },
                  { key: 'e', header: 'Standard export', render: (o) => o.standard_export_support.level, text: (o) => o.standard_export_support.level },
                  { key: 'p', header: 'Proprietary storage', render: (o) => o.proprietary_storage_parsing.level, text: (o) => o.proprietary_storage_parsing.level },
                  { key: 'd', header: 'Deleted video recovery', render: (o) => o.deleted_video_recovery.level, text: (o) => o.deleted_video_recovery.level },
                  {
                    key: 's', header: 'Source confidence',
                    render: (o) => o.sources.map((s) => `${s}: ${r.sources[s]?.confidence ?? '?'}`).join(', '),
                  },
                ]}
              />
              <p className="mt-2 text-xs text-slate-400">Registry entries are built from published research and open-source format documentation; nothing implies validation on a real device.</p>
            </>
          )}
        </Loadable>
      </Card>
    </div>
  )
}

function UnknownTab({ id }: { id: Identification }) {
  return (
    <div className="space-y-4">
      <Card title="Unknown-device view">
        <KV
          items={[
            ['Manufacturer', <IdValue key="m" f={id.manufacturer} />],
            ...Object.entries(id.device).map(([k, f]) => [k.replace(/_/g, ' '), <IdValue key={k} f={f} />] as [string, React.ReactNode]),
          ]}
        />
      </Card>
      {id.not_identifiable && (
        <Card title="What cannot be identified">
          <p className="text-sm">{id.not_identifiable.reason}</p>
          {id.not_identifiable.vendors.length > 0 && <p className="mt-1 text-xs text-slate-300">Vendors with no supported signature: {id.not_identifiable.vendors.join(', ')}</p>}
        </Card>
      )}
      <Card title="Limits">
        <ul className="list-disc pl-5 text-xs text-slate-300">{id.limits.map((l) => <li key={l}>{l}</li>)}</ul>
      </Card>
    </div>
  )
}

function Result({ evId }: { evId: number }) {
  const toast = useToast()
  const state = useAsync((s) => deviceApi.identification(evId, false, s), [evId])
  const [busy, setBusy] = useState(false)
  const redo = async () => {
    setBusy(true)
    try {
      const fresh = await deviceApi.identification(evId, true)
      state.setData(fresh)
      toast.ok('Identification refreshed')
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Loadable state={state} rows={5}>
      {(id) =>
        !id.available ? (
          <Unavailable what="Identification" reason={id.reason} />
        ) : (
          <div className="space-y-4">
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm">
                  Manufacturer: <b data-testid="manufacturer">{id.manufacturer.value ?? 'unknown'}</b> <Chip tone={id.manufacturer.value ? 'info' : 'bad'}>{id.manufacturer.status}</Chip>{' '}
                  <span className="text-xs text-slate-400">image {fmtBytes(id.image_size)} · tool {id.tool_version} · {id.cached ? 'cached result' : 'fresh result'}</span>
                </p>
                <Button busy={busy} onClick={redo}>Refresh identification</Button>
              </div>
              <p className="mt-1 text-xs text-slate-400">Reference test data built from published research; this is signature matching, not validation on a real device.</p>
            </Card>
            <Tabs
              label="Identification sections"
              tabs={[
                { id: 'signatures', label: 'Signature matches', render: () => <SignatureTab id={id} /> },
                { id: 'selection', label: 'Parser selection', render: () => <SelectionTab id={id} /> },
                { id: 'unknown', label: 'Unknown-device view', render: () => <UnknownTab id={id} /> },
              ]}
            />
          </div>
        )
      }
    </Loadable>
  )
}

export default function DeviceModule() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Identification result" subtitle="Device intelligence from documented signatures. Unknown stays unknown." />
      <EvidencePicker caseId={caseId}>{(ev) => <Result key={ev.id} evId={ev.id} />}</EvidencePicker>
    </div>
  )
}
