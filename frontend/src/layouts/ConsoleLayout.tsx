import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'

const TITLES: Record<string, string> = {
  '/dashboard': 'Overview',
  '/inbox': 'Inbox',
  '/approvals': 'Approval queue',
  '/contacts': 'Contacts',
  '/leads': 'Leads',
  '/campaigns': 'Campaigns',
  '/content': 'Content',
  '/knowledge': 'Knowledge base',
  '/workflows': 'Workflows',
  '/analytics': 'Analytics',
  '/settings': 'Settings',
}

export function ConsoleLayout() {
  const { pathname } = useLocation()
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar title={TITLES[pathname] ?? 'OmniAI'} />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
