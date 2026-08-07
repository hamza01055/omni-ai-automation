import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Field } from '@/components/ui/Field'
import { useAuth } from '@/hooks/useAuth'
import { PLATFORM_LABEL, PLATFORMS } from '@/types/domain'
import { cn } from '@/utils/cn'

/**
 * The sign-in screen states what the product does before asking for anything:
 * four channels, one queue. The channel row on the left is the same colour
 * encoding used throughout the console, so the vocabulary starts here.
 */
export function Login() {
  const { user, signIn, signUp } = useAuth()
  const location = useLocation()
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (user) {
    const from = (location.state as { from?: { pathname: string } })?.from?.pathname
    return <Navigate to={from ?? '/inbox'} replace />
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    const data = new FormData(event.currentTarget)
    try {
      if (mode === 'signin') {
        await signIn(String(data.get('email')), String(data.get('password')))
      } else {
        await signUp({
          email: String(data.get('email')),
          password: String(data.get('password')),
          full_name: String(data.get('full_name')),
          organization_name: String(data.get('organization_name')),
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* Left: what this is. */}
      <aside className="hidden flex-col justify-between p-12 lg:flex bg-ink-900">
        <div className="flex items-center gap-2.5">
          <img src="/mark.svg" alt="" className="h-8 w-8" />
          <span className="font-display text-sm font-bold tracking-tight text-ink-50">
            OmniAI
          </span>
        </div>

        <div className="max-w-md space-y-6">
          <h2 className="font-display text-3xl font-bold leading-tight tracking-tight text-ink-50">
            Four inboxes.
            <br />
            One queue.
            <br />
            <span className="text-signal">One decision at a time.</span>
          </h2>
          <p className="text-sm leading-relaxed text-ink-300">
            Messages from every channel arrive in the same shape. The AI answers
            what it is sure about, and hands you everything else with the reason
            attached.
          </p>

          <ul className="space-y-2 pt-2">
            {PLATFORMS.map((platform) => (
              <li key={platform} className="flex items-center gap-2.5">
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    platform === 'whatsapp' && 'bg-channel-whatsapp',
                    platform === 'instagram' && 'bg-channel-instagram',
                    platform === 'facebook' && 'bg-channel-facebook',
                    platform === 'x' && 'bg-channel-x',
                  )}
                  aria-hidden
                />
                <span className="font-mono text-meta text-ink-300">
                  {PLATFORM_LABEL[platform]}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="font-mono text-micro text-ink-500">
          Official platform APIs only. No scraping.
        </p>
      </aside>

      {/* Right: the form. */}
      <main className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm space-y-7 animate-slide-up">
          <div className="space-y-1.5">
            <h1 className="font-display text-xl font-semibold">
              {mode === 'signin' ? 'Sign in' : 'Create a workspace'}
            </h1>
            <p className="text-sm muted">
              {mode === 'signin'
                ? 'Pick up where your team left off.'
                : 'You will be the owner and can invite the rest of your team after.'}
            </p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            {mode === 'signup' && (
              <>
                <Field label="Your name" name="full_name" autoComplete="name" required />
                <Field
                  label="Workspace name"
                  name="organization_name"
                  hint="Usually your company or brand."
                  required
                />
              </>
            )}

            <Field
              label="Email"
              name="email"
              type="email"
              autoComplete="email"
              required
              placeholder="you@company.com"
            />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              required
              hint={mode === 'signup' ? 'At least 12 characters, mixing letters and numbers.' : undefined}
            />

            {error && (
              <p role="alert" className="rounded-control bg-risk/10 px-3 py-2 text-meta text-risk">
                {error}
              </p>
            )}

            <Button type="submit" variant="primary" size="lg" loading={busy} className="w-full">
              {mode === 'signin' ? 'Sign in' : 'Create workspace'}
            </Button>
          </form>

          <p className="text-meta muted">
            {mode === 'signin' ? "Don't have a workspace yet? " : 'Already have one? '}
            <button
              type="button"
              onClick={() => {
                setMode(mode === 'signin' ? 'signup' : 'signin')
                setError(null)
              }}
              className="font-medium text-signal underline-offset-2 hover:underline"
            >
              {mode === 'signin' ? 'Create one' : 'Sign in'}
            </button>
          </p>
        </div>
      </main>
    </div>
  )
}
