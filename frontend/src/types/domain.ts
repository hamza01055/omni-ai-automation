/**
 * Mirrors backend/app/models/enums.py. Keep both sides in step —
 * the backend is the source of truth.
 */

export const PLATFORMS = ['whatsapp', 'instagram', 'facebook', 'x'] as const
export type Platform = (typeof PLATFORMS)[number]

export type Role = 'owner' | 'admin' | 'manager' | 'agent' | 'viewer'

export type Intent =
  | 'support' | 'pricing' | 'product_question' | 'purchase_intent'
  | 'lead_generation' | 'complaint' | 'refund' | 'booking'
  | 'general' | 'spam' | 'unknown'

export type ConversationStatus = 'open' | 'pending_human' | 'snoozed' | 'closed'
export type LeadStatus = 'new' | 'qualified' | 'contacted' | 'meeting' | 'won' | 'lost'
export type SenderType = 'contact' | 'ai' | 'human' | 'system'
export type ContentStatus =
  | 'draft' | 'pending_review' | 'approved' | 'scheduled'
  | 'publishing' | 'published' | 'failed' | 'rejected'

export const PLATFORM_LABEL: Record<Platform, string> = {
  whatsapp: 'WhatsApp',
  instagram: 'Instagram',
  facebook: 'Facebook',
  x: 'X',
}

/** Tailwind classes per channel, so the colour lives in exactly one place. */
export const PLATFORM_STYLE: Record<Platform, { dot: string; text: string; ring: string }> = {
  whatsapp: { dot: 'bg-channel-whatsapp', text: 'text-channel-whatsapp', ring: 'ring-channel-whatsapp/30' },
  instagram: { dot: 'bg-channel-instagram', text: 'text-channel-instagram', ring: 'ring-channel-instagram/30' },
  facebook: { dot: 'bg-channel-facebook', text: 'text-channel-facebook', ring: 'ring-channel-facebook/30' },
  x: { dot: 'bg-channel-x', text: 'text-channel-x', ring: 'ring-channel-x/30' },
}

export interface UserProfile {
  id: string
  email: string
  full_name: string
  avatar_url?: string | null
  last_login_at?: string | null
}

export interface OrganizationSummary {
  id: string
  name: string
  slug: string
  role?: Role | null
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_at: string
}

export interface AuthSession {
  tokens: TokenPair
  user: UserProfile
  organization: OrganizationSummary
  role: Role
  organizations: OrganizationSummary[]
}

export interface ApiError {
  code: string
  message: string
  request_id?: string
  details?: unknown
}
