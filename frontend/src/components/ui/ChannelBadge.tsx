import { PLATFORM_LABEL, PLATFORM_STYLE, type Platform } from '@/types/domain'
import { cn } from '@/utils/cn'

/**
 * Channel identity as data, not decoration: a coloured dot plus the platform
 * name. Colour alone never carries the meaning, so it still works for anyone
 * who cannot distinguish the four hues.
 */
export function ChannelBadge({
  platform,
  live = true,
  showLabel = true,
  className,
}: {
  platform: Platform
  /** False when the channel is running on its mock adapter. */
  live?: boolean
  showLabel?: boolean
  className?: string
}) {
  const style = PLATFORM_STYLE[platform]
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span
        className={cn('h-2 w-2 shrink-0 rounded-full', style.dot, !live && 'opacity-40')}
        aria-hidden
      />
      {showLabel && (
        <span className="text-meta font-medium">
          {PLATFORM_LABEL[platform]}
          {!live && <span className="muted"> · sandbox</span>}
        </span>
      )}
      <span className="sr-only">{PLATFORM_LABEL[platform]}</span>
    </span>
  )
}
