# n8n Workflows

n8n is the orchestration layer. It decides *when* things happen and in what
order; the FastAPI backend decides *what* they mean. That split is deliberate
and worth preserving:

- **n8n never holds a platform credential.** Every outbound call goes through
  `/api/internal/*`, and the backend picks the live or mock adapter. If an n8n
  export leaks, no customer token leaks with it.
- **n8n never talks to Postgres directly.** Organization isolation is enforced
  in one place — the backend — not re-implemented in Code nodes.
- **Code nodes are a last resort.** They appear only where declarative nodes
  genuinely can't express the logic (payload classification, error redaction).

## Workflows

| Code | Name | Trigger | Purpose |
|------|------|---------|---------|
| WF-01 | WhatsApp Incoming | Webhook | Ingest, route, answer/qualify/escalate |
| WF-02 | Instagram Incoming | Webhook | Same architecture as WF-01 |
| WF-03 | Facebook Incoming | Webhook | Same architecture as WF-01 |
| WF-04 | X Mentions & DMs | Schedule (5 min) | Poll mentions, reply in-thread |
| WF-90 | Error Handler | Error trigger | Central failure sink for all of the above |

Workflows WF-20 (follow-up), WF-30 (content generation) and WF-40 (scheduled
publishing) arrive with implementation steps 14, 15 and 17.

## Why WF-04 polls instead of receiving webhooks

X's Account Activity API — the push-based product — is gated behind a separate
approval process that most accounts don't have. Rather than ship a webhook
handler that would never fire, WF-04 polls `GET /2/users/:id/mentions` on a
schedule, and the backend keeps the cursor so a missed run catches up instead
of reprocessing. `XAdapter.parse_webhook()` *does* handle Account Activity
payloads, so if you're approved for it, switching is a trigger swap.

## Importing

1. Open n8n at `http://localhost:5678`.
2. **Workflows → Import from File**, select a file from `workflows/`.
3. Import WF-90 first — the others reference it as their error workflow.
4. Activate each workflow.

The workflows read two environment variables, both already set on the n8n
container by `docker-compose.yml`:

- `OMNI_BACKEND_URL` — `http://backend:8000` on the internal network
- `OMNI_INTERNAL_TOKEN` — the shared secret from `INTERNAL_SERVICE_TOKEN`

No n8n credentials need to be configured by hand.

## Webhook URLs

Once activated, each webhook workflow listens at:

```
http://localhost:5678/webhook/whatsapp
http://localhost:5678/webhook/instagram
http://localhost:5678/webhook/facebook
```

For Meta to reach these, they must be publicly resolvable over HTTPS. In
development, tunnel with `ngrok http 5678` and register the tunnel URL as the
callback in the Meta app dashboard. Full setup: `docs/integrations.md`.

## Testing without a platform account

`test-payloads/` holds captured payloads in each platform's real shape. Replay
one against a running stack:

```bash
curl -X POST http://localhost:5678/webhook/whatsapp \
  -H 'Content-Type: application/json' \
  --data @test-payloads/whatsapp-text.json
```

Signature verification is skipped while a channel is in sandbox mode, so this
works with no Meta app configured. `sandbox-message.json` is different — it's
the *internal* unified shape, accepted directly by the mock adapter, useful for
exercising the AI path without caring about platform JSON at all.

## Error handling contract

Every HTTP node that can fail uses `onError: continueErrorOutput` and routes
its error branch to a dead-letter node, which POSTs to
`/api/internal/workflow-runs` with `status: dead_letter`. Retries are set per
node: 3 attempts for ingestion and sending, 2 for AI calls (they're expensive
and a second failure usually means a real problem, not a blip).

WF-90 catches anything that escapes those branches, redacts credentials out of
the error payload, and notifies admins. Failed runs appear on the Workflows
page in the dashboard.
