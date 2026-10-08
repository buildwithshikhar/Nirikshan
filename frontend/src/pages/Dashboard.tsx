import { useEffect, useState } from 'react'
import { type SystemInfo, api } from '../api'

// Placeholder shell: values stay empty until the evidence core exists (Phase 1+).
const CARDS = [
  { label: 'Cases', hint: 'Open the Cases page' },
  { label: 'Evidence Items Hashed', hint: 'See the case evidence list' },
  { label: 'Recovered Clips', hint: 'Available after carving (Phase 2)' },
]

export default function Dashboard() {
  const [sys, setSys] = useState<SystemInfo | null>(null)
  useEffect(() => {
    api.system().then(setSys).catch(() => setSys(null))
  }, [])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {CARDS.map((c) => (
          <div key={c.label} className="rounded-lg bg-navy-800 p-5">
            <div className="text-sm text-slate-400">{c.label}</div>
            <div className="mt-2 text-3xl font-bold text-accent">—</div>
            <div className="mt-2 text-xs text-slate-400">{c.hint}</div>
          </div>
        ))}
      </div>
      <section className="rounded-lg bg-navy-800 p-5 text-sm">
        <h2 className="font-medium">System</h2>
        {sys ? (
          <ul className="mt-2 space-y-1 text-slate-300">
            <li>Tool version {sys.tool_version}</li>
            <li data-testid="ffmpeg-status">
              ffmpeg: {sys.ffmpeg.available ? sys.ffmpeg.version : 'not installed (degraded mode)'}
            </li>
            <li>Clock NTP sync: {sys.ntp_status}</li>
            <li className="font-mono text-xs">Custody signing key id {sys.signing_key_id}</li>
          </ul>
        ) : (
          <p className="mt-2 text-slate-400">API unavailable.</p>
        )}
      </section>
    </div>
  )
}
