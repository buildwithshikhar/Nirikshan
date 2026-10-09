import { Route, Routes } from 'react-router-dom'
import Registry from './Registry'
import ValidationCenter from './ValidationCenter'

export default function ValidationModule() {
  return (
    <Routes>
      <Route index element={<ValidationCenter />} />
      <Route path="compatibility" element={<Registry />} />
      <Route path="*" element={<ValidationCenter />} />
    </Routes>
  )
}
