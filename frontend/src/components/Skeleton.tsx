/** Loading placeholder. Hidden from assistive tech; the region announces "Loading" instead. */
export default function Skeleton({ rows = 3, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2" data-testid="skeleton">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} aria-hidden="true" className="h-5 animate-pulse rounded bg-navy-700" />
      ))}
    </div>
  )
}
