import { useState } from 'react'
import { PageHeader, Tabs } from '../../ui'
import { Markdown } from './Markdown'

// Docs are bundled at build time, so Help works offline. Paths are relative to this file; the
// frontend Dockerfile copies ./docs to /docs so the same relative path resolves in the image build.
const raw = import.meta.glob(
  [
    '../../../../docs/sop/*.md',
    '../../../../docs/USER_MANUAL.md',
    '../../../../docs/oem-registry.md',
    '../../../../docs/recoverability.md',
    '../../../../docs/workers.md',
    '../../../../docs/legal/BSA-63-4-notes.md',
    '../../../../docs/security/auth.md',
    '../../../../docs/ROUND_D_DEFERRED.md',
  ],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>

const doc = (suffix: string) => {
  const k = Object.keys(raw).find((p) => p.endsWith(suffix))
  return k ? raw[k] : null
}
const title = (src: string, fallback: string) => /^#\s+(.+)$/m.exec(src)?.[1] ?? fallback

const SOPS = Object.keys(raw)
  .filter((p) => p.includes('/docs/sop/'))
  .sort()
  .map((p) => ({ id: p.split('/').pop()!.replace('.md', ''), src: raw[p] }))

const LIMITS: [string, string][] = [
  ['oem-registry.md', 'Compatibility registry and tiers'],
  ['recoverability.md', 'Recoverability estimate'],
  ['workers.md', 'Worker isolation'],
  ['security/auth.md', 'What authentication does not protect'],
  ['ROUND_D_DEFERRED.md', 'Deferred items'],
  ['legal/BSA-63-4-notes.md', 'BSA s.63(4) certificate notes'],
]

function DocPicker({ items }: { items: { id: string; label: string; src: string | null }[] }) {
  const [id, setId] = useState(items[0]?.id)
  const cur = items.find((i) => i.id === id) ?? items[0]
  if (!cur) return <p>No documents are bundled.</p>
  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
      <ul className="space-y-1" aria-label="Documents">
        {items.map((i) => (
          <li key={i.id}>
            <button
              onClick={() => setId(i.id)}
              aria-current={i.id === cur.id}
              className={`w-full rounded px-3 py-1.5 text-left text-sm ${i.id === cur.id ? 'bg-accent font-semibold text-navy-900' : 'hover:bg-navy-700'}`}
            >
              {i.label}
            </button>
          </li>
        ))}
      </ul>
      <article>{cur.src ? <Markdown source={cur.src} /> : <p>This document is not bundled.</p>}</article>
    </div>
  )
}

export default function HelpModule() {
  const manual = doc('USER_MANUAL.md')
  return (
    <div>
      <PageHeader title="Help" subtitle="Bundled with the application: works offline. Standard operating procedures, the user manual, and the limits and tiers of this tool." />
      <Tabs
        label="Help sections"
        tabs={[
          { id: 'sops', label: 'SOPs', render: () => <DocPicker items={SOPS.map((s) => ({ id: s.id, label: title(s.src, s.id), src: s.src }))} /> },
          { id: 'manual', label: 'Manual', render: () => (manual ? <Markdown source={manual} /> : <p>The manual is not bundled.</p>) },
          {
            id: 'limits',
            label: 'Limits and tiers',
            render: () => (
              <div className="space-y-4">
                <p className="max-w-3xl text-sm text-slate-300">
                  Reference test data only; no vendor is supported above Tier B; nothing here has been validated on a real device.
                  Recoverability is a rough estimate whose measured agreement with ground truth is weak (correlation 0.44).
                  Worker isolation is subprocess workers with best-effort limits.
                </p>
                <DocPicker items={LIMITS.map(([f, label]) => ({ id: f, label, src: doc(f) }))} />
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
