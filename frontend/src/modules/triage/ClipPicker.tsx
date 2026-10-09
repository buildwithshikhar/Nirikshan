import { Link, useSearchParams } from 'react-router-dom'
import { type CarveRunInfo, api } from '../../api'
import { get } from '../../lib/http'
import { EmptyState, Loadable, useAsync } from '../../ui'
import type { ClipOption } from './api'

/** Clips of a case that have an exported video (the only ones analytics can read). */
export function useCaseClips(caseId: number) {
  return useAsync(async (): Promise<ClipOption[]> => {
    const evidence = await api.listEvidence(caseId)
    const runs = await Promise.all(evidence.map((e) => get<CarveRunInfo[]>(`/api/evidence/${e.id}/runs`)))
    return runs.flat().flatMap((r) =>
      r.clips
        .filter((c) => c.kind === 'clip' && c.has_video)
        .map((c) => ({ id: c.id, evidence_id: r.evidence_id, channel: c.channel, codec: c.codec, duration_s: c.duration_s, size_bytes: c.size_bytes })),
    )
  }, [caseId])
}

export const clipLabel = (c: ClipOption) =>
  `Clip #${c.id} (evidence ${c.evidence_id}, channel ${c.channel ?? 'n/a'}, ${c.codec}${c.duration_s != null ? `, ${c.duration_s.toFixed(1)} s` : ''})`

/** Chooses the clip through `?clip=` (the contract other modules link to). */
export function ClipPicker({ caseId, children }: { caseId: number; children: (clip: ClipOption) => React.ReactNode }) {
  const clips = useCaseClips(caseId)
  const [sp, setSp] = useSearchParams()
  return (
    <Loadable state={clips}>
      {(list) => {
        if (list.length === 0)
          return (
            <EmptyState
              title="This case has no exported clips yet"
              hint="Carve evidence in the Recovery Lab first; analytics read exported clips."
              action={<Link className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-navy-900" to={`/cases/${caseId}/recovery`}>Open Recovery Lab</Link>}
            />
          )
        const cur = list.find((c) => c.id === Number(sp.get('clip'))) ?? list[0]
        return (
          <div className="space-y-4">
            <label className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-slate-300">Clip</span>
              <select
                value={cur.id}
                onChange={(e) => {
                  const next = new URLSearchParams(sp)
                  next.set('clip', e.target.value)
                  setSp(next, { replace: true })
                }}
                className="rounded-md bg-navy-900 px-3 py-1.5 ring-1 ring-navy-600"
              >
                {list.map((c) => <option key={c.id} value={c.id}>{clipLabel(c)}</option>)}
              </select>
              <Link className="text-accent underline" to={`/cases/${caseId}/recovery/clips/${cur.id}`}>Open clip</Link>
            </label>
            {children(cur)}
          </div>
        )
      }}
    </Loadable>
  )
}
