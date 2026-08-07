import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '@/hooks/useAuth'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { ConsoleLayout } from '@/layouts/ConsoleLayout'
import { Dashboard } from '@/pages/Dashboard'
import { Login } from '@/pages/Login'
import { Placeholder } from '@/pages/Placeholder'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
})

/** Routes not yet implemented, each labelled with the step that delivers it. */
const PENDING: Array<[string, string, string, string]> = [
  ['/inbox', 'Unified inbox', 'Step 9', 'Every conversation from all four channels in one list.'],
  ['/approvals', 'Approval queue', 'Step 16', 'Replies and posts the AI wants a person to sign off.'],
  ['/contacts', 'Contacts', 'Step 3', 'People you talk to, across every platform.'],
  ['/leads', 'Leads', 'Step 13', 'Qualified opportunities with scores and follow-up state.'],
  ['/campaigns', 'Campaigns', 'Step 15', 'Briefs that generate platform-specific content.'],
  ['/content', 'Content', 'Step 17', 'Drafts, the schedule calendar, and what has published.'],
  ['/knowledge', 'Knowledge base', 'Step 11', 'Documents the support agent answers from.'],
  ['/workflows', 'Workflows', 'Step 1', 'n8n runs, success and failure counts, durations.'],
  ['/analytics', 'Analytics', 'Step 18', 'Volume, automation rate, conversion, and response time.'],
  ['/settings', 'Settings', 'Step 5', 'Channel credentials, team members, and AI thresholds.'],
]

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <ProtectedRoute>
                  <ConsoleLayout />
                </ProtectedRoute>
              }
            >
              <Route path="/dashboard" element={<Dashboard />} />
              {PENDING.map(([path, title, step, describes]) => (
                <Route
                  key={path}
                  path={path}
                  element={<Placeholder title={title} step={step} describes={describes} />}
                />
              ))}
            </Route>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
