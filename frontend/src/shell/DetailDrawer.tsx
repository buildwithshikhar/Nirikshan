import { type ReactNode, createContext, useContext, useMemo, useState } from 'react'
import { Drawer } from '../ui'

interface Ctx {
  show: (title: string, body: ReactNode) => void
  hide: () => void
}
const DrawerCtx = createContext<Ctx>({ show: () => undefined, hide: () => undefined })

/** The on-demand right drawer for evidence and clip details (hashes, tier, confidence, parsed /
 * inferred / unknown chips). Any screen calls `useDetailDrawer().show(title, node)`. */
export function DetailDrawerProvider({ children }: { children: ReactNode }) {
  const [d, setD] = useState<{ title: string; body: ReactNode } | null>(null)
  const value = useMemo(() => ({ show: (title: string, body: ReactNode) => setD({ title, body }), hide: () => setD(null) }), [])
  return (
    <DrawerCtx.Provider value={value}>
      {children}
      <Drawer open={!!d} title={d?.title ?? ''} onClose={() => setD(null)} testId="detail-drawer">
        {d?.body}
      </Drawer>
    </DrawerCtx.Provider>
  )
}
export const useDetailDrawer = () => useContext(DrawerCtx)
