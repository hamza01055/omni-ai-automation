# OmniAI Automation

Unified AI automation across WhatsApp, Instagram, Facebook and X. Messages from
every channel arrive in one shape and one queue. The AI answers what it is
confident about and hands a person everything else, with the reason attached.

n8n orchestrates. FastAPI owns the data model, the AI layer and the API. React
provides the console.

---

## Build status

This is built incrementally and the status below is accurate. Nothing is marked
done that has not been implemented and tested.

| Step | Scope | Status |
|------|-------|--------|
| 1 | Docker, Postgres, Redis, FastAPI, React, n8n | **Done** |
| 2 | Authentication and organizations | **Done** |
| 3 | Contacts, conversations, messages | **Done** |
| 4 | Unified message normalization | **Done** |
| 5–8 | Channel adapters (WhatsApp, Instagram, Facebook, X) | **Parsing done and tested. Sending implemented, unverified without credentials.** |
| 9 | Unified inbox UI | API done, UI pending |
| 10 | AI router | **Done** (with offline stub) |
| 11 | RAG | Schema and pgvector index done, pipeline pending |
| 12 | Support agent | Pending |
| 13 | Sales agent and CRM | Schema done, logic pending |
| 14 | Follow-up automation | Schema and guardrails done, workflow pending |
| 15–17 | Content generation, approval, scheduling | Schema done, logic pending |
| 18 | Analytics | Event table done, aggregation pending |
| 19 | Security hardening | Partial — see [Security](#security) |
| 20 | Tests and documentation | 48 tests passing, docs in `docs/` |

**On the channel adapters specifically:** webhook parsing and signature
verification are implemented and unit-tested against captured payloads.
Outbound sending is written against each platform's documented endpoints but
has not been verified end to end, because that requires live Business accounts.
With no credentials configured, adapters return an explicit failure with setup
instructions rather than pretending to succeed. See `docs/integrations.md`.

---

## Quick start

```bash
git clone <your-repo> omni-ai-automation
cd omni-ai-automation

make init          # creates .env with freshly generated secrets
make up            # builds and starts all six services
make migrate       # applies the database schema
make seed          # loads a demo workspace
```

Then:

| Surface | URL |
|---------|-----|
| Console | http://localhost:8080 |
| API docs | http://localhost:8000/docs |
| n8n | http://localhost:5678 |
| Health | http://localhost:8000/health/ready |

Demo credentials after `make seed`: `owner@demo.co` / `OmniDemo!2026`

`make init` generates real values for `JWT_SECRET`, `CREDENTIAL_ENCRYPTION_KEY`,
`INTERNAL_SERVICE_TOKEN`, `N8N_ENCRYPTION_KEY` and the database password. Add
your `OPENAI_API_KEY` to `.env` if you want real classification; without it the
router runs a deterministic keyword stub so the pipeline still works offline.

Run `make help` for the full command list.

---

## It works without any platform credentials

Every channel falls back to a mock adapter when its credentials are absent. The
mock accepts sends, records them, and **labels itself as sandbox** everywhere it
appears — nothing in the dashboard can mistake a mock delivery for a real one.

Exercise the whole pipeline with no Meta or X account:

```bash
curl -X POST http://localhost:5678/webhook/whatsapp \
  -H 'Content-Type: application/json' \
  --data @n8n/test-payloads/whatsapp-text.json
```

That message flows through normalization, storage, AI routing, and either an
automated reply or the approval queue.

---

## Architecture

```
                         React Console
                              │
                       REST / WebSocket
                              │
                              ▼
                       FastAPI Backend ──────────┐
                              │                  │
              ┌───────────────┼──────────┐       │ /api/internal/*
              ▼               ▼          ▼       │  (service token)
         PostgreSQL        Redis     AI Layer    │
         + pgvector        cache     router      ▼
              │                      agents     n8n
              │                      RAG      Orchestrator
              ▼                                  │
          Adapters ◄────────────────────────────┘
              │
     ┌────────┼────────┬────────┐
     ▼        ▼        ▼        ▼
  WhatsApp Instagram Facebook   X
```

The key decision — why n8n calls the backend rather than parsing payloads and
holding credentials itself — is documented in
[ADR-001](docs/adr/ADR-001-orchestration-boundary.md). In short: payload parsing
lives in tested Python, tenant isolation has exactly one implementation, and an
exported workflow JSON contains no secrets.

### The unified message

Every platform payload becomes this before anything else sees it:

```json
{
  "platform": "instagram",
  "external_user_id": "12345",
  "conversation_id": "abc123",
  "external_message_id": "xyz789",
  "sender_name": "Ahmed",
  "text": "What are your prices?",
  "message_type": "text",
  "attachments": [],
  "timestamp": "2026-08-08T01:30:00Z"
}
```

The AI layer never sees a raw platform payload. Adding a fifth channel means
writing one adapter and changing nothing else.

### Idempotency

Meta retries webhooks for roughly 24 hours until it sees a 200. Ingestion is
keyed on `(organization_id, platform, external_message_id)`, so a redelivery
finds the existing row and returns `created: false` — the conversation counter
does not move and no second AI reply fires. WF-01 acknowledges Meta before any
AI call for the same reason.

### Human-in-the-loop

The model classifies. It does not decide policy.

| Confidence | Outcome |
|------------|---------|
| ≥ 0.90 | Answered automatically |
| 0.70–0.89 | Sent, flagged for review |
| < 0.70 | Held for a person |

Refunds, complaints and unrecognised intents go to a person **regardless of
confidence** — the model does not get to overrule that at 0.99. The rule lives
in `apply_escalation_policy()` in `backend/app/ai/router.py` as a pure,
directly-tested function, not in a prompt. If the AI service is unreachable,
routing fails closed: unknown intent, straight to a human.

---

## Repository layout

```
backend/app/
  core/          config, security, logging, db, redis, errors
  models/        SQLAlchemy models (22 entities)
  schemas/       Pydantic request/response shapes
  api/v1/        auth, conversations, internal (n8n-facing)
  ai/            client, router  (agents and RAG land in steps 11–12)
  integrations/  base contract, four adapters, mock, registry
  services/      auth, ingestion
frontend/src/
  components/ui/ design system primitives
  pages/         routes
  hooks/         useAuth, useTheme
  services/      API client with refresh rotation
n8n/
  workflows/     importable JSON (WF-01…04, WF-90)
  test-payloads/ captured payloads in each platform's real shape
docs/
  adr/           architecture decision records
  design-system.md, integrations.md
```

---

## Security

Implemented:

- Argon2id password hashing; timing-equalised login so a missing account and a
  wrong password take the same time
- Short-lived JWT access tokens; refresh tokens rotate on use with a Redis
  denylist and a Postgres audit trail. A replayed token is logged as a probable leak.
- Membership re-checked on every request, so a revoked seat stops working
  immediately rather than at token expiry
- Channel credentials Fernet-encrypted at rest; plaintext never serialized to any response
- Webhook signature verification (Meta HMAC-SHA256, X base64 HMAC) with
  `compare_digest`
- Organization isolation on every query; a wrong-tenant id returns 404,
  indistinguishable from missing
- Structured logging with automatic redaction of any key matching
  password/token/secret/key
- Rate limiting, CORS allowlist, security headers, Pydantic validation on all input
- Production startup **refuses to boot** on unsafe configuration (default JWT
  secret, missing encryption key, wildcard CORS)
- `/api/internal/*` guarded by a service token, not reachable from the browser

Still to do (Step 19): per-tenant credential storage in `channel_credentials`
rather than environment variables, request-id propagation from n8n into backend
logs, and internal API versioning.

---

## Testing

```bash
make test-be          # 48 tests, no containers needed
```

Tests run against SQLite in-memory; `conftest.py` teaches the test dialect to
render JSONB and UUID so the production schema is never weakened for testability.

Coverage today: password hashing and JWT lifecycle, credential encryption,
webhook signature verification (including tampered-body and missing-secret
cases), adapter normalization for all four platforms (text, media, echoes,
comments, malformed payloads), ingestion idempotency and tenant isolation,
status-update ordering, and the escalation policy including its boundaries.

---

## Documentation

| Document | Contents |
|----------|----------|
| [ADR-001](docs/adr/ADR-001-orchestration-boundary.md) | Why the n8n/backend split sits where it does |
| [docs/design-system.md](docs/design-system.md) | Tokens, components, patterns, accessibility |
| [docs/integrations.md](docs/integrations.md) | Exact credential setup per platform |
| [n8n/README.md](n8n/README.md) | Workflow import, webhook URLs, error contract |

---

## Licence

MIT. See [LICENSE](LICENSE).
