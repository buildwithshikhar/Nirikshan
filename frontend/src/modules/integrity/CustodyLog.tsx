import { useParams } from 'react-router-dom'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { Card, DataTable, HashText, KV, Loadable, PageHeader, Tabs, fmtTime, useAsync } from '../../ui'
import { type CustodyEntry, integrityApi } from './api'
import { ChainVerify } from './ChainVerify'
import { IntegrityNav } from './IntegrityNav'

function EntryDetail({ e }: { e: CustodyEntry }) {
  let pretty = e.details_json
  try {
    pretty = JSON.stringify(JSON.parse(e.details_json), null, 2)
  } catch {
    // show the raw text
  }
  return (
    <div className="space-y-3">
      <KV
        items={[
          ['Sequence', e.seq],
          ['Time (UTC)', e.timestamp_utc],
          ['Action', e.action],
          ['Examiner', e.examiner],
          ['Evidence', e.evidence_id ?? '—'],
          ['Tool version', e.tool_version],
          ['Clock (NTP)', e.ntp_status],
          ['Key id', e.key_id],
          ['Previous hash', <HashText key="p" value={e.prev_hash} label="previous hash" head={16} />],
          ['Entry hash', <HashText key="h" value={e.entry_hash} label="entry hash" head={16} />],
          ['Signature', <HashText key="s" value={e.signature} label="signature" head={16} />],
        ]}
      />
      <div>
        <h3 className="mb-1 font-medium">Details as recorded</h3>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-navy-900 p-2 text-xs">{pretty}</pre>
      </div>
    </div>
  )
}

function ChainView({ caseId }: { caseId: number }) {
  const drawer = useDetailDrawer()
  const entries = useAsync(() => integrityApi.custody(caseId), [caseId])
  return (
    <div className="space-y-4">
      <ChainVerify caseId={caseId} />
      <Loadable state={entries} rows={6}>
        {(rows) => (
          <DataTable
            testId="custody-table"
            caption="Custody log entries"
            rows={rows}
            rowKey={(e) => e.seq}
            pageSize={25}
            onRowClick={(e) => drawer.show(`Custody entry ${e.seq}`, <EntryDetail e={e} />)}
            empty={{ title: 'No custody entries yet', hint: 'Entries are written as soon as evidence is acquired.' }}
            columns={[
              { key: 'seq', header: '#', sort: (e) => e.seq, render: (e) => e.seq },
              { key: 'time', header: 'Time (UTC)', sort: (e) => e.timestamp_utc, render: (e) => <span className="font-mono text-xs">{fmtTime(e.timestamp_utc.slice(0, 26))}</span> },
              {
                key: 'action',
                header: 'Action',
                sort: (e) => e.action,
                render: (e) => (
                  <button className="text-accent underline" onClick={(ev) => { ev.stopPropagation(); drawer.show(`Custody entry ${e.seq}`, <EntryDetail e={e} />) }}>
                    {e.action}
                  </button>
                ),
              },
              { key: 'who', header: 'Examiner', sort: (e) => e.examiner, render: (e) => e.examiner },
              { key: 'hash', header: 'Entry hash', render: (e) => <HashText value={e.entry_hash} label={`entry ${e.seq} hash`} head={10} />, text: (e) => e.entry_hash },
              { key: 'key', header: 'Key id', render: (e) => <span className="font-mono text-xs">{e.key_id}</span> },
            ]}
          />
        )}
      </Loadable>
    </div>
  )
}

function HeadHashTab({ caseId }: { caseId: number }) {
  const chain = useAsync(() => integrityApi.verifyChain(caseId), [caseId])
  return (
    <Loadable state={chain}>
      {(c) => (
        <div className="space-y-4">
          <p className="text-sm text-slate-300">Custody head_hash after {c.entries} entries (signed with key {c.key_id}):</p>
          <div className="flex flex-wrap items-center gap-3 rounded-lg bg-navy-900 p-4" data-testid="head-hash">
            <code className="break-all font-mono text-lg">{c.head_hash}</code>
            <HashText value={c.head_hash} label="custody head hash" head={0} />
          </div>
          <p className="text-sm">
            Record this value outside the system (a signed note, a ticket, a printout). A truncated or rolled-back log can only be detected against a head hash that
            was recorded elsewhere.
          </p>
          <p className="text-sm">{c.ok ? 'The chain verified at load time.' : 'The chain did NOT verify: use the Chain view for the failing entries.'}</p>
        </div>
      )}
    </Loadable>
  )
}

function AuditTab({ caseId }: { caseId: number }) {
  const rows = useAsync(() => integrityApi.audit(caseId), [caseId])
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-300">API request audit for this case (most recent first, up to 200). The audit trail is separate from the signed custody chain.</p>
      <Loadable state={rows} rows={6}>
        {(list) => (
          <DataTable
            testId="audit-table"
            caption="API audit trail"
            rows={list}
            rowKey={(r) => r.id}
            pageSize={25}
            empty={{ title: 'No audited requests for this case yet' }}
            columns={[
              { key: 'time', header: 'Time (UTC)', sort: (r) => r.timestamp_utc, render: (r) => <span className="font-mono text-xs">{fmtTime(r.timestamp_utc.slice(0, 26))}</span> },
              { key: 'who', header: 'Principal', sort: (r) => r.examiner, render: (r) => r.examiner },
              { key: 'm', header: 'Method', sort: (r) => r.method, render: (r) => r.method },
              { key: 'p', header: 'Path', sort: (r) => r.path, render: (r) => <span className="break-all font-mono text-xs">{r.path}</span> },
              { key: 's', header: 'Status', sort: (r) => r.status_code, render: (r) => r.status_code },
            ]}
          />
        )}
      </Loadable>
    </div>
  )
}

export default function CustodyLog() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Custody log" subtitle="Append-only, hash-chained and signed. Reference test data only; the chain proves tampering within the log, not who the examiner was." />
      <IntegrityNav caseId={caseId} />
      <Card>
        <Tabs
          label="Custody log views"
          tabs={[
            { id: 'chain', label: 'Chain view', render: () => <ChainView caseId={caseId} /> },
            { id: 'head', label: 'head_hash', render: () => <HeadHashTab caseId={caseId} /> },
            { id: 'audit', label: 'Audit trail', render: () => <AuditTab caseId={caseId} /> },
          ]}
        />
      </Card>
    </div>
  )
}
