import { useState } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { READONLY_HINT } from '../../ui'
import { refreshStatusBanners } from '../../shell/CaseStatus'
import {
  Button, Can, Card, Chip, type Column, DataTable, Field, HashText, KV, Loadable, PageHeader, Tabs, Unavailable, fmtBytes, fmtTime, inputClass, useAsync, useToast,
} from '../../ui'
import { casesApi } from '../cases/api'
import { SourcePicker } from './SourcePicker'
import { type BadSectors, type Evidence, evidenceApi } from './api'

const verifyChip = (e: Evidence) =>
  e.last_verify_ok === 1 ? <Chip tone="ok">verified {fmtTime(e.last_verified_at)}</Chip> : e.last_verify_ok === 0 ? <Chip tone="bad">integrity failure</Chip> : <Chip>never verified</Chip>

function EvidenceList() {
  const caseId = Number(useParams().caseId)
  const toast = useToast()
  const { can } = useAuth()
  const list = useAsync((s) => evidenceApi.list(caseId, s), [caseId])
  const sessions = useAsync((s) => evidenceApi.sessions(caseId, s), [caseId])
  const [busy, setBusy] = useState<number | null>(null)
  const resume = async (id: number) => {
    setBusy(id)
    try {
      const r = await evidenceApi.resume(id)
      toast.ok(`Acquisition ${id} ${r.status}`)
      refreshStatusBanners()
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(null)
      list.reload()
      sessions.reload()
    }
  }
  const cols: Column<Evidence>[] = [
    { key: 'id', header: '#', sort: (e) => e.id, render: (e) => e.id },
    {
      key: 'label', header: 'Label', sort: (e) => e.label,
      render: (e) => (
        <>
          <Link className="text-accent hover:underline" to={`/cases/${caseId}/evidence/${e.id}`}>{e.label}</Link>
          {e.synthetic && <span className="ml-2"><Chip tone="warn">Reference data</Chip></span>}
        </>
      ),
    },
    { key: 'size', header: 'Size', sort: (e) => e.size_bytes, render: (e) => fmtBytes(e.size_bytes) },
    { key: 'sha', header: 'SHA-256', render: (e) => <HashText value={e.sha256} label={`SHA-256 of evidence ${e.id}`} />, text: (e) => e.sha256 },
    { key: 'wb', header: 'Write blocker', sort: (e) => e.write_blocker, render: (e) => e.write_blocker },
    { key: 'v', header: 'Verification', sort: (e) => e.last_verify_ok, render: verifyChip },
  ]
  const open = (sessions.data ?? []).filter((s) => s.status === 'interrupted' || s.status === 'in_progress')
  return (
    <div className="space-y-4">
      <PageHeader
        title="Evidence"
        subtitle="Acquired evidence items. Sources are copied read-only; hashes are of the copy."
        actions={
          can('case.write') ? (
            <Link className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/evidence/new`}>
              New acquisition
            </Link>
          ) : (
            <span className="text-xs text-slate-400" title={READONLY_HINT}>Read-only role: no new acquisitions</span>
          )
        }
      />
      {open.length > 0 && (
        <Card title="Interrupted acquisitions">
          <ul className="space-y-2 text-sm">
            {open.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3">
                <span>
                  Session {s.id} ({s.status}): {Math.round(s.progress * 100)}% of {fmtBytes(s.source_size)} from <code className="text-xs">{s.source_path}</code>
                </span>
                <Can perm="case.write">
                  <Button busy={busy === s.id} onClick={() => resume(s.id)} aria-label={`Resume acquisition ${s.id}`}>
                    Resume
                  </Button>
                </Can>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <Loadable state={list}>
          {(rows) => (
            <DataTable
              rows={rows}
              columns={cols}
              caption="Evidence items"
              rowKey={(e) => e.id}
              empty={{
                title: 'No evidence acquired yet',
                hint: can('case.write') ? 'Start with a new acquisition.' : 'An examiner must acquire the first item.',
                action: can('case.write') ? <Link className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/evidence/new`}>New acquisition</Link> : undefined,
              }}
            />
          )}
        </Loadable>
      </Card>
    </div>
  )
}

const STEPS = ['Source path', 'Write-blocker attestation', 'Label', 'Review', 'Acquire'] as const

