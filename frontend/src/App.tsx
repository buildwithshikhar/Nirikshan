import { type ReactNode, Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { AuthProvider, RequireAuth, RequirePermission } from './auth/AuthContext'
import Login from './auth/Login'
import { CaseProvider } from './shell/CaseContext'
import Shell from './shell/Shell'
import { Skeleton, ToastProvider } from './ui'

const lazyMod = (f: () => Promise<{ default: React.ComponentType }>) => lazy(f)
const Dashboard = lazyMod(() => import('./modules/dashboard'))
const Evidence = lazyMod(() => import('./modules/evidence'))
const Device = lazyMod(() => import('./modules/device'))
const Explorer = lazyMod(() => import('./modules/explorer'))
const Recovery = lazyMod(() => import('./modules/recovery'))
const Timeline = lazyMod(() => import('./modules/timeline'))
const Triage = lazyMod(() => import('./modules/triage'))
const Correlation = lazyMod(() => import('./modules/correlation'))
const Integrity = lazyMod(() => import('./modules/integrity'))
const Reports = lazyMod(() => import('./modules/reports'))
const Validation = lazyMod(() => import('./modules/validation'))
const Jobs = lazyMod(() => import('./modules/jobs'))
const Admin = lazyMod(() => import('./modules/admin'))
const Help = lazyMod(() => import('./modules/help'))
const CaseList = lazy(() => import('./modules/cases').then((m) => ({ default: m.CaseList })))
const CaseDetail = lazy(() => import('./modules/cases').then((m) => ({ default: m.CaseDetail })))

const Loading = ({ children }: { children: ReactNode }) => (
  <Suspense fallback={<Skeleton rows={4} />}>{children}</Suspense>
)

/** Old bookmarks: /cases/:id/custody is now the Integrity Center. */
const ToIntegrity = () => <Navigate to={`/cases/${useParams().id}/integrity`} replace />

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="login" element={<Login />} />
            <Route
              element={
                <RequireAuth>
                  <CaseProvider>
                    <Shell />
                  </CaseProvider>
                </RequireAuth>
              }
            >
              {/* every route element is wrapped once so each module code-splits */}
              {(
                [
                  ['', <Dashboard />],
                  ['cases', <CaseList />],
                  ['cases/:caseId', <CaseDetail />],
                  ['cases/:caseId/evidence/*', <Evidence />],
                  ['cases/:caseId/identification/*', <Device />],
                  ['cases/:caseId/explorer/*', <Explorer />],
                  ['cases/:caseId/recovery/*', <Recovery />],
                  ['cases/:caseId/timeline/*', <Timeline />],
                  ['cases/:caseId/triage/*', <Triage />],
                  ['cases/:caseId/correlation/*', <Correlation />],
                  ['cases/:caseId/integrity/*', <Integrity />],
                  ['cases/:caseId/reports/*', <Reports />],
                  ['cases/:caseId/jobs/*', <Jobs />],
                  ['validation/*', <Validation />],
                  ['help/*', <Help />],
                ] as [string, ReactNode][]
              ).map(([path, el]) => (
                <Route key={path} path={path} element={<Loading>{el}</Loading>} />
              ))}
              <Route path="cases/:id/custody" element={<ToIntegrity />} />
              <Route
                path="admin/*"
                element={
                  <RequirePermission perm="users.manage">
                    <Loading>
                      <Admin />
                    </Loading>
                  </RequirePermission>
                }
              />
              <Route path="*" element={<div role="alert" className="p-6">Page not found.</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
