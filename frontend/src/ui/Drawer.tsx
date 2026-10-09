import { type ReactNode, useEffect, useRef } from 'react'

/** Right-hand drawer (role=dialog). Esc or the close button closes it; focus moves in on open and
 * returns to the opener on close. Non-modal: the page behind stays usable and visible. */
export function Drawer({
  open,
  title,
  onClose,
  children,
  testId,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  testId?: string
}) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    ref.current?.focus()
    return () => opener?.focus?.()
  }, [open])
  if (!open) return null
  return (
    <aside
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-label={title}
      data-testid={testId}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      className="fixed inset-y-0 right-0 z-50 flex w-[28rem] max-w-full flex-col border-l border-navy-600 bg-navy-800 shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-navy-700 px-4 py-3">
        <h2 className="font-semibold">{title}</h2>
        <button aria-label={`Close ${title}`} onClick={onClose} className="rounded px-2 py-1 hover:bg-navy-700">
          ×
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 text-sm">{children}</div>
    </aside>
  )
}
