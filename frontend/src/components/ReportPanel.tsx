import { useCallback, useEffect, useState } from 'react'
import { reportApi, type ReportRow } from '../api_report'

export interface ReportPanelProps {
  caseId: number
  /** Evidence items of the case; one draft-certificate button is shown per item. */
  evidence: { id: number; label: string }[]
}

export default function ReportPanel({ caseId, evidence }: ReportPanelProps) {
  const [rows, setRows] = useState<ReportRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    reportApi.list(caseId).then(setRows).catch((e) => setError(e.message))
  }, [caseId])
  useEffect(load, [load])

  const generate = async () => {
    setError('')
    setBusy(true)
    try {
      await reportApi.generate(caseId)
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-lg bg-navy-800 p-5" data-testid="report-panel">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-medium">Reports and exports</h2>
        <button
          onClick={generate}
          disabled={busy}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-navy-900 hover:bg-accent-hover disabled:opacity-50"
        >
          {busy ? 'Generating…' : 'Generate report'}
        </button>
      </div>
      <p className="mb-3 text-xs text-slate-400">
        Generating a report re-verifies the custody chain, stores a read-only PDF and writes a
        report_generated custody entry with the PDF SHA-256. Validation behind it is on synthetic
        images only.
      </p>
      {error && <p role="alert" className="mb-2 text-sm text-red-400">{error}</p>}
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400">No report generated yet.</p>
      ) : (
        <table className="w-full text-left text-sm" data-testid="report-table">
          <thead className="text-slate-400">
            <tr><th className="py-1">#</th><th>Generated (UTC)</th><th>Chain</th><th>PDF SHA-256</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-navy-700 align-top">
                <td className="py-2">{r.id}</td>
                <td>{r.generated_at.slice(0, 19)}Z<div className="text-xs text-slate-400">{r.examiner}, {r.pages} pages</div></td>
                <td className={r.chain_ok ? 'text-emerald-400' : 'text-red-400'}>{r.chain_ok ? 'VALID' : 'FAILED'}</td>
                <td className="font-mono text-[11px] break-all">{r.sha256}</td>
                <td>
                  <a className="rounded bg-navy-700 px-3 py-1 text-xs hover:bg-navy-900" href={reportApi.downloadUrl(r.id)} download>
                    Download PDF
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="mt-4 space-y-2 border-t border-navy-700 pt-3">
        <h3 className="text-sm font-medium">Draft Section 63(4) certificate</h3>
        <p className="text-xs text-amber-400" data-testid="draft-note">
          DRAFT for examiner and legal review, not legal advice. Nirikshan does not assert that
          this satisfies Section 63(4).
        </p>
        {evidence.length === 0 ? (
          <p className="text-sm text-slate-400">Acquire evidence first.</p>
        ) : (
          <ul className="space-y-1">
            {evidence.map((ev) => (
              <li key={ev.id} className="flex items-center gap-3 text-sm">
                <span>#{ev.id} {ev.label}</span>
                <a className="rounded bg-navy-700 px-3 py-1 text-xs hover:bg-navy-900"
                  href={reportApi.certificateUrl(caseId, ev.id)} download>
                  Draft §63(4) certificate
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-4 border-t border-navy-700 pt-3 text-sm">
        <a className="text-accent hover:underline" href={reportApi.jsonldUrl(caseId)} download>
          Export case JSON-LD
        </a>
        <span className="ml-2 text-xs text-slate-400">
          plain JSON-LD, NOT CASE-conformant (only hash terms are borrowed from UCO)
        </span>
      </div>
    </section>
  )
}
