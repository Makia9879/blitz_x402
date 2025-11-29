import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import DashboardPage from './pages/DashboardPage'
import RechargePage from './pages/RechargePage'

const App = () => (
  <AppShell>
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/recharge" element={<RechargePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </AppShell>
)

export default App
