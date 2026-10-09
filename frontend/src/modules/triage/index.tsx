import { Route, Routes } from 'react-router-dom'
import Results from './Results'
import Run from './Run'
import Search from './Search'

export default function TriageModule() {
  return (
    <Routes>
      <Route index element={<Run />} />
      <Route path="results" element={<Results />} />
      <Route path="search" element={<Search />} />
      <Route path="*" element={<Run />} />
    </Routes>
  )
}
