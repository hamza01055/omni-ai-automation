# ADR-001: Where the orchestration boundary sits between n8n and FastAPI

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Platform architecture
**Supersedes:** —

## Context

The brief mandates n8n as "the primary workflow orchestration layer" and
FastAPI as the backend API. Both statements are satisfiable by wildly different
architectures, and the choice determines almost everything downstream: where
credentials live, how tenant isolation is enforced, how much of the system is
testable, and what happens when a platform changes its payload shape.

Forces in play:

- **Meta retries webhooks for ~24 hours** on any non-200 response. Anything
  slow in the ingest path turns into duplicate deliveries.
- **Four platforms, four payload shapes**, each of which will change without
  warning. Instagram alone has two unrelated event shapes (`messaging` for DMs,
  `changes` for comments).
- **Organization isolation is a security boundary**, not a convenience. Every
  query that forgets `organization_id` is a cross-tenant data leak.
- **n8n workflows are exported as JSON** and checked into the repository.
  Anything embedded in them is effectively public to everyone with repo access.
- The team needs to **extend this system without an n8n expert on hand** for
  every change.

## Decision

n8n owns *sequencing, scheduling, retry, and branching*. The FastAPI backend
owns *meaning*: payload parsing, credential custody, tenant resolution, AI
invocation, and all database access.

Concretely: n8n calls `/api/internal/*` over the private Docker network with a
shared bearer token. It never holds a platform credential, never talks to
Postgres, and Code nodes appear only where declarative nodes genuinely cannot
express the logic (payload classification in WF-01, error redaction in WF-90).

## Options considered

### Option A: n8n as a thin trigger, backend does everything

n8n receives the webhook and immediately forwards the raw body to the backend,
which runs the whole pipeline synchronously.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Testability | High — everything is Python |
| Visibility | Poor — the workflow page shows one opaque box |
| Fit with brief | Weak — n8n is not meaningfully orchestrating |

**Pros:** Simplest to reason about. All logic in one language with one test suite.
**Cons:** Reduces n8n to a webhook proxy, which contradicts the brief. Loses per-step retry, per-step visibility, and the ability for a non-engineer to change routing. A slow AI call blocks the webhook acknowledgement.

### Option B: n8n does the work, backend is a CRUD API

n8n parses platform payloads in Code nodes, calls OpenAI directly with n8n
credentials, and writes to Postgres via the Postgres node.

| Dimension | Assessment |
|-----------|------------|
| Complexity | High and *distributed* |
| Testability | Very poor — logic lives in JSON string fields |
| Security | Poor — credentials in n8n, tenant filtering in Code nodes |
| Fit with brief | Superficially strong |

**Pros:** Maximally "n8n-first". Visual, and every step is individually retryable.
**Cons:** Payload parsing lives in unversioned JavaScript strings inside JSON — unlintable, untestable, and invisible to code review. Organization isolation would be re-implemented per Code node, which is exactly the shape of bug that leaks tenant data. Platform tokens sit in n8n credentials, and a workflow export leaks them. When Instagram changes its payload, the fix is in four places.

### Option C: Split by concern — n8n sequences, backend interprets

The chosen option.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Testability | High — parsing and policy are Python, tested |
| Security | Strong — single credential custodian, single isolation point |
| Fit with brief | Strong — n8n owns real orchestration |

**Pros:** Adapters are unit-tested against captured payloads. Tenant isolation has one implementation. n8n retains genuine orchestration: retry counts, branch conditions, schedules, and dead-lettering are all visible and editable without touching Python. A workflow export contains no secrets.
**Cons:** Two systems to run and reason about. Debugging crosses a process boundary. Requires the discipline to keep business logic out of Code nodes.

## Trade-off analysis

The decisive factor is **where a mistake becomes a security incident rather than
a bug**. Options A and C both keep tenant filtering in one tested place. Option B
spreads it across Code nodes where a missing `WHERE organization_id = ...`
produces a cross-tenant leak that no test would catch — and n8n has no unit test
story for Code nodes at all.

The second factor is **credential blast radius**. Under Option B, `n8n/workflows/*.json`
in version control is a credential-adjacent artifact forever. Under Option C it is
inert configuration that can be shared freely.

Against Option A, the argument is weaker but still holds: acknowledging Meta's
webhook in under a second is a hard requirement, and doing it in n8n (WF-01's
`Ack 200 Immediately` node fires before any AI call) is cleaner than building
background task handling into FastAPI. Per-node retry configuration and the
dead-letter convergence pattern are things n8n does well and that would be
custom code otherwise.

The cost accepted is cross-process debugging. It is mitigated by propagating a
request id from n8n through the backend into structured logs, so one automation
run is traceable end to end.

## Consequences

**Easier:**
- Adding a fifth channel: write one adapter, add one workflow, change nothing else.
- Changing routing behaviour without a Python deploy — it is a branch condition in n8n.
- Auditing security: credential handling and tenant filtering each have one home.
- Testing: 48 tests run in seconds with no containers.

**Harder:**
- Tracing a failure requires reading both n8n execution history and backend logs.
- The `/api/internal/*` contract is now a real interface with compatibility obligations. Changing a field breaks workflows silently.
- Local development needs the full Compose stack for end-to-end work.

**To revisit:**
- If `/api/internal/*` drifts far enough that workflows break on backend deploys, it needs explicit versioning (`/api/internal/v1/`).
- The shared bearer token is appropriate for a private network. Public n8n exposure would require mTLS or signed requests.
- Tenant resolution currently falls back to "the single active organization" and refuses to guess when several exist. Real multi-tenancy needs channel-based resolution keyed on `channels.external_account_id` (Step 5).

## Action items

1. [x] Define the `/api/internal/*` contract and guard it with a service token
2. [x] Move all payload parsing into tested Python adapters
3. [x] Establish the dead-letter convergence pattern in WF-01, propagate to WF-02/03/04
4. [x] Enforce the escalation policy in Python, not in a prompt
5. [ ] Propagate the n8n execution id into backend logs as `workflow_run_id` (Step 19)
6. [ ] Version the internal API once a second consumer exists
7. [ ] Replace the single-organization fallback with channel-based tenant resolution (Step 5)
