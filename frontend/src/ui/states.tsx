import type { ReactNode } from 'react'
import { ApiError } from '../lib/http'

export function Skeleton({ rows = 3, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2" data-testid="skeleton">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} aria-hidden="true" className="h-5 animate-pulse rounded bg-navy-700" />
      ))}
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div data-testid="empty-state" className="rounded-lg border border-dashed border-navy-600 p-6 text-center">
      <p className="font-medium">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-400">{hint}</p>}
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : null
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div role="alert" data-testid="error-state" className="rounded-lg border border-red-400 bg-red-950 p-4 text-sm text-red-100">
      <p className="font-semibold">{status === 403 ? 'Your role cannot do this' : status === 404 ? 'Not found' : 'Something went wrong'}</p>
      <p className="mt-1 break-words">{msg}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-3 rounded bg-navy-700 px-3 py-1 text-slate-100 hover:bg-navy-600">
          Try again
        </button>
      )}
    </div>
  )
}

/** The unavailable/deferred state the API reports as {available:false, reason}. Shown, never faked. */
export function Unavailable({ reason, what }: { reason?: string; what?: string }) {
  return (
    <div data-testid="unavailable" role="note" className="rounded-lg border border-amber-400 bg-navy-800 p-4 text-sm">
      <p className="font-semibold text-amber-300">{what ? `${what}: not available` : 'Not available'}</p>
      <p className="mt-1 text-slate-300">{reason ?? 'The server reports this capability as not available.'}</p>
    </div>
  )
}

/** Loading / error / ready switch used by most screens. */
export function Loadable<T>({
  state,
  children,
  rows,
}: {
  state: { data: T | null; error: Error | null; loading: boolean; reload: () => void }
  children: (d: T) => ReactNode
  rows?: number
}) {
  if (state.error && state.data == null) return <ErrorState error={state.error} onRetry={state.reload} />
  if (state.data == null) return <Skeleton rows={rows} />
  return <>{children(state.data)}</>
}
