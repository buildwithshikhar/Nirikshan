/** The one HTTP layer: bearer token from the session, JSON in/out, typed errors, 401 handling.
 * Every API module (legacy api*.ts and modules/<name>/api.ts) goes through `authFetch` or `http`. */
export const API_URL = import.meta.env.VITE_API_URL ?? ''

const TOKEN_KEY = 'nirikshan.token'
export const UNAUTHORIZED_EVENT = 'nirikshan:unauthorized'

export const getToken = (): string | null => {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
export const setToken = (t: string | null) => {
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable: the session lives only in memory of this page
  }
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

/** fetch with the Authorization header. A 401 on any call except login ends the session. */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(input, { ...init, headers })
  if (res.status === 401 && !input.includes('/api/auth/login')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  return res
}

export interface HttpOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown // JSON-encoded unless FormData/Blob
  signal?: AbortSignal
}

export async function http<T>(path: string, opts: HttpOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (opts.body instanceof FormData || opts.body instanceof Blob) body = opts.body
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const res = await authFetch(`${API_URL}${path}`, { method: opts.method ?? 'GET', headers, body, signal: opts.signal })
  if (!res.ok) {
    const text = await res.text()
    let detail: unknown = text
    try {
      detail = (JSON.parse(text) as { detail?: unknown }).detail ?? text
    } catch {
      // not JSON: keep the raw text
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('json') ? res.json() : res.text()) as Promise<T>
}

export const get = <T>(path: string, signal?: AbortSignal) => http<T>(path, { signal })
export const post = <T>(path: string, body?: unknown) => http<T>(path, { method: 'POST', body })
export const put = <T>(path: string, body?: unknown) => http<T>(path, { method: 'PUT', body })
export const patch = <T>(path: string, body?: unknown) => http<T>(path, { method: 'PATCH', body })
export const del = <T>(path: string) => http<T>(path, { method: 'DELETE' })

/** Fetch a protected file (PDF, ZIP, CSV) with the token and hand it to the browser as a download. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await authFetch(`${API_URL}${path}`)
  if (!res.ok) throw new ApiError(res.status, (await res.text()) || res.statusText)
  const cd = res.headers.get('content-disposition') ?? ''
  const name = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const errorText = (e: unknown): string => (e instanceof Error ? e.message : String(e))
