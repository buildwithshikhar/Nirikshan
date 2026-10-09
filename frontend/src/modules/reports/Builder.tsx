import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { download, errorText } from '../../lib/http'
import { EvidencePicker } from '../../shell/EvidencePicker'
import { useDetailDrawer } from '../../shell/DetailDrawer'
import { Button, Can, Card, Chip, DataTable, Field, HashText, KV, Loadable, PageHeader, Tabs, fmtBytes, fmtTime, inputClass, useAsync, useToast, type Tone } from '../../ui'
import { type ReportRow, type ReviewStatus, reportsApi } from './api'
import { ReportsNav } from './ReportsNav'

const STATUS_TONE: Record<ReviewStatus, Tone> = { draft: 'neutral', pending_approval: 'warn', approved: 'ok', rejected: 'bad', final: 'accent' }
export const StatusLabel = ({ status }: { status: ReviewStatus }) => (
  <Chip tone={STATUS_TONE[status] ?? 'neutral'} testId="review-status">{status.replace('_', ' ')}</Chip>
)

function ReviewPanel({ reportId, onChanged }: { reportId: number; onChanged: () => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const rv = useAsync(() => reportsApi.review(reportId), [reportId])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const act = async (action: 'request-approval' | 'approve' | 'reject' | 'finalize') => {
    setBusy(true)
    try {
      if (action === 'reject' && note.trim().length < 3) throw new Error('A reason of at least 3 characters is required to reject.')
      await reportsApi.step(reportId, action, action === 'reject' ? { reason: note } : { note })
      toast.ok(`Report ${reportId}: ${action.replace('-', ' ')} recorded (custody entry written).`)
      setNote('')
      rv.reload()
      onChanged()
    } catch (e) {
      toast.error(errorText(e)) // includes the server's two-person-rule refusals
    } finally {
      setBusy(false)
    }
  }
  return (
    <Loadable state={rv}>
      {(r) => (
        <div className="space-y-4" data-testid="review-panel">
          <KV
            items={[
              ['Status', <StatusLabel key="s" status={r.status} />],
              ['Author', r.author],
              ['Requested by', r.requested_by ? `${r.requested_by} (${fmtTime(r.requested_at)})` : '—'],
              ['Approved by', r.approved_by ? `${r.approved_by} (${fmtTime(r.approved_at)})` : '—'],
              ['Rejected by', r.rejected_by ? `${r.rejected_by} (${fmtTime(r.rejected_at)})` : '—'],
              ['Finalized by', r.finalized_by ? `${r.finalized_by} (${fmtTime(r.finalized_at)})` : '—'],
              ['PDF SHA-256', <HashText key="h" value={r.report_sha256} label="report SHA-256" />],
            ]}
          />
          <p className="text-xs text-slate-300">Two-person rule: the author and the requester cannot approve or reject. The server enforces it and its refusal is shown here.</p>
          <div>
            <h3 className="mb-1 font-medium">History</h3>
            {r.events.length === 0 && <p className="text-slate-300">No review steps yet (draft).</p>}
            <ol className="space-y-1">
              {r.events.map((e, i) => (
                <li key={i} className="rounded bg-navy-900 p-2">
                  <b>{e.action}</b> by {e.actor} ({e.actor_role}) at {fmtTime(e.at)}
                  {e.custody_seq != null && ` · custody #${e.custody_seq}`}
                  {e.note && <div className="text-slate-300">{e.note}</div>}
                </li>
              ))}
            </ol>
          </div>
          <Field label="Note (reason is required to reject)">
            <input aria-label="Review note" className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {can('case.write') && r.status === 'draft' && <Button busy={busy} onClick={() => act('request-approval')}>Request approval</Button>}
            {can('report.approve') && r.status === 'pending_approval' && (
              <>
                <Button variant="primary" busy={busy} onClick={() => act('approve')}>Approve</Button>
                <Button variant="danger" busy={busy} onClick={() => act('reject')}>Reject</Button>
              </>
            )}
            {can('report.finalize') && r.status === 'approved' && <Button variant="primary" busy={busy} onClick={() => act('finalize')}>Finalize</Button>}
            {r.status === 'rejected' && <p className="text-slate-300">Rejected is final for this report. Generate a new one.</p>}
            {r.status === 'final' && <p className="text-slate-300">Final. The PDF bytes are unchanged; the status travels in the download file name.</p>}
          </div>
        </div>
      )}
    </Loadable>
  )
}

function PdfTab({ caseId }: { caseId: number }) {
  const toast = useToast()
  const drawer = useDetailDrawer()
  const list = useAsync(() => reportsApi.list(caseId), [caseId])
  const [busy, setBusy] = useState(false)
  const generate = async () => {
    setBusy(true)
    try {
      const r = await reportsApi.generate(caseId)
      toast.ok(`Report ${r.id} generated as a draft (custody entry written).`)
      list.reload()
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const dl = (r: ReportRow) => download(`/api/reports/${r.id}/download`, r.file_name).catch((e) => toast.error(errorText(e)))
  const review = (r: ReportRow) => drawer.show(`Report ${r.id}: review`, <ReviewPanel reportId={r.id} onChanged={list.reload} />)
  return (
    <div className="space-y-4">
      <p data-testid="draft-note" className="text-sm text-slate-300">
        Reports are generated from the case record and custody chain as a draft for the examiner and a reviewer. This is software output, not legal advice, and a
        report is only as reliable as the reference-data validation behind it.
      </p>
      <Can perm="case.write">
        <Button variant="primary" busy={busy} onClick={generate}>Generate report</Button>
      </Can>
      <Loadable state={list}>
        {(rows) => (
          <DataTable
            testId="report-table"
            caption="Generated PDF reports"
            rows={rows}
            rowKey={(r) => r.id}
            empty={{ title: 'No report generated yet', hint: 'An examiner generates the first draft with the button above.' }}
            columns={[
              { key: 'id', header: '#', sort: (r) => r.id, render: (r) => r.id },
              { key: 'at', header: 'Generated', sort: (r) => r.generated_at, render: (r) => fmtTime(r.generated_at) },
              { key: 'by', header: 'Examiner', sort: (r) => r.examiner, render: (r) => r.examiner },
              { key: 'sha', header: 'SHA-256', render: (r) => <HashText value={r.sha256} label="report SHA-256" />, text: (r) => r.sha256 },
              { key: 'size', header: 'Size', render: (r) => `${fmtBytes(r.size_bytes)}, ${r.pages} p.` },
              { key: 'chain', header: 'Custody chain', render: (r) => (r.chain_ok ? <Chip tone="ok">VALID at generation</Chip> : <Chip tone="bad">BROKEN at generation</Chip>) },
              { key: 'st', header: 'Approval', sort: (r) => r.review_status, render: (r) => <StatusLabel status={r.review_status} /> },
              {
                key: 'act',
                header: 'Actions',
                render: (r) => (
                  <span className="flex gap-2">
                    <Button aria-label={`Download PDF for report ${r.id}`} onClick={() => dl(r)}>Download PDF</Button>
                    <Button aria-label={`Review report ${r.id}`} onClick={() => review(r)}>Review</Button>
                  </span>
                ),
              },
            ]}
          />
        )}
      </Loadable>
    </div>
  )
}

function CertificateTab({ caseId }: { caseId: number }) {
  const toast = useToast()
  return (
    <div className="space-y-4">
      <div role="note" data-testid="cert-draft" className="rounded border border-amber-400 bg-navy-900 p-3 text-sm">
        <b className="text-amber-300">DRAFT.</b> This is a draft of a BSA section 63(4) certificate (Bharatiya Sakshya Adhiniyam, 2023) prepared from the
        recorded acquisition. It is not a signed certificate and not legal advice: the responsible person must review, complete and sign it.
      </div>
      <EvidencePicker caseId={caseId}>
        {(ev) => (
          <Button
            variant="primary"
            onClick={() => download(`/api/cases/${caseId}/certificate-draft?evidence_id=${ev.id}`, `DRAFT_certificate_evidence${ev.id}.pdf`).catch((e) => toast.error(errorText(e)))}
          >
            Download DRAFT certificate for evidence #{ev.id}
          </Button>
        )}
      </EvidencePicker>
    </div>
  )
}

export default function Builder() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Report builder" subtitle="Generate PDF reports, move them through approval, and prepare a draft BSA 63(4) certificate. Reference test data only." />
      <ReportsNav caseId={caseId} />
      <Card>
        <Tabs
          label="Report builder"
          tabs={[
            { id: 'pdf', label: 'PDF report', render: () => <PdfTab caseId={caseId} /> },
            { id: 'certificate', label: 'Draft BSA 63(4) certificate', render: () => <CertificateTab caseId={caseId} /> },
          ]}
        />
      </Card>
    </div>
  )
}
