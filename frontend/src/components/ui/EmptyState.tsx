import type { ReactNode } from 'react'

/**
 * An empty screen is an invitation to act, so it always names the next step
 * rather than apologising for having nothing.
 */
export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && <div className="text-ink-400">{icon}</div>}
      <h3 className="font-display text-base font-semibold">{title}</h3>
      <p className="max-w-sm text-sm muted">{body}</p>
      {action && <div className="pt-1">{action}</div>}
    </div>
  )
}
