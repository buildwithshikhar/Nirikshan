import { useEffect, useState } from 'react'
import { api } from './api'

export type BackendStatus = 'checking' | 'online' | 'waking' | 'offline'

const RETRY_MS = 3000
const MAX_ATTEMPTS = 20 // ~1 minute, enough for a cold-starting host

/** Polls /health; retries while the backend may be cold-starting. */
export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>('checking')

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    const attempt = (n: number) => {
      api
        .health()
        .then(() => !cancelled && setStatus('online'))
        .catch(() => {
          if (cancelled) return
          if (n >= MAX_ATTEMPTS) return setStatus('offline')
          setStatus('waking')
          timer = setTimeout(() => attempt(n + 1), RETRY_MS)
        })
    }
    attempt(1)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  return status
}
