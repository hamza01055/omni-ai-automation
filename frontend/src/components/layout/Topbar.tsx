import { Moon, Sun, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'

export function Topbar({ title }: { title: string }) {
  const { user, organization, signOut } = useAuth()
  const { theme, toggle } = useTheme()

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b hairline px-5">
      <div className="min-w-0">
        <h1 className="truncate font-display text-base font-semibold">{title}</h1>
        {organization && <p className="text-micro muted">{organization.name}</p>}
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={toggle}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        <div className="hidden text-right sm:block">
          <p className="text-meta font-medium">{user?.full_name}</p>
          <p className="text-micro muted">{user?.email}</p>
        </div>

        <Button variant="ghost" size="sm" onClick={() => void signOut()} aria-label="Sign out">
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
