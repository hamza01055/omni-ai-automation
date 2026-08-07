import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/utils/cn'

/**
 * A labelled input. The label is always present (never a placeholder standing
 * in for one), errors are announced, and the hint explains the constraint
 * before the person hits it rather than after.
 */

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: string
  error?: string | null
  trailing?: ReactNode
}

export const Field = forwardRef<HTMLInputElement, Props>(function Field(
  { label, hint, error, trailing, className, id, ...rest },
  ref,
) {
  const generated = useId()
  const inputId = id ?? generated
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined

  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="block text-meta font-medium">
        {label}
      </label>
      <div className="relative">
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(
            'h-10 w-full rounded-control border bg-transparent px-3 text-sm transition',
            'placeholder:text-ink-400',
            error ? 'border-risk' : 'hairline focus:border-signal',
            trailing && 'pr-10',
            className,
          )}
          {...rest}
        />
        {trailing && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2">{trailing}</span>
        )}
      </div>
      {error ? (
        <p id={`${inputId}-error`} role="alert" className="text-meta text-risk">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-meta muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
})
