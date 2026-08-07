import type { Intent } from '@/types/domain'

/**
 * The three-band confidence policy from the spec, in one place.
 * The backend enforces it; this mirrors it so the UI can explain the
 * decision rather than just displaying a number.
 */
export const AUTO_THRESHOLD = 0.9
export const REVIEW_THRESHOLD = 0.7

export type Band = 'auto' | 'review' | 'human'

/** Intents that go to a person regardless of how sure the model is. */
export const ALWAYS_ESCALATE: Intent[] = ['refund', 'complaint', 'unknown']

export function band(confidence: number | null | undefined, intent?: Intent | null): Band {
  if (intent && ALWAYS_ESCALATE.includes(intent)) return 'human'
  if (confidence == null) return 'human'
  if (confidence >= AUTO_THRESHOLD) return 'auto'
  if (confidence >= REVIEW_THRESHOLD) return 'review'
  return 'human'
}

export const BAND_COPY: Record<Band, { label: string; explain: string; tone: string }> = {
  auto: {
    label: 'Answered automatically',
    explain: 'Confidence is above 0.90, so the reply was sent without waiting.',
    tone: 'text-ok',
  },
  review: {
    label: 'Review recommended',
    explain: 'Confidence is between 0.70 and 0.89. The reply was sent, but it is worth a look.',
    tone: 'text-signal',
  },
  human: {
    label: 'Needs a person',
    explain: 'Either confidence is below 0.70 or the topic always goes to a human.',
    tone: 'text-risk',
  },
}

export function formatConfidence(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(2)
}
