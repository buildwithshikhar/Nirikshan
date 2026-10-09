import { type DependencyList, useCallback, useEffect, useRef, useState } from 'react'

export interface Async<T> {
  data: T | null
  error: Error | null
  loading: boolean
  reload: () => void
  setData: (d: T | null) => void
}

/** Runs `fn` on mount and whenever `deps` change; `reload()` runs it again. The last result stays
 * visible while a reload is in flight; stale responses are ignored. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: DependencyList): Async<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    fnRef
      .current(ctl.signal)
      .then((d) => {
        if (ctl.signal.aborted) return
        setData(d)
        setError(null)
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return
        setError(e instanceof Error ? e : new Error(String(e)))
      })
      .finally(() => !ctl.signal.aborted && setLoading(false))
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload, setData }
}
