import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import CaseDetail from './pages/CaseDetail'
import Analysis from './pages/Analysis'
import Cases from './pages/Cases'
import CustodyLog from './pages/CustodyLog'
import Dashboard from './pages/Dashboard'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="cases" element={<Cases />} />
          <Route path="cases/:id" element={<CaseDetail />} />
          <Route path="evidence/:caseId/:id" element={<Analysis />} />
          <Route path="cases/:id/custody" element={<CustodyLog />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
