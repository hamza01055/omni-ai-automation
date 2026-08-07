import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, errorMessage, tokens } from '@/services/api'
import type { AuthSession, OrganizationSummary, Role, UserProfile } from '@/types/domain'

interface AuthState {
  user: UserProfile | null
  organization: OrganizationSummary | null
  organizations: OrganizationSummary[]
  role: Role | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (input: SignUpInput) => Promise<void>
  signOut: () => Promise<void>
  switchOrganization: (id: string) => Promise<void>
}

interface SignUpInput {
  email: string
  password: string
  full_name: string
  organization_name: string
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [organization, setOrganization] = useState<OrganizationSummary | null>(null)
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([])
  const [role, setRole] = useState<Role | null>(null)
  const [loading, setLoading] = useState(true)

  const apply = useCallback((session: AuthSession) => {
    tokens.set(session)
    setUser(session.user)
    setOrganization(session.organization)
    setOrganizations(session.organizations)
    setRole(session.role)
  }, [])

  const clear = useCallback(() => {
    tokens.clear()
    setUser(null)
    setOrganization(null)
    setOrganizations([])
    setRole(null)
  }, [])

  // Restore the session on load so a refresh doesn't sign the person out.
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!tokens.access) {
        setLoading(false)
        return
      }
      try {
        const { data } = await api.get('/auth/me')
        if (cancelled) return
        setUser(data.user)
        setOrganization(data.organization)
        setOrganizations(data.organizations)
        setRole(data.role)
      } catch {
        if (!cancelled) clear()
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [clear])

  // The api layer emits this when a refresh fails mid-session.
  useEffect(() => {
    const onSignedOut = () => clear()
    window.addEventListener('omni:signed-out', onSignedOut)
    return () => window.removeEventListener('omni:signed-out', onSignedOut)
  }, [clear])

  const signIn = useCallback(
    async (email: string, password: string) => {
      try {
        const { data } = await api.post<AuthSession>('/auth/login', { email, password })
        apply(data)
      } catch (error) {
        throw new Error(errorMessage(error, 'Could not sign in.'))
      }
    },
    [apply],
  )

  const signUp = useCallback(
    async (input: SignUpInput) => {
      try {
        const { data } = await api.post<AuthSession>('/auth/register', input)
        apply(data)
      } catch (error) {
        throw new Error(errorMessage(error, 'Could not create the workspace.'))
      }
    },
    [apply],
  )

  const signOut = useCallback(async () => {
    const refresh = tokens.refresh
    clear()
    if (refresh) {
      // Best effort: the local session is already gone either way.
      await api.post('/auth/logout', { refresh_token: refresh }).catch(() => undefined)
    }
  }, [clear])

  const switchOrganization = useCallback(
    async (id: string) => {
      const { data } = await api.post<AuthSession>(`/auth/switch/${id}`)
      apply(data)
    },
    [apply],
  )

  const value = useMemo<AuthState>(
    () => ({
      user, organization, organizations, role, loading,
      signIn, signUp, signOut, switchOrganization,
    }),
    [user, organization, organizations, role, loading, signIn, signUp, signOut, switchOrganization],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>.')
  return ctx
}
