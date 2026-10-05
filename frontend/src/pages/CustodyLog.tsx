import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type ChainResult, type CustodyEntry, api } from '../api'
import HeadHash from '../components/HeadHash'

export default function CustodyLog() {
  const id = Number(useParams().id)
  const [entries, setEntries] = useState<CustodyEntry[]>([])
  const [chain, setChain] = useState<ChainResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.custody(id).then(setEntries).catch((e) => setError(e.message))
    api.verifyChain(id).then(setChain).catch((e) => setError(e.message))
  }, [id])

  const check = () =>
    api.verifyChain(id).then(setChain).catch((e) => setError(e.message))

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Custody log</h1>
        <Link className="text-sm text-accent hover:underline" to={`/cases/${id}`}>← Case</Link>
      </div>
      <div className="flex items-center gap-4 rounded-lg bg-navy-800 p-5">
        <button className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover" onClick={check}>
          Verify chain and signatures
        </button>
        {chain && (
          <div data-testid="chain-result" className="text-sm">
            <span className={chain.ok ? 'text-emerald-400' : 'text-red-400'}>
              {chain.ok ? 'CHAIN VALID' : 'CHAIN INVALID'}
            </span>{' '}
            ({chain.entries} entries, key {chain.key_id})
            {chain.failures.map((f, i) => (
              <div key={i} className="text-red-400">entry {f.seq}: {f.reason}</div>
            ))}
          </div>
        )}
      </div>
      <HeadHash chain={chain} />
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      <section className="overflow-x-auto rounded-lg bg-navy-800 p-5">
        <table className="w-full text-left text-sm">
          <thead className="text-slate-400">
            <tr><th className="py-1">#</th><th>Time (UTC)</th><th>Action</th><th>Examiner</th><th>NTP</th><th>Tool</th><th>Details</th></tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.seq} className="border-t border-navy-700 align-top">
                <td className="py-2">{e.seq}</td>
                <td className="font-mono text-xs">{e.timestamp_utc.slice(0, 26)}</td>
                <td>{e.action}</td><td>{e.examiner}</td><td>{e.ntp_status}</td><td>{e.tool_version}</td>
                <td className="font-mono text-[11px] break-all">{e.details_json}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
