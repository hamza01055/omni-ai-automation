import { cn } from '@/utils/cn'
import { BAND_COPY, band, formatConfidence } from '@/utils/confidence'
import type { Intent } from '@/types/domain'

/**
 * The console's signature element.
 *
 * Every place the AI made a decision, this shows the same three things:
 * the raw score in mono (a machine produced it), a five-segment bar filled
 * to the score, and — critically — which of the three policy bands it landed
 * in. Operators learn to read the segments before they read the number.
 */

interface Props {
  confidence: number | null | undefined
  intent?: Intent | null
  /** `bar` for lists, `full` for detail panes where the reason matters. */
  variant?: 'bar' | 'full'
  className?: string
}

const SEGMENTS = 5

const FILL: Record<string, string> = {
  auto: 'bg-ok',
  review: 'bg-signal',
  human: 'bg-risk',
}

export function ConfidenceGauge({ confidence, intent, variant = 'bar', className }: Props) {
  const b = band(confidence, intent)
  const copy = BAND_COPY[b]
  const filled = confidence == null ? 0 : Math.round(confidence * SEGMENTS)

  const gauge = (
    <span
      className="flex items-center gap-[3px]"
      role="img"
      aria-label={`Confidence ${formatConfidence(confidence)}. ${copy.label}.`}
    >
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <span
          key={i}
          className={cn(
            'h-3 w-[3px] rounded-full transition-colors',
            i < filled ? FILL[b] : 'bg-ink-600/50',
          )}
        />
      ))}
    </span>
  )

  if (variant === 'bar') {
    return (
      <span className={cn('inline-flex items-center gap-2', className)} title={copy.explain}>
        {gauge}
        <span className={cn('font-mono text-meta tabular-nums', copy.tone)}>
          {formatConfidence(confidence)}
        </span>
      </span>
    )
  }

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center gap-2.5">
        {gauge}
        <span className={cn('font-mono text-sm font-medium tabular-nums', copy.tone)}>
          {formatConfidence(confidence)}
        </span>
        <span className={cn('text-meta font-medium', copy.tone)}>{copy.label}</span>
      </div>
      <p className="text-meta muted">{copy.explain}</p>
    </div>
  )
}
