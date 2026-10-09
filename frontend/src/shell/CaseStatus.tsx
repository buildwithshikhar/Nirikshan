import { useCallback, useEffect, useState } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { type ChainResult, api } from '../api'
import { apiTimeline } from '../api_timeline'
import { ORIGIN_DISCLOSURE, ORIGIN_HEADLINE, ORIGIN_LABEL } from '../dataOrigin'
import { Chip, HashText } from '../ui'

/** Window event other components dispatch after a change that can alter these indicators
 * (acquisition, saving a time assumption, any custody entry). */
export const STATUS_REFRESH = 'nirikshan:status-refresh'
export const refreshStatusBanners = () => window.dispatchEvent(new Event(STATUS_REFRESH))

/** Case numbers starting with this prefix are demo cases and always show the reference-data banner. */
export const DEMO_PREFIX = 'DEMO-REFERENCE'

export interface CaseStatusData {
  syntheticCount: number
  demoCase: boolean
  total: number
  unknownTz: number[]
  chain: ChainResult | null
}

/** Status of the case in the URL: data origin, evidence without a timezone assumption, custody head. */
export function useCaseStatus(): { caseId: number | null; st: CaseStatusData | null } {
  const { pathname } = useLocation()
  const caseId = Number(matchPath('/cases/:id/*', pathname)?.params.id ?? matchPath('/cases/:id', pathname)?.params.id) || null
  const [st, setSt] = useState<CaseStatusData | null>(null)

  const load = useCallback(() => {
    if (caseId == null) return setSt(null)
    Promise.all([api.getCase(caseId), api.listEvidence(caseId), api.verifyChain(caseId).catch(() => null)])
      .then(async ([kase, evs, chain]) => {
        const acquired = evs.filter((e) => e.status === 'acquired' || e.status === 'integrity_failed')
        const tz = await Promise.all(
          acquired.map((e) =>
            apiTimeline
              .getAssumption(e.id)
              .then((a) => (a.tz_status === 'unknown' ? e.id : null))
              .catch(() => null),
          ),
        )
        setSt({
          syntheticCount: evs.filter((e) => e.synthetic).length,
          demoCase: kase.case_number.startsWith(DEMO_PREFIX),
          total: evs.length,
          unknownTz: tz.filter((x): x is number => x != null),
          chain,
        })
      })
      .catch(() => setSt(null)) // indicators are advisory; each screen shows its own errors
  }, [caseId, pathname])

  useEffect(() => {
    load()
    window.addEventListener(STATUS_REFRESH, load)
    return () => window.removeEventListener(STATUS_REFRESH, load)
  }, [load])
  return { caseId, st }
}

/** Top-bar chips: data origin, timezone unknown (when applicable), custody head_hash (short, Copy). */
export function StatusChips({ caseId, st }: { caseId: number | null; st: CaseStatusData | null }) {
  if (caseId == null || st == null) return null
  const synthetic = st.demoCase || st.syntheticCount > 0
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="status-chips">
      {synthetic && (
        <Chip tone="warn" testId="chip-origin" title={`${ORIGIN_HEADLINE}. ${ORIGIN_DISCLOSURE}`}>
          {ORIGIN_LABEL}
        </Chip>
      )}
      {st.unknownTz.length > 0 && (
        <Chip tone="bad" testId="chip-tz-unknown" title="No timezone assumption: UTC time is not computed for these items">
          Timezone unknown ({st.unknownTz.length})
        </Chip>
      )}
      {st.chain && (
        <span className="flex items-center gap-1 text-xs text-slate-300" data-testid="chip-head">
          <Chip tone={st.chain.ok ? 'ok' : 'bad'}>{st.chain.ok ? 'custody chain valid' : 'CUSTODY CHAIN BROKEN'}</Chip>
          head
          <HashText value={st.chain.head_hash} label="custody head hash" head={10} />
        </span>
      )}
    </div>
  )
}

/** Full-text banners under the top bar on every case screen (the honest wording, not just chips). */
export default function StatusBanners({ caseId, st }: { caseId: number | null; st: CaseStatusData | null }) {
  if (caseId == null || st == null) return null
  const synthetic = st.demoCase || st.syntheticCount > 0
  if (!synthetic && st.unknownTz.length === 0) return null
  return (
    <div className="space-y-2 bg-navy-900 px-6 pt-3" data-testid="status-banners">
      {synthetic && (
        <div role="status" data-testid="status-reference-data" className="rounded border-2 border-amber-400 bg-amber-400 p-2 text-xs font-semibold text-navy-900">
          {ORIGIN_HEADLINE}. {st.demoCase ? 'This is a demo case. ' : ''}
          {st.syntheticCount > 0
            ? `${st.syntheticCount} of ${st.total} evidence item${st.total === 1 ? '' : 's'} in this case ${st.syntheticCount === 1 ? 'is a reference image' : 'are reference images'}. `
            : ''}
          {ORIGIN_DISCLOSURE} Results say nothing about any real device.
        </div>
      )}
      {st.unknownTz.length > 0 && (
        <div role="status" data-testid="status-tz-unknown" className="rounded border-2 border-red-400 bg-red-900 p-2 text-xs font-medium text-red-200">
          TIMEZONE UNKNOWN for evidence {st.unknownTz.map((e) => `#${e}`).join(', ')}: no UTC time is computed and its clips cannot be
          placed on the timeline. Nothing is defaulted.{' '}
          <Link className="underline" to={`/cases/${caseId}/timeline`}>
            Set the time assumption
          </Link>
        </div>
      )}
    </div>
  )
}
