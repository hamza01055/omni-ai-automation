import { cn } from '@/utils/cn'

type Tone = 'neutral' | 'ok' | 'warn' | 'risk' | 'info'

const TONES: Record<Tone, string> = {
  neutral: 'bg-ink-500/15 text-ink-300 ring-ink-500/25',
  ok: 'bg-ok/12 text-ok ring-ok/25',
  warn: 'bg-signal/12 text-signal ring-signal/30',
  risk: 'bg-risk/12 text-risk ring-risk/25',
  info: 'bg-channel-facebook/12 text-channel-facebook ring-channel-facebook/25',
}

export function StatusPill({
  children,
  tone = 'neutral',
  className,
}: {
  children: React.ReactNode
  tone?: Tone
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-micro font-medium uppercase',
        'tracking-wider ring-1 ring-inset',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
