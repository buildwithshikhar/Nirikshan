import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { useCase } from '../../shell/CaseContext'
import {
  Button, Can, Card, type Column, DataTable, ErrorState, Field, KV, Loadable, PageHeader, Tabs, fmtTime, inputClass, useAsync, useToast,
} from '../../ui'
import { type AuditRow, type Case, type CaseMember, type CustodyEntry, casesApi } from './api'
import { type Evidence, evidenceApi } from '../evidence/api'

function CreateCase({ onCreated }: { onCreated: (c: Case) => void }) {
  const toast = useToast()
  const [f, setF] = useState({ case_number: '', title: '', description: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      const c = await casesApi.create(f)
      toast.ok(`Case ${c.case_number} created`)
      setF({ case_number: '', title: '', description: '' })
      onCreated(c)
    } catch (x) {
      setErr(errorText(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card title="Create case">
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-3" aria-label="Create case">
        <Field label="Case number">
          <input className={inputClass} required value={f.case_number} onChange={(e) => setF({ ...f, case_number: e.target.value })} />
        </Field>
        <div className="md:col-span-2">
          <Field label="Title">
            <input className={inputClass} required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          </Field>
        </div>
        <div className="md:col-span-3">
          <Field label="Description (optional)">
            <input className={inputClass} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
          </Field>
        </div>
        <div>
          <Button type="submit" variant="primary" busy={busy}>
            Create case
          </Button>
        </div>
      </form>
      {err && <p role="alert" className="mt-2 text-sm text-red-300">{err}</p>}
    </Card>
  )
}

export function CaseList() {
  const state = useAsync((s) => casesApi.list(s), [])
  const ctx = useCase()
  const nav = useNavigate()
  const { can } = useAuth()
  const cols: Column<Case>[] = [
    {
      key: 'number', header: 'Number', sort: (c) => c.case_number,
      render: (c) => <Link className="text-accent hover:underline" to={`/cases/${c.id}`}>{c.case_number}</Link>,
    },
    { key: 'title', header: 'Title', sort: (c) => c.title, render: (c) => c.title },
    { key: 'examiner', header: 'Examiner', sort: (c) => c.examiner, render: (c) => c.examiner },
    { key: 'created', header: 'Created (UTC)', sort: (c) => c.created_at, render: (c) => <span className="font-mono text-xs">{fmtTime(c.created_at)}</span> },
  ]
  return (
    <div className="space-y-5">
      <PageHeader title="Cases" subtitle="Cases you are a member of." />
      <Can perm="case.create">
        <CreateCase
          onCreated={(c) => {
            ctx.reload()
            nav(`/cases/${c.id}`)
          }}
        />
      </Can>
      <Card>
        <Loadable state={state}>
          {(rows) => (
            <DataTable
              rows={rows}
              columns={cols}
              caption="Cases"
              rowKey={(c) => c.id}
              empty={{
                title: 'No cases yet',
                hint: can('case.create') ? 'Create the first case with the form above.' : 'Ask an examiner or admin to add you to a case.',
              }}
            />
          )}
        </Loadable>
      </Card>
    </div>
  )
}

function Overview({ kase, caseId }: { kase: Case; caseId: number }) {
  const members = useAsync((s) => casesApi.members(caseId, s), [caseId])
  const ev = useAsync((s) => evidenceApi.list(caseId, s), [caseId])
  return (
    <div className="space-y-4">
      <Card title="Case">
        <KV
          items={[
            ['Case number', kase.case_number],
            ['Title', kase.title],
            ['Description', kase.description || '—'],
            ['Opened by', kase.examiner],
            ['Created (UTC)', fmtTime(kase.created_at)],
            ['Evidence items', ev.data ? String(ev.data.length) : '…'],
          ]}
        />
        <p className="mt-3 flex gap-4 text-sm">
          <Link className="text-accent hover:underline" to={`/cases/${caseId}/timeline`}>Timeline</Link>
          <Link className="text-accent hover:underline" to={`/cases/${caseId}/integrity`}>Integrity and custody</Link>
        </p>
      </Card>
      <Card title="Members (read-only)">
        <Loadable state={members} rows={2}>
          {(rows: CaseMember[]) => (
            <DataTable
              rows={rows}
              caption="Case members"
              rowKey={(m) => m.user_id}
              columns={[
                { key: 'u', header: 'User', sort: (m) => m.display_name, render: (m) => `${m.display_name} (${m.username})` },
                { key: 'r', header: 'Role', sort: (m) => m.role, render: (m) => m.role },
                { key: 'a', header: 'Added', sort: (m) => m.added_at, render: (m) => fmtTime(m.added_at) },
              ]}
              empty={{ title: 'No members' }}
            />
          )}
        </Loadable>
      </Card>
    </div>
  )
}

function EvidenceTab({ caseId }: { caseId: number }) {
  const state = useAsync((s) => evidenceApi.list(caseId, s), [caseId])
  const cols: Column<Evidence>[] = [
    { key: 'id', header: '#', sort: (e) => e.id, render: (e) => e.id },
    {
      key: 'label', header: 'Label', sort: (e) => e.label,
      render: (e) => <Link className="text-accent hover:underline" to={`/cases/${caseId}/evidence/${e.id}`}>{e.label}</Link>,
    },
    { key: 'size', header: 'Size (bytes)', sort: (e) => e.size_bytes, render: (e) => e.size_bytes.toLocaleString() },
    { key: 'status', header: 'Status', sort: (e) => e.status, render: (e) => e.status },
    { key: 'wb', header: 'Write blocker', sort: (e) => e.write_blocker, render: (e) => e.write_blocker },
  ]
  return (
    <Card
      title="Evidence"
      actions={
        <Can perm="case.write">
          <Link className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/evidence/new`}>
            New acquisition
          </Link>
        </Can>
      }
    >
      <Loadable state={state}>
        {(rows) => (
          <DataTable
            rows={rows}
            columns={cols}
            caption="Evidence in this case"
            rowKey={(e) => e.id}
            empty={{ title: 'No evidence acquired yet', hint: 'Acquire the first image read-only from a server-side path.' }}
          />
        )}
      </Loadable>
    </Card>
  )
}

function Activity({ caseId }: { caseId: number }) {
  const custody = useAsync((s) => casesApi.custody(caseId, s), [caseId])
  const audit = useAsync((s) => casesApi.audit(caseId, s), [caseId])
  return (
    <div className="space-y-4">
      <Card title="Custody entries">
        <Loadable state={custody}>
          {(rows: CustodyEntry[]) => (
            <DataTable
              rows={[...rows].reverse()}
              caption="Chain-of-custody entries for this case"
              rowKey={(r) => r.seq}
              columns={[
                { key: 'seq', header: 'Seq', sort: (r) => r.seq, render: (r) => r.seq },
                { key: 't', header: 'Time (UTC)', sort: (r) => r.timestamp_utc, render: (r) => <span className="font-mono text-xs">{fmtTime(r.timestamp_utc)}</span> },
                { key: 'a', header: 'Action', sort: (r) => r.action, render: (r) => r.action },
                { key: 'e', header: 'Evidence', sort: (r) => r.evidence_id ?? 0, render: (r) => r.evidence_id ?? '—' },
                { key: 'x', header: 'Examiner', sort: (r) => r.examiner, render: (r) => r.examiner },
              ]}
              empty={{ title: 'No custody entries' }}
            />
          )}
        </Loadable>
        <p className="mt-2 text-xs text-slate-400">Chain verification lives in the Integrity center.</p>
      </Card>
      <Card title="Access audit">
        {audit.error && audit.data == null ? (
          <ErrorState error={audit.error} onRetry={audit.reload} />
        ) : (
          <Loadable state={audit}>
            {(rows: AuditRow[]) => (
              <DataTable
                rows={rows}
                caption="API access audit for this case"
                rowKey={(r) => r.id}
                columns={[
                  { key: 't', header: 'Time (UTC)', sort: (r) => r.timestamp_utc, render: (r) => <span className="font-mono text-xs">{fmtTime(r.timestamp_utc)}</span> },
                  { key: 'x', header: 'Examiner', sort: (r) => r.examiner, render: (r) => r.examiner },
                  { key: 'm', header: 'Request', sort: (r) => `${r.method} ${r.path}`, render: (r) => <code className="text-xs">{r.method} {r.path}</code> },
                  { key: 's', header: 'Status', sort: (r) => r.status_code, render: (r) => r.status_code },
                ]}
                empty={{ title: 'No audit rows' }}
              />
            )}
          </Loadable>
        )}
      </Card>
    </div>
  )
}

export function CaseDetail() {
  const caseId = Number(useParams().caseId)
  const state = useAsync((s) => casesApi.get(caseId, s), [caseId])
  return (
    <Loadable state={state}>
      {(kase) => (
        <div>
          <PageHeader title={`${kase.case_number}: ${kase.title}`} subtitle="Case detail" />
          <Tabs
            label="Case sections"
            tabs={[
              { id: 'overview', label: 'Overview', render: () => <Overview kase={kase} caseId={caseId} /> },
              { id: 'evidence', label: 'Evidence list', render: () => <EvidenceTab caseId={caseId} /> },
              { id: 'activity', label: 'Activity', render: () => <Activity caseId={caseId} /> },
            ]}
          />
        </div>
      )}
    </Loadable>
  )
}
