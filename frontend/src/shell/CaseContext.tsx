import { type ReactNode, createContext, useContext, useEffect, useMemo, useState } from 'react'
import { matchPath, useLocation } from 'react-router-dom'
import { type Case, api } from '../api'
import { useAuth } from '../auth/AuthContext'

const KEY = 'nirikshan.case'
const stored = (): number | null => {
  try {
    return Number(localStorage.getItem(KEY)) || null
  } catch {
    return null
  }
}

interface CaseCtx {
  caseId: number | null
  kase: Case | null
  cases: Case[]
  reload: () => void
}
const Ctx = createContext<CaseCtx>({ caseId: null, kase: null, cases: [], reload: () => undefined })

/** The case the user is working in: taken from the URL (/cases/:id/...), else the last one used. */
export function CaseProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const { pathname } = useLocation()
  const fromUrl = Number(matchPath('/cases/:id/*', pathname)?.params.id ?? matchPath('/cases/:id', pathname)?.params.id) || null
  const [last, setLast] = useState<number | null>(stored)
  const [cases, setCases] = useState<Case[]>([])
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (fromUrl) {
      setLast(fromUrl)
      try {
        localStorage.setItem(KEY, String(fromUrl))
      } catch {
        // remembering the case is a convenience only
      }
    }
  }, [fromUrl])

  useEffect(() => {
    if (status !== 'ready') return
    api.listCases().then(setCases).catch(() => setCases([]))
  }, [status, tick, pathname === '/cases'])

  const caseId = fromUrl ?? (last && cases.some((c) => c.id === last) ? last : null)
  const value = useMemo(
    () => ({ caseId, kase: cases.find((c) => c.id === caseId) ?? null, cases, reload: () => setTick((t) => t + 1) }),
    [caseId, cases],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useCase = () => useContext(Ctx)
