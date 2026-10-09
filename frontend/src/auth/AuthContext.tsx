import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Skeleton } from '../ui/states'
import { UNAUTHORIZED_EVENT, getToken, setToken } from '../lib/http'
import { type Me, authApi } from './api'
import { type Permission, roleCan } from './permissions'

interface AuthState {
  user: Me | null
  status: 'loading' | 'anon' | 'ready'
  notice: string
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  can: (p: Permission) => boolean
}
const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [status, setStatus] = useState<AuthState['status']>(getToken() ? 'loading' : 'anon')
  const [notice, setNotice] = useState('')

  const end = useCallback((msg: string) => {
    setToken(null)
    setUser(null)
    setStatus('anon')
    setNotice(msg)
  }, [])

  useEffect(() => {
    if (!getToken()) return
    authApi
      .me()
      .then((u) => {
        setUser(u)
        setStatus('ready')
      })
      .catch(() => end(''))
  }, [end])

  useEffect(() => {
    const h = () => end('Your session ended (expired, signed out elsewhere, or the account changed). Sign in again.')
    window.addEventListener(UNAUTHORIZED_EVENT, h)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, h)
  }, [end])

  const value = useMemo<AuthState>(
    () => ({
      user,
      status,
      notice,
      login: async (username, password) => {
        const res = await authApi.login(username.trim(), password)
        setToken(res.token)
        setUser(await authApi.me())
        setNotice('')
        setStatus('ready')
      },
      logout: async () => {
        try {
          await authApi.logout()
        } catch {
          // the session may already be gone: still sign out locally
        }
        end('You have signed out.')
      },
      can: (p) => roleCan(user?.role, p),
    }),
    [user, status, notice, end],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}

/** Route guard: anonymous visitors go to /login and come back to where they were headed. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const loc = useLocation()
  if (status === 'loading') return <div className="p-8"><Skeleton label="Checking your session" /></div>
  if (status === 'anon') return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  return <>{children}</>
}

/** Route guard for screens a role cannot use: explains instead of showing a broken page. */
export function RequirePermission({ perm, children }: { perm: Permission; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(perm)) {
    return (
      <div role="alert" data-testid="forbidden" className="rounded-lg border border-amber-400 bg-navy-800 p-6">
        <h1 className="text-xl font-semibold">Your role cannot open this screen</h1>
        <p className="mt-2 text-sm text-slate-300">Ask an administrator if you need access. The server enforces this independently of the interface.</p>
      </div>
    )
  }
  return <>{children}</>
}
