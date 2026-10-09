import { type ReactNode } from 'react'

/** Small, safe Markdown renderer for the bundled docs (headings, paragraphs, lists, tables, fenced
 * code, quotes, bold/italic/inline code/links). It builds React elements only: no HTML is injected. */

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)]+\))/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const t = m[0]
    const k = `${key}-${i++}`
    if (t.startsWith('`')) out.push(<code key={k} className="rounded bg-navy-900 px-1 py-0.5 font-mono text-[0.85em]">{t.slice(1, -1)}</code>)
    else if (t.startsWith('**')) out.push(<strong key={k}>{t.slice(2, -2)}</strong>)
    else if (t.startsWith('*')) out.push(<em key={k}>{t.slice(1, -1)}</em>)
    else {
      const [, label, href] = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)!
      out.push(
        /^https?:\/\//.test(href) ? (
          <a key={k} href={href} target="_blank" rel="noreferrer noopener" className="text-accent underline">{label}</a>
        ) : (
          <span key={k} title={href}>{label}</span>
        ),
      )
    }
    last = m.index + t.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r/g, '').split('\n')
  const out: ReactNode[] = []
  let i = 0
  let n = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${n++}`
    if (!line.trim()) {
      i++
    } else if (line.startsWith('```')) {
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++])
      i++
      out.push(<pre key={key} className="overflow-x-auto rounded bg-navy-900 p-3 font-mono text-xs"><code>{code.join('\n')}</code></pre>)
    } else if (/^#{1,6}\s/.test(line)) {
      const level = /^#+/.exec(line)![0].length
      const text = line.replace(/^#+\s*/, '')
      const cls = ['text-2xl font-semibold mt-6', 'text-xl font-semibold mt-6', 'text-lg font-semibold mt-5', 'font-semibold mt-4', 'font-semibold mt-3', 'font-semibold mt-3'][level - 1]
      // the page owns the single <h1>; document headings start at h2
      const Tag = `h${Math.min(level + 1, 6)}` as 'h2'
      out.push(<Tag key={key} className={cls}>{inline(text, key)}</Tag>)
      i++
    } else if (line.trim().startsWith('|') && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] ?? '')) {
      const head = cells(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(cells(lines[i++]))
      out.push(
        <div key={key} className="my-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Table (scrollable)">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-400"><tr>{head.map((h, j) => <th key={j} scope="col" className="px-3 py-2">{inline(h, `${key}h${j}`)}</th>)}</tr></thead>
            <tbody className="divide-y divide-navy-700">
              {rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k} className="px-3 py-2 align-top">{inline(c, `${key}r${j}c${k}`)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>,
      )
    } else if (/^\s*([-*]|\d+\.)\s/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''))
      const L = ordered ? 'ol' : 'ul'
      out.push(<L key={key} className={`my-2 space-y-1 pl-6 ${ordered ? 'list-decimal' : 'list-disc'}`}>{items.map((t, j) => <li key={j}>{inline(t, `${key}i${j}`)}</li>)}</L>)
    } else if (line.startsWith('>')) {
      const q: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) q.push(lines[i++].replace(/^>\s?/, ''))
      out.push(<blockquote key={key} className="my-2 border-l-4 border-accent pl-3 text-slate-300">{inline(q.join(' '), key)}</blockquote>)
    } else {
      const p: string[] = []
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|\s*([-*]|\d+\.)\s|\|)/.test(lines[i])) p.push(lines[i++])
      if (p.length === 0) { p.push(lines[i++]) }
      out.push(<p key={key} className="my-2 leading-relaxed">{inline(p.join(' '), key)}</p>)
    }
  }
  return <div className="max-w-4xl text-sm" data-testid="markdown">{out}</div>
}
