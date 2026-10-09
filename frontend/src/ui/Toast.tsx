import { type ReactNode, createContext, useCallback, useContext, useState } from 'react'

type Kind = 'ok' | 'error' | 'info'
interface T { id: number; kind: Kind; text: string }
const Ctx = createContext<(kind: Kind, text: string) => void>(() => undefined)

/** Toasts for action results. Errors stay until dismissed; others fade after 5 s. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<T[]>([])
  const dismiss = (id: number) => setItems((l) => l.filter((t) => t.id !== id))
  const push = useCallback((kind: Kind, text: string) => {
    const id = Date.now() + Math.random()
    setItems((l) => [...l.slice(-4), { id, kind, text }])
    if (kind !== 'error') setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), 5000)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div aria-live="polite" role="region" aria-label="Notifications" className="fixed bottom-4 right-4 z-[60] flex w-96 max-w-[90vw] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            data-testid={`toast-${t.kind}`}
            className={`flex items-start justify-between gap-3 rounded-md p-3 text-sm shadow-lg ${
              t.kind === 'error' ? 'bg-red-900 text-red-100' : t.kind === 'ok' ? 'bg-emerald-900 text-emerald-100' : 'bg-navy-700 text-slate-100'
            }`}
          >
            <span className="break-words">{t.text}</span>
            <button aria-label="Dismiss notification" onClick={() => dismiss(t.id)} className="rounded px-1 hover:bg-black/30">
              ×
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast() {
  const push = useContext(Ctx)
  return {
    ok: (t: string) => push('ok', t),
    error: (e: unknown) => push('error', e instanceof Error ? e.message : String(e)),
    info: (t: string) => push('info', t),
  }
}
