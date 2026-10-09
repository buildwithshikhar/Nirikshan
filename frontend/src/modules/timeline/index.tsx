import { Route, Routes } from 'react-router-dom'
import TimeSettingsScreen from './TimeSettings'
import TimelineScreen from './TimelineScreen'

export default function TimelineModule() {
  return (
    <Routes>
      <Route index element={<TimelineScreen />} />
      <Route path="time-settings" element={<TimeSettingsScreen />} />
      <Route path="*" element={<TimelineScreen />} />
    </Routes>
  )
}
