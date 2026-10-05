import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Case, type ChainResult, type Evidence, api } from '../api'
import HeadHash from '../components/HeadHash'

const WB = ['unknown', 'yes', 'no'] as const

function verifyLabel(ev: Evidence) {
  if (ev.last_verify_ok === 1) return <span className="text-emerald-400">verified {ev.last_verified_at.slice(0, 19)}Z</span>
  if (ev.last_verify_ok === 0) return <span className="text-red-400">INTEGRITY FAILURE</span>
  return <span className="text-slate-400">never verified</span>
}

export default function CaseDetail() {
  const id = Number(useParams().id)
  const [kase, setKase] = useState<Case | null>(null)
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [form, setForm] = useState({ source_path: '', label: '', write_blocker: 'unknown' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [chain, setChain] = useState<ChainResult | null>(null)

  const load = useCallback(() => {
    api.getCase(id).then(setKase).catch((e) => setError(e.message))
    api.listEvidence(id).then(setEvidence).catch((e) => setError(e.message))
    api.verifyChain(id).then(setChain).catch(() => setChain(null))
  }, [id])
  useEffect(load, [load])

  const acquire = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await api.acquire(id, form)
      setForm({ ...form, source_path: '', label: '' })
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const verify = async (evId: number) => {
    setError('')
    try {
      await api.verifyEvidence(evId)
    } catch (err) {
      setError((err as Error).message)
    }
    load()
  }

  const input = 'w-full rounded-md bg-navy-900 px-3 py-2 text-sm outline-none ring-1 ring-navy-700 focus:ring-accent'

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">{kase ? `${kase.case_number}: ${kase.title}` : 'Case'}</h1>
        <Link className="text-sm text-accent hover:underline" to={`/cases/${id}/custody`}>Custody log →</Link>
      </div>
      <form onSubmit={acquire} className="grid gap-3 rounded-lg bg-navy-800 p-5 md:grid-cols-4">
        <input className={`${input} md:col-span-2`} placeholder="Source image path (server-side)" required
          value={form.source_path} onChange={(e) => setForm({ ...form, source_path: e.target.value })} />
        <input className={input} placeholder="Label" required value={form.label}
          onChange={(e) => setForm({ ...form, label: e.target.value })} />
        <select aria-label="Write blocker used" className={input} value={form.write_blocker}
          onChange={(e) => setForm({ ...form, write_blocker: e.target.value })}>
          {WB.map((w) => <option key={w} value={w}>Write blocker: {w}</option>)}
        </select>
        <button disabled={busy} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 md:col-span-4 md:w-48">
          {busy ? 'Acquiring…' : 'Acquire (read-only)'}
        </button>
        <p className="text-xs text-slate-500 md:col-span-4">
          The source is opened read-only and copied into the case workspace; MD5 and SHA-256 are computed in one pass.
          The write-blocker choice is an examiner attestation and is not verified by the tool.
        </p>
      </form>
      <HeadHash chain={chain} />
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      <section className="rounded-lg bg-navy-800 p-5">
        <h2 className="mb-2 font-medium">Evidence</h2>
        {evidence.length === 0 ? (
          <p className="text-sm text-slate-400">No evidence acquired yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-slate-400">
              <tr><th className="py-1">#</th><th>Label</th><th>Size</th><th>Hashes</th><th>WB</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {evidence.map((ev) => (
                <tr key={ev.id} className="border-t border-navy-700 align-top">
                  <td className="py-2">{ev.id}</td>
                  <td>{ev.label}<div className="text-xs text-slate-500">{ev.source_type}</div></td>
                  <td>{ev.size_bytes.toLocaleString()} B</td>
                  <td className="font-mono text-[11px] break-all">
                    <div>MD5 {ev.md5}</div><div>SHA-256 {ev.sha256}</div>
                  </td>
                  <td>{ev.write_blocker}</td>
                  <td>{ev.status}<div className="text-xs">{verifyLabel(ev)}</div></td>
                  <td>
                    <button className="rounded bg-navy-700 px-3 py-1 text-xs hover:bg-navy-900" onClick={() => verify(ev.id)}>
                      Verify
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
