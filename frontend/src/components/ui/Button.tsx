import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/utils/cn'

/**
 * Variants:
 *   primary   the one action that moves the task forward
 *   secondary supporting actions of equal weight to each other
 *   ghost     low-emphasis, sits inside dense surfaces
 *   danger    destructive or irreversible
 *
 * A loading button keeps its label and its width, so the layout does not
 * jump and the person can still read what they triggered.
 */

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-signal text-ink-950 font-semibold hover:bg-signal-soft active:bg-signal ' +
    'disabled:bg-signal/40 disabled:text-ink-950/60',
  secondary:
    'border hairline bg-transparent hover:bg-ink-100/60 dark:hover:bg-ink-800 ' +
    'disabled:opacity-50',
  ghost: 'bg-transparent hover:bg-ink-100/60 dark:hover:bg-ink-800 disabled:opacity-50',
  danger: 'bg-risk text-white font-semibold hover:bg-risk/90 disabled:bg-risk/40',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-meta gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'secondary', size = 'md', loading, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center rounded-control transition',
        'disabled:cursor-not-allowed',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})
