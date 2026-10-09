import { Route, Routes } from 'react-router-dom'
import CustodyLog from './CustodyLog'
import Verification from './Verification'

export default function IntegrityModule() {
  return (
    <Routes>
      <Route index element={<CustodyLog />} />
      <Route path="verification" element={<Verification />} />
      <Route path="*" element={<CustodyLog />} />
    </Routes>
  )
}
