// Placeholder shell: values stay empty until the evidence core exists (Phase 1+).
const CARDS = [
  { label: 'Cases', hint: 'Available after the evidence core (Phase 1)' },
  { label: 'Evidence Items Hashed', hint: 'Available after acquisition (Phase 1)' },
  { label: 'Recovered Clips', hint: 'Available after carving (Phase 2)' },
]

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {CARDS.map((c) => (
          <div key={c.label} className="rounded-lg bg-navy-800 p-5">
            <div className="text-sm text-slate-400">{c.label}</div>
            <div className="mt-2 text-3xl font-bold text-accent">—</div>
            <div className="mt-2 text-xs text-slate-500">{c.hint}</div>
          </div>
        ))}
      </div>
      <section className="rounded-lg bg-navy-800 p-5">
        <h2 className="font-medium">Recent Cases</h2>
        <p className="mt-2 text-sm text-slate-400">No cases yet. Case management arrives in Phase 1.</p>
      </section>
    </div>
  )
}
