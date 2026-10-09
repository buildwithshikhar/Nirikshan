import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../../api'
import { useAuth } from '../../auth/AuthContext'
import { errorText } from '../../lib/http'
import { Button, Card, Chip, DataTable, HashText, Loadable, PageHeader, READONLY_HINT, Tabs, fmtBytes, useAsync, useToast } from '../../ui'
import { type ClipLite, integrityApi } from './api'
import { ChainVerify } from './ChainVerify'
import { IntegrityNav } from './IntegrityNav'

type Outcome = { ok: boolean; text: string }

function HashReverify({ caseId }: { caseId: number }) {
  const { can } = useAuth()
  const toast = useToast()
  const writable = can('case.write')
  const evidence = useAsync(() => api.listEvidence(caseId), [caseId])
  const clips = useAsync(async () => {
    const list = await api.listEvidence(caseId)
    const runs = await Promise.all(list.map((e) => integrityApi.runs(e.id).then((r) => r.map((x) => ({ ev: e.id, clips: x.clips })))))
    return runs.flat().flatMap((r) => r.clips.filter((c) => c.kind === 'clip' && c.mp4_sha256).map((c) => ({ ...c, ev: r.ev })))
  }, [caseId])
  const [out, setOut] = useState<Record<string, Outcome>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (key: string, fn: () => Promise<Outcome>) => {
    setBusy(key)
    try {
      const o = await fn()
      setOut((m) => ({ ...m, [key]: o }))
      if (!o.ok) toast.error(`${key}: hash does NOT match`)
      else toast.ok(`${key}: hash matches (custody entry written)`)
    } catch (e) {
      toast.error(errorText(e))
    } finally {
      setBusy(null)
    }
  }
  const verdict = (key: string) => {
    const o = out[key]
    return o ? <span data-testid={`verdict-${key.replace(/\s/g, '-')}`}><Chip tone={o.ok ? 'ok' : 'bad'}>{o.ok ? 'MATCH' : 'MISMATCH'}</Chip> <span className="text-xs">{o.text}</span></span> : <span className="text-slate-400">not checked</span>
  }
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-300">
        Re-hashing reads the stored file again and compares it with the hash recorded at acquisition or carve time. Every check writes a custody entry.
      </p>
      {!writable && <p className="text-sm text-slate-300">{READONLY_HINT}</p>}
      <section aria-labelledby="ev-h">
        <h2 id="ev-h" className="mb-2 font-medium">Evidence images</h2>
        <Loadable state={evidence}>
          {(rows) => (
            <DataTable
              testId="reverify-evidence"
              caption="Evidence images to re-verify"
              rows={rows}
              rowKey={(e) => e.id}
              empty={{ title: 'No evidence in this case yet' }}
              columns={[
                { key: 'id', header: '#', render: (e) => e.id, sort: (e) => e.id },
                { key: 'l', header: 'Label', render: (e) => e.label, sort: (e) => e.label },
                { key: 'sz', header: 'Size', render: (e) => fmtBytes(e.size_bytes) },
                { key: 'sha', header: 'Recorded SHA-256', render: (e) => <HashText value={e.sha256} label="SHA-256" /> },
                { key: 'res', header: 'Result', render: (e) => verdict(`evidence ${e.id}`) },
                {
                  key: 'act',
                  header: 'Action',
                  render: (e) =>
                    writable ? (
                      <Button aria-label={`Re-verify evidence ${e.id}`} busy={busy === `evidence ${e.id}`} onClick={() =>
                        run(`evidence ${e.id}`, async () => {
                          const r = await integrityApi.verifyEvidence(e.id)
                          return { ok: r.ok, text: r.ok ? `SHA-256 ${r.observed?.sha256.slice(0, 12)}…` : r.error || `observed ${r.observed?.sha256.slice(0, 12)}…, expected ${r.expected.sha256.slice(0, 12)}…` }
                        })
                      }>Re-verify</Button>
                    ) : null,
                },
              ]}
            />
          )}
        </Loadable>
      </section>
      <section aria-labelledby="clip-h">
        <h2 id="clip-h" className="mb-2 font-medium">Exported clips</h2>
        <Loadable state={clips}>
          {(rows) => (
            <DataTable
              testId="reverify-clips"
              caption="Exported clips to re-verify"
              rows={rows as (ClipLite & { ev: number })[]}
              rowKey={(c) => c.id}
              empty={{ title: 'No exported clips yet', hint: 'Carve evidence in the Recovery Lab first.' }}
              columns={[
                { key: 'id', header: 'Clip', render: (c) => `#${c.id}`, sort: (c) => c.id },
                { key: 'ev', header: 'Evidence', render: (c) => `#${c.ev}`, sort: (c) => c.ev },
                { key: 'sha', header: 'Recorded MP4 SHA-256', render: (c) => <HashText value={c.mp4_sha256} label="MP4 SHA-256" /> },
                { key: 'res', header: 'Result', render: (c) => verdict(`clip ${c.id}`) },
                {
                  key: 'act',
                  header: 'Action',
                  render: (c) =>
                    writable ? (
                      <Button aria-label={`Re-verify clip ${c.id}`} busy={busy === `clip ${c.id}`} onClick={() =>
                        run(`clip ${c.id}`, async () => {
                          const r = await integrityApi.verifyClip(c.id)
                          return { ok: r.ok, text: r.ok ? 'MP4 matches the hash recorded at carve time' : `observed ${r.observed.slice(0, 12) || 'unreadable'}…` }
                        })
                      }>Re-verify</Button>
                    ) : null,
                },
              ]}
            />
          )}
        </Loadable>
      </section>
    </div>
  )
}

export default function Verification() {
  const caseId = Number(useParams().caseId)
  return (
    <div>
      <PageHeader title="Verification" subtitle="Check the custody chain and re-hash stored evidence and clips. Reference test data only." />
      <IntegrityNav caseId={caseId} />
      <Card>
        <Tabs
          label="Verification"
          tabs={[
            { id: 'chain', label: 'Chain check', render: () => <ChainVerify caseId={caseId} /> },
            { id: 'hash', label: 'Hash re-verify', render: () => <HashReverify caseId={caseId} /> },
          ]}
        />
      </Card>
    </div>
  )
}
