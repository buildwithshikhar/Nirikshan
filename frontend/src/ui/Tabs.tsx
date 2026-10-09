import { type KeyboardEvent, type ReactNode, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

export interface TabDef {
  id: string
  label: string
  render: () => ReactNode
}

/** WAI-ARIA tabs (arrow keys, Home/End), the active tab kept in `?tab=` so links and reloads land
 * on it. Only the active panel is rendered, so inactive tabs load nothing. */
export function Tabs({ tabs, label, param = 'tab' }: { tabs: TabDef[]; label: string; param?: string }) {
  const [sp, setSp] = useSearchParams()
  const active = tabs.find((t) => t.id === sp.get(param)) ?? tabs[0]
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const select = (id: string) => {
    const next = new URLSearchParams(sp)
    next.set(param, id)
    setSp(next, { replace: true })
    refs.current[id]?.focus()
  }
  const onKey = (e: KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === active.id)
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key]
    if (to === undefined) return
    e.preventDefault()
    select(tabs[(to + tabs.length) % tabs.length].id)
  }
  return (
    <div>
      <div role="tablist" aria-label={label} onKeyDown={onKey} className="mb-4 flex flex-wrap gap-1 border-b border-navy-700">
        {tabs.map((t) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el
            }}
            role="tab"
            id={`tab-${param}-${t.id}`}
            aria-selected={t.id === active.id}
            aria-controls={`panel-${param}-${t.id}`}
            tabIndex={t.id === active.id ? 0 : -1}
            onClick={() => select(t.id)}
            className={`-mb-px rounded-t-md border-b-2 px-4 py-2 text-sm font-medium ${
              t.id === active.id ? 'border-accent text-accent' : 'border-transparent text-slate-300 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${param}-${active.id}`} aria-labelledby={`tab-${param}-${active.id}`} tabIndex={0}>
        {active.render()}
      </div>
    </div>
  )
}
