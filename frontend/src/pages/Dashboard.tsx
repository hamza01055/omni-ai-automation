import { useEffect, useState } from 'react'
import { Activity, CheckCircle2, XCircle } from 'lucide-react'
import { ChannelBadge } from '@/components/ui/ChannelBadge'
import { StatusPill } from '@/components/ui/StatusPill'
import { api } from '@/services/api'
import { PLATFORMS, type Platform } from '@/types/domain'

interface ChannelStatus {
  platform: Platform
  connected: boolean
  mode: 'live' | 'sandbox'
  capabilities: Record<string, boolean>
}

/**
 * The overview answers one question on load: is the machinery actually
 * running, and which channels are real? Metrics come in Step 18; showing
 * invented numbers here would be worse than showing none.
 */
export function Dashboard() {
  const [channels, setChannels] = useState<ChannelStatus[] | null>(null)
  const [health, setHealth] = useState<Record<string, string> | null>(null)

  useEffect(() => {
    const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
    void fetch(`${base}/health/ready`)
      .then((r) => r.json())
      .then((d) => {
        setChannels(d.channels ?? [])
        setHealth(d.checks ?? {})
      })
      .catch(() => setChannels([]))
  }, [])

  return (
    <div className="space-y-6 p-6">
      <section className="space-y-3">
        <p className="eyebrow">Services</p>
        <div className="grid gap-3 sm:grid-cols-3">
          {Object.entries(health ?? { postgres: '…', redis: '…' }).map(([name, state]) => (
            <div key={name} className="surface flex items-center justify-between px-4 py-3">
              <span className="text-sm capitalize">{name}</span>
              {state === 'ok' ? (
                <CheckCircle2 className="h-4 w-4 text-ok" aria-label="Healthy" />
              ) : state === '…' ? (
                <Activity className="h-4 w-4 muted animate-pulse-dot" aria-label="Checking" />
              ) : (
                <XCircle className="h-4 w-4 text-risk" aria-label="Unavailable" />
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <p className="eyebrow">Channels</p>
        <div className="surface divide-y hairline">
          {(channels ?? PLATFORMS.map((p) => ({
            platform: p, connected: false, mode: 'sandbox' as const, capabilities: {},
          }))).map((channel) => (
            <div key={channel.platform} className="flex items-center justify-between px-4 py-3">
              <ChannelBadge platform={channel.platform} live={channel.connected} />
              <StatusPill tone={channel.connected ? 'ok' : 'neutral'}>
                {channel.mode}
              </StatusPill>
            </div>
          ))}
        </div>
        <p className="text-meta muted">
          Sandbox channels run against the mock adapter — messages flow through the
          full pipeline but nothing leaves this machine. Add credentials in Settings
          to switch a channel to live.
        </p>
      </section>
    </div>
  )
}
