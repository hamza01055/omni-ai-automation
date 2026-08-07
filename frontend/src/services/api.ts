import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { ApiError, AuthSession } from '@/types/domain'

/**
 * One axios instance for the whole app.
 *
 * Tokens live in memory plus localStorage. On a 401 the client refreshes once
 * and replays the original request; concurrent 401s share a single refresh so
 * a burst of requests cannot start a refresh stampede.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const ACCESS_KEY = 'omni.access'
const REFRESH_KEY = 'omni.refresh'

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY)
  },
  set(session: AuthSession) {
    localStorage.setItem(ACCESS_KEY, session.tokens.access_token)
    localStorage.setItem(REFRESH_KEY, session.tokens.refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export const api = axios.create({
  baseURL: `${BASE_URL}/api`,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokens.access
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokens.refresh
  if (!refresh) return null
  try {
    const { data } = await axios.post<AuthSession>(`${BASE_URL}/api/auth/refresh`, {
      refresh_token: refresh,
    })
    tokens.set(data)
    return data.tokens.access_token
  } catch {
    tokens.clear()
    return null
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<{ error?: ApiError }>) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean }
    const isAuthCall = original?.url?.includes('/auth/')

    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true
      refreshing ??= refreshAccessToken().finally(() => {
        refreshing = null
      })
      const fresh = await refreshing
      if (fresh) {
        original.headers.Authorization = `Bearer ${fresh}`
        return api(original)
      }
      // Refresh failed — the session is genuinely over.
      window.dispatchEvent(new CustomEvent('omni:signed-out'))
    }
    return Promise.reject(error)
  },
)

/** Pull the human-readable message out of our error envelope. */
export function errorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.error?.message ?? error.message ?? fallback
  }
  return fallback
}
