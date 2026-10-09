import { type ButtonHTMLAttributes, type ReactNode, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import type { Permission } from '../auth/permissions'

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Card({ title, children, actions, className = '' }: { title?: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg bg-navy-800 p-4 ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="font-medium">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  )
}

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent text-navy-900 hover:bg-accent-hover font-semibold',
  secondary: 'bg-navy-700 text-slate-100 hover:bg-navy-600',
  danger: 'bg-red-800 text-red-50 hover:bg-red-700',
  ghost: 'text-slate-200 underline hover:text-white',
}
export function Button({
  variant = 'secondary',
  busy,
  className = '',
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`rounded-md px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${className}`}
    >
      {busy ? 'Working…' : children}
    </button>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-400">{hint}</span>}
    </label>
  )
}
export const inputClass = 'w-full rounded-md bg-navy-900 px-3 py-1.5 text-sm ring-1 ring-navy-600'

/** Key/value list for details and the evidence drawer. */
export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-400">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

/** A hash: shortened on screen (full value in the title and on copy) with a Copy button. */
export function HashText({ value, label = 'hash', head = 12 }: { value: string; label?: string; head?: number }) {
  const [done, setDone] = useState(false)
  if (!value) return <span className="text-slate-400">none</span>
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setDone(true)
      setTimeout(() => setDone(false), 1500)
    } catch {
      // clipboard unavailable: the full value is in the title
    }
  }
  return (
    <span className="inline-flex items-center gap-1">
      <code title={value} className="font-mono text-xs">
        {value.length > head + 4 ? `${value.slice(0, head)}…` : value}
      </code>
      <button onClick={copy} aria-label={`Copy ${label}`} className="rounded bg-navy-700 px-1.5 py-0.5 text-[11px] hover:bg-navy-600">
        {done ? 'Copied' : 'Copy'}
      </button>
    </span>
  )
}

/** Renders children only when the signed-in role holds `perm`; otherwise `fallback` (default: nothing).
 * The server stays the authority: this only hides what the role cannot do. */
export function Can({ perm, children, fallback = null }: { perm: Permission; children: ReactNode; fallback?: ReactNode }) {
  const { can } = useAuth()
  return <>{can(perm) ? children : fallback}</>
}

/** Plain-language reason a control is disabled for the current role. */
export const READONLY_HINT = 'Your role cannot do this (read-only for this action).'

export const fmtBytes = (n: number) => {
  if (n < 1024) return `${n} B`
  const u = ['KiB', 'MiB', 'GiB', 'TiB']
  let v = n
  let i = -1
  do {
    v /= 1024
    i++
  } while (v >= 1024 && i < u.length - 1)
  return `${v.toFixed(v < 10 ? 2 : 1)} ${u[i]}`
}
export const fmtTime = (iso: string | null | undefined) => (iso ? iso.replace('T', ' ').replace(/\.\d+/, '') : '—')