function Wizard() {
  const caseId = Number(useParams().caseId)
  const nav = useNavigate()
  const toast = useToast()
  const caps = useAsync((s) => evidenceApi.capabilities(s), [])
  const [step, setStep] = useState(0)
  const [f, setF] = useState({ kind: 'image', source_path: '', write_blocker: '', label: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const native = f.kind === 'native'
  const canNext = [f.source_path.trim().length > 0, f.write_blocker !== '', f.label.trim().length > 0, true][step]
  const go = async () => {
    setBusy(true)
    setErr('')
    try {
      const body = { source_path: f.source_path.trim(), label: f.label.trim(), write_blocker: f.write_blocker }
      const s = native ? (await evidenceApi.nativeExport(caseId, body)).acquisition : await evidenceApi.acquire(caseId, body)
      refreshStatusBanners()
      if (s.evidence_id) {
        toast.ok('Acquisition complete')
        nav(`/cases/${caseId}/evidence/${s.evidence_id}`)
      } else {
        toast.info(`Acquisition ${s.id} is ${s.status}; resume it from the evidence list`)
        nav(`/cases/${caseId}/evidence`)
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-4">
      <PageHeader title="New acquisition" subtitle="Five steps. The source is opened read-only and copied into the case workspace." />
      <Can perm="case.write" fallback={<p role="note" className="text-sm text-amber-300">{READONLY_HINT}</p>}>
        <ol className="flex flex-wrap gap-2 text-xs" aria-label="Steps">
          {STEPS.map((s, i) => (
            <li key={s} aria-current={i === step ? 'step' : undefined} className={`rounded-full px-3 py-1 ${i === step ? 'bg-accent text-navy-900' : i < step ? 'bg-navy-600' : 'bg-navy-800 text-slate-300'}`}>
              {i + 1}. {s}
            </li>
          ))}
        </ol>
        <Card>
          <div className="space-y-3" data-testid={`wizard-step-${step}`}>
            {step === 0 && (
              <>
                <fieldset className="space-y-1 text-sm">
                  <legend className="mb-1 text-slate-300">Source kind</legend>
                  <label className="flex items-center gap-2"><input type="radio" name="kind" checked={f.kind === 'image'} onChange={() => setF({ ...f, kind: 'image' })} /> Disk image or file (resumable copy, bad-sector map)</label>
                  <label className="flex items-center gap-2">
                    <input type="radio" name="kind" checked={f.kind === 'native'} disabled={caps.data?.native_export_ingest.available === false} onChange={() => setF({ ...f, kind: 'native' })} />
                    Standard export file (hashed, then described by ffprobe; no vendor claim)
                  </label>
                  <label className="flex items-center gap-2 text-slate-400"><input type="radio" name="kind" disabled /> E01 / EWF image</label>
                </fieldset>
                {caps.data && !caps.data.ewf.available && <Unavailable what="E01/EWF ingest" reason={caps.data.ewf.reason} />}
                {caps.data?.native_export_ingest.available === false && <Unavailable what="Native-export ingest" reason={caps.data.native_export_ingest.reason ?? 'ffprobe is not installed on the server.'} />}
                {caps.data && !caps.data.block_device.available && (
                  <p className="text-xs text-slate-400">Block devices are not available (opt-in {caps.data.block_device.opt_in}; never verified on real disks).</p>
                )}
                <SourcePicker caseId={caseId} value={f.source_path} onChange={(p) => setF((cur) => ({ ...cur, source_path: p }))} />
              </>
            )}
            {step === 1 && (
              <fieldset className="space-y-1 text-sm">
                <legend className="mb-1 text-slate-300">Was a write blocker used? This is your attestation; the tool cannot verify it.</legend>
                {(['yes', 'no', 'unknown'] as const).map((v) => (
                  <label key={v} className="flex items-center gap-2">
                    <input type="radio" name="wb" checked={f.write_blocker === v} onChange={() => setF({ ...f, write_blocker: v })} /> {v}
                  </label>
                ))}
              </fieldset>
            )}
            {step === 2 && (
              <Field label="Evidence label">
                <input className={inputClass} value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} />
              </Field>
            )}
            {step >= 3 && (
              <KV
                items={[
                  ['Kind', native ? 'Standard export file' : 'Disk image or file'],
                  ['Source path', f.source_path],
                  ['Write blocker (attested)', f.write_blocker],
                  ['Label', f.label],
                ]}
              />
            )}
            {step === 4 && <p className="text-sm text-slate-300">Press Acquire to copy and hash the source (MD5 and SHA-256). This is recorded in the custody log.</p>}
            {err && <p role="alert" className="text-sm text-red-300">{err}</p>}
          </div>
          <div className="mt-4 flex gap-2">
            <Button disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>Back</Button>
            {step < 4 ? (
              <Button variant="primary" disabled={!canNext} onClick={() => setStep(step + 1)}>Next</Button>
            ) : (
              <Button variant="primary" busy={busy} onClick={go}>Acquire</Button>
            )}
          </div>
        </Card>
      </Can>
    </div>
  )
}

/** Accessible bad-sector map: an SVG strip over the whole source plus the table of the same ranges. */
function BadSectorMap({ b, size }: { b: BadSectors; size: number }) {
  const label = b.range_count === 0 ? 'Bad-sector map: no unreadable ranges recorded' : `Bad-sector map: ${b.range_count} unreadable range(s), ${fmtBytes(b.bytes)} zero-filled`
  return (
    <div className="space-y-2">
      <svg role="img" aria-label={label} viewBox="0 0 1000 24" className="h-6 w-full rounded bg-emerald-900">
        {b.ranges.map((r, i) => (
          <rect key={i} x={(r.start / Math.max(size, 1)) * 1000} width={Math.max(2, ((r.end - r.start) / Math.max(size, 1)) * 1000)} y={0} height={24} className="fill-red-500" />
        ))}
      </svg>
      <p className="text-xs text-slate-300">Green = read; red = unreadable and zero-filled in the copy. {b.method}. {b.hash_scope ?? b.note}</p>
      <DataTable
        rows={b.ranges}
        caption="Bad-sector ranges (table alternative to the map)"
        rowKey={(r) => r.start}
        columns={[
          { key: 's', header: 'Start', sort: (r) => r.start, render: (r) => `0x${r.start.toString(16)}` },
          { key: 'e', header: 'End', sort: (r) => r.end, render: (r) => `0x${r.end.toString(16)}` },
          { key: 'b', header: 'Bytes', sort: (r) => r.bytes, render: (r) => r.bytes.toLocaleString() },
          { key: 'x', header: 'Error', render: (r) => r.error },
        ]}
        empty={{ title: 'No unreadable ranges recorded', hint: 'The copy has no zero-filled ranges.' }}
      />
    </div>
  )
}

function SourceTab({ ev }: { ev: Evidence }) {
  const bad = useAsync((s) => evidenceApi.badSectors(ev.id, s), [ev.id])
  const nx = useAsync((s) => evidenceApi.nativeInfo(ev.id, s), [ev.id])
  return (
    <div className="space-y-4">
      <Card title="Source and attestation">
        <KV
          items={[
            ['Label', ev.label],
            ['Source path', <code key="p" className="text-xs">{ev.source_path}</code>],
            ['Source type', ev.source_type],
            ['Write blocker (examiner attestation, not verified by the tool)', ev.write_blocker],
            ['Status', ev.status],
            ['Size', `${fmtBytes(ev.size_bytes)} (${ev.size_bytes.toLocaleString()} bytes)`],
            ['Acquired', `${fmtTime(ev.acquired_at)} by ${ev.examiner}`],
            ['Data origin', ev.synthetic ? <Chip key="o" tone="warn">Reference test data</Chip> : 'Examiner-supplied source'],
          ]}
        />
      </Card>
      <Card title="Bad-sector map">
        <Loadable state={bad} rows={2}>{(b) => (b.available ? <BadSectorMap b={b} size={ev.size_bytes} /> : <Unavailable reason={b.note} />)}</Loadable>
      </Card>
      <Card title="Native export">
        <Loadable state={nx} rows={2}>
          {(n) =>
            !n.available ? (
              <p className="text-sm text-slate-300">{n.reason}</p>
            ) : (
              <div className="space-y-2 text-sm">
                <KV
                  items={[
                    ['Probe status', n.probe_status ?? ''],
                    ['Container', `${n.container?.format_name} (${n.container?.format_long_name})`],
                    ['Duration', n.container?.duration_s != null ? `${n.container.duration_s} s` : 'unknown'],
                    ['Streams', String(n.container?.nb_streams)],
                    ['Probe score', String(n.container?.probe_score)],
                    ['ffprobe', n.ffprobe_version ?? ''],
                  ]}
                />
                {n.probe_error && <p className="text-amber-300">{n.probe_error}</p>}
                <p className="text-xs text-slate-400">{n.tags_note} {n.note}</p>
              </div>
            )
          }
        </Loadable>
      </Card>
    </div>
  )
}

function HashTab({ ev, reload }: { ev: Evidence; reload: () => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const verify = async () => {
    setBusy(true)
    try {
      const r = await evidenceApi.verify(ev.id)
      if (r.ok) toast.ok('Hashes match the acquisition-time values')
      else toast.error(new Error(r.error || 'Integrity failure: hashes do not match'))
      refreshStatusBanners()
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
      reload()
    }
  }
  const { can } = useAuth()
  return (
    <Card title="Hash and verify">
      <KV
        items={[
          ['MD5', <HashText key="m" value={ev.md5} label="MD5" head={32} />],
          ['SHA-256', <HashText key="s" value={ev.sha256} label="SHA-256" head={64} />],
          ['Last verified', ev.last_verified_at ? fmtTime(ev.last_verified_at) : 'never'],
          ['Result', verifyChip(ev)],
        ]}
      />
      <div className="mt-3">
        <Button variant="primary" busy={busy} disabled={!can('case.write')} title={can('case.write') ? undefined : READONLY_HINT} onClick={verify}>
          Verify hashes
        </Button>
      </div>
    </Card>
  )
}

function CustodyTab({ ev }: { ev: Evidence }) {
  const state = useAsync(async (s) => (await casesApi.custody(ev.case_id, s)).filter((c) => c.evidence_id === ev.id), [ev.id])
  return (
    <Card title="Custody entries for this evidence item">
      <Loadable state={state}>
        {(rows) => (
          <DataTable
            rows={rows}
            caption="Custody entries for this evidence item"
            rowKey={(r) => r.seq}
            columns={[
              { key: 'seq', header: 'Seq', sort: (r) => r.seq, render: (r) => r.seq },
              { key: 't', header: 'Time (UTC)', sort: (r) => r.timestamp_utc, render: (r) => fmtTime(r.timestamp_utc) },
              { key: 'a', header: 'Action', sort: (r) => r.action, render: (r) => r.action },
              { key: 'x', header: 'Examiner', sort: (r) => r.examiner, render: (r) => r.examiner },
              { key: 'h', header: 'Entry hash', render: (r) => <HashText value={r.entry_hash} label={`entry hash ${r.seq}`} /> },
            ]}
            empty={{ title: 'No custody entries for this item' }}
          />
        )}
      </Loadable>
    </Card>
  )
}

function EvidenceDetail() {
  const { caseId, evidenceId } = useParams()
  const state = useAsync(async (s) => {
    const ev = (await evidenceApi.list(Number(caseId), s)).find((e) => e.id === Number(evidenceId))
    if (!ev) throw new Error(`Evidence ${evidenceId} was not found in this case`)
    return ev
  }, [caseId, evidenceId])
  return (
    <Loadable state={state}>
      {(ev) => (
        <div>
          <PageHeader
            title={`Evidence #${ev.id}: ${ev.label}`}
            subtitle={<Link className="text-accent hover:underline" to={`/cases/${caseId}/evidence`}>All evidence</Link>}
            actions={<>
              <Link className="rounded-md bg-navy-700 px-3 py-1.5 text-sm" to={`/cases/${caseId}/identification?evidence=${ev.id}`}>Identify</Link>
              <Link className="rounded-md bg-navy-700 px-3 py-1.5 text-sm" to={`/cases/${caseId}/recovery?evidence=${ev.id}`}>Recover</Link>
            </>}
          />
          <Tabs
            label="Evidence sections"
            tabs={[
              { id: 'source', label: 'Source and attestation', render: () => <SourceTab ev={ev} /> },
              { id: 'hash', label: 'Hash and verify', render: () => <HashTab ev={ev} reload={state.reload} /> },
              { id: 'custody', label: 'Custody entries', render: () => <CustodyTab ev={ev} /> },
            ]}
          />
        </div>
      )}
    </Loadable>
  )
}

export default function EvidenceModule() {
  return (
    <Routes>
      <Route index element={<EvidenceList />} />
      <Route path="new" element={<Wizard />} />
      <Route path=":evidenceId" element={<EvidenceDetail />} />
    </Routes>
  )
}
