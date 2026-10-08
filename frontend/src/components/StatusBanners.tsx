import { useCallback, useEffect, useState } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { api } from '../api'
import { apiTimeline } from '../api_timeline'

/** Window event other components dispatch after a change that can alter these banners
 * (acquisition, saving a time assumption). */
export const STATUS_REFRESH = 'nirikshan:status-refresh'
export const refreshStatusBanners = () => window.dispatchEvent(new Event(STATUS_REFRESH))

/** Case numbers starting with this prefix are demo cases and always show the SYNTHETIC banner. */
export const DEMO_PREFIX = 'DEMO-SYNTHETIC'

/** The case the current route belongs to, if any. A clip route carries it as ?case=<id>. */
export function caseIdFromPath(pathname: string, search: string): number | null {
  const ev = matchPath('/evidence/:caseId/:id', pathname)
  if (ev) return Number(ev.params.caseId)
  const c = matchPath('/cases/:id/*', pathname) ?? matchPath('/cases/:id', pathname)
  if (c) return Number(c.params.id)
  if (matchPath('/clips/:clipId/analytics', pathname)) {
    const c = Number(new URLSearchParams(search).get('case'))
    return c > 0 ? c : null
  }
  return null
}

interface Status {
  syntheticCount: number
  demoCase: boolean
  total: number
  unknownTz: number[]
  demoCases: number // list pages only: SYNTHETIC demo cases present in this workspace
}

/**
 * Two persistent banners, shown on every page that belongs to a case:
 *  1. SYNTHETIC: some evidence carries the SYNTHETIC image banner, or the case is a demo case.
 *  2. UNKNOWN TIMEZONE: some evidence has no examiner timezone assumption (P5), so its clips cannot
 *     be placed in UTC. Nothing is defaulted; the banner links to where it is set.
 */
export default function StatusBanners() {
  const { pathname, search } = useLocation()
  const caseId = caseIdFromPath(pathname, search)
  const [st, setSt] = useState<Status | null>(null)

  const load = useCallback(() => {
    if (caseId == null) {
      if (pathname === '/' || pathname === '/cases') {
        api
          .listCases()
          .then((cs) => {
            const n = cs.filter((c) => c.case_number.startsWith(DEMO_PREFIX)).length
            setSt({ syntheticCount: 0, demoCase: false, total: 0, unknownTz: [], demoCases: n })
          })
          .catch(() => setSt(null))
      } else setSt(null)
      return
    }
    Promise.all([api.getCase(caseId), api.listEvidence(caseId)])
      .then(async ([kase, evs]) => {
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
          demoCases: 0,
        })
      })
      .catch(() => setSt(null)) // banners are advisory; page-level errors are shown by the page
  }, [caseId, pathname])

  useEffect(() => {
    load()
    window.addEventListener(STATUS_REFRESH, load)
    return () => window.removeEventListener(STATUS_REFRESH, load)
  }, [load, pathname])

  if (st == null) return null
  if (caseId == null) {
    if (st.demoCases === 0) return null
    return (
      <div className="sticky top-0 z-40 bg-navy-900 px-6 py-3" data-testid="status-banners">
        <div
          role="status"
          data-testid="status-synthetic"
          className="rounded border-2 border-amber-400 bg-amber-400 p-2 text-xs font-semibold text-navy-900"
        >
          SYNTHETIC DATA: this workspace contains {st.demoCases} SYNTHETIC demo case{st.demoCases === 1 ? '' : 's'}{' '}
          (generated test images, not real DVR/NVR evidence).
        </div>
      </div>
    )
  }
  const synthetic = st.demoCase || st.syntheticCount > 0
  if (!synthetic && st.unknownTz.length === 0) return null

  return (
    <div className="sticky top-0 z-40 space-y-2 bg-navy-900 px-6 py-3" data-testid="status-banners">
      {synthetic && (
        <div
          role="status"
          data-testid="status-synthetic"
          className="rounded border-2 border-amber-400 bg-amber-400 p-2 text-xs font-semibold text-navy-900"
        >
          SYNTHETIC DATA: {st.demoCase ? 'this is a demo case; ' : ''}
          {st.syntheticCount > 0
            ? `${st.syntheticCount} of ${st.total} evidence item${st.total === 1 ? '' : 's'} in this case ${
                st.syntheticCount === 1 ? 'is' : 'are'
              } generated test image${st.syntheticCount === 1 ? '' : 's'}`
            : 'its evidence is generated test data'}
          , not real DVR/NVR evidence. Results say nothing about any real device.
        </div>
      )}
      {st.unknownTz.length > 0 && (
        <div
          role="status"
          data-testid="status-tz-unknown"
          className="rounded border-2 border-red-400 bg-red-900 p-2 text-xs font-medium text-red-200"
        >
          TIMEZONE UNKNOWN for evidence {st.unknownTz.map((e) => `#${e}`).join(', ')}: no UTC time is computed and
          its clips cannot be placed on the timeline. Nothing is defaulted.{' '}
          <Link className="underline" to={`/cases/${caseId}/timeline`}>
            Set the time assumption
          </Link>
        </div>
      )}
    </div>
  )
}
