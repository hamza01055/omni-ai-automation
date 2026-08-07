import { NavLink } from 'react-router-dom'
import {
  BarChart3, BookOpen, Inbox, Megaphone, Settings, ShieldCheck,
  Sparkles, Users, Workflow,
} from 'lucide-react'
import { cn } from '@/utils/cn'

/**
 * Navigation is grouped by what the operator is doing, not by data model:
 * conversations first (the live surface), then the pipeline it feeds, then
 * the machinery behind it.
 */
const GROUPS = [
  {
    label: 'Conversations',
    items: [
      { to: '/inbox', label: 'Inbox', icon: Inbox },
      { to: '/approvals', label: 'Approvals', icon: ShieldCheck },
      { to: '/contacts', label: 'Contacts', icon: Users },
    ],
  },
  {
    label: 'Pipeline',
    items: [
      { to: '/leads', label: 'Leads', icon: BarChart3 },
      { to: '/campaigns', label: 'Campaigns', icon: Megaphone },
      { to: '/content', label: 'Content', icon: Sparkles },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/knowledge', label: 'Knowledge base', icon: BookOpen },
      { to: '/workflows', label: 'Workflows', icon: Workflow },
      { to: '/analytics', label: 'Analytics', icon: BarChart3 },
      { to: '/settings', label: 'Settings', icon: Settings },
    ],
  },
]

export function Sidebar({ pendingApprovals = 0 }: { pendingApprovals?: number }) {
  return (
    <nav
      aria-label="Main"
      className="hidden w-56 shrink-0 flex-col gap-6 border-r hairline px-3 py-5 lg:flex"
      style={{ background: 'var(--surface-raised)' }}
    >
      <div className="flex items-center gap-2.5 px-2">
        <img src="/mark.svg" alt="" className="h-7 w-7" />
        <span className="font-display text-sm font-bold tracking-tight">OmniAI</span>
      </div>

      {GROUPS.map((group) => (
        <div key={group.label} className="space-y-1">
          <p className="eyebrow px-2 pb-1">{group.label}</p>
          {group.items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-control px-2 py-1.5 text-sm transition',
                  isActive
                    ? 'bg-signal/10 font-medium text-signal'
                    : 'muted hover:bg-ink-100/60 dark:hover:bg-ink-800',
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              <span className="flex-1">{label}</span>
              {to === '/approvals' && pendingApprovals > 0 && (
                <span className="rounded-full bg-signal px-1.5 font-mono text-micro font-bold text-ink-950">
                  {pendingApprovals}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  )
}
