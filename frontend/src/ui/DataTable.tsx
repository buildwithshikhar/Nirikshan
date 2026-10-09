import { type ReactNode, useMemo, useState } from 'react'
import { EmptyState } from './states'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  /** value used for sorting (and the default filter text); omit to make the column unsortable */
  sort?: (row: T) => string | number
  /** extra text matched by the filter box */
  text?: (row: T) => string
  className?: string
}

/** Sortable, filterable, paginated table. Sorting is on header buttons (aria-sort); the filter
 * matches every column's sort/text value; pages of 10/25/50. */
export function DataTable<T>({
  rows,
  columns,
  caption,
  rowKey,
  empty,
  filterable = true,
  pageSize = 10,
  onRowClick,
  testId,
}: {
  rows: T[]
  columns: Column<T>[]
  caption: string
  rowKey: (r: T) => string | number
  empty?: { title: string; hint?: string; action?: ReactNode }
  filterable?: boolean
  pageSize?: number
  onRowClick?: (r: T) => void
  testId?: string
}) {
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [dir, setDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(pageSize)

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    let out = rows
    if (needle) {
      out = out.filter((r) =>
        columns.some((c) => String(c.text?.(r) ?? c.sort?.(r) ?? '').toLowerCase().includes(needle)),
      )
    }
    const col = columns.find((c) => c.key === sortKey)
    if (col?.sort) {
      const s = col.sort
      out = [...out].sort((a, b) => {
        const x = s(a)
        const y = s(b)
        const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
        return dir === 'asc' ? r : -r
      })
    }
    return out
  }, [rows, columns, q, sortKey, dir])

  if (rows.length === 0 && empty) return <EmptyState {...empty} />
  const pages = Math.max(1, Math.ceil(shown.length / size))
  const cur = Math.min(page, pages - 1)
  const slice = shown.slice(cur * size, cur * size + size)

  return (
    <div data-testid={testId}>
      {filterable && rows.length > size / 2 && (
        <input
          aria-label={`Filter ${caption}`}
          placeholder="Filter rows"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setPage(0)
          }}
          className="mb-2 w-64 rounded-md bg-navy-900 px-3 py-1 text-sm ring-1 ring-navy-600"
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="text-xs uppercase text-slate-400">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className="px-3 py-2"
                  aria-sort={sortKey === c.key ? (dir === 'asc' ? 'ascending' : 'descending') : c.sort ? 'none' : undefined}
                >
                  {c.sort ? (
                    <button
                      className="uppercase hover:text-white"
                      onClick={() => {
                        if (sortKey === c.key) setDir(dir === 'asc' ? 'desc' : 'asc')
                        else {
                          setSortKey(c.key)
                          setDir('asc')
                        }
                      }}
                    >
                      {c.header}
                      {sortKey === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-navy-700">
            {slice.map((r) => (
              <tr
                key={rowKey(r)}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={onRowClick ? 'cursor-pointer hover:bg-navy-800' : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key} className={`px-3 py-2 align-top ${c.className ?? ''}`}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))}
            {slice.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-4 text-center text-slate-400">
                  No rows match the filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {shown.length > 10 && (
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-300">
          <span>
            {shown.length} rows, page {cur + 1} of {pages}
          </span>
          <button disabled={cur === 0} onClick={() => setPage(cur - 1)} className="rounded bg-navy-700 px-2 py-1 disabled:opacity-40">
            Previous
          </button>
          <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)} className="rounded bg-navy-700 px-2 py-1 disabled:opacity-40">
            Next
          </button>
          <label className="flex items-center gap-1">
            Rows per page
            <select value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(0) }} className="rounded bg-navy-900 px-1 py-0.5 ring-1 ring-navy-600">
              {[10, 25, 50].map((n) => <option key={n}>{n}</option>)}
            </select>
          </label>
        </div>
      )}
    </div>
  )
}
