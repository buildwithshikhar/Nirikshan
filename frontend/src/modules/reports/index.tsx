import { Route, Routes } from 'react-router-dom'
import Builder from './Builder'
import Exports from './Exports'

export default function ReportsModule() {
  return (
    <Routes>
      <Route index element={<Builder />} />
      <Route path="exports" element={<Exports />} />
      <Route path="*" element={<Builder />} />
    </Routes>
  )
}
