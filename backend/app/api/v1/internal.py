"""Internal API — the surface n8n calls.

Everything here is guarded by ``require_internal_service`` (a shared bearer
token on the private Docker network) rather than a user session. These routes
are deliberately *not* reachable from the browser: CORS does not list them, and
nginx does not proxy them from the public path.

Why the backend and not n8n does the parsing: signature verification, adapter
selection, credential decryption and tenant isolation all live in one place.
n8n orchestrates; it never holds a platform token and never touches Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.ai.router import AIRouter
from app.api.deps import DbDep, require_internal_service
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger, organization_id_ctx, request_id_ctx
from app.integrations.base import OutboundMessage
from app.integrations.registry import get_adapter
from app.models import (
    AuditLog, Channel, Conversation, Message, Organization, Workflow, WorkflowRun,
)
from app.models.enums import MessageStatus, Platform, RunStatus, SenderType
from app.schemas.common import Ack
from app.schemas.messaging import (
    InternalIngestResult, InternalRouteRequest, InternalSendRequest, InternalWorkflowRun,
)
from app.services.ingestion import IngestionService

log = get_logger("api.internal")

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_service)],
    include_in_schema=True,
)


async def _resolve_organization(db: DbDep, platform: Platform,
                                explicit: uuid.UUID | None = None) -> uuid.UUID:
    """Work out which tenant a webhook belongs to.

    Single-tenant deployments have one organization and this is trivial. For
    multi-tenant, the channel row keyed by the platform's account id is the
    lookup — which is why ``channels.external_account_id`` is unique per
    organization. Until per-tenant channel provisioning lands (Step 5), this
    falls back to the single active organization and refuses to guess if there
    is more than one.
    """
    if explicit is not None:
        return explicit

    channel = await db.scalar(
        select(Channel).where(Channel.platform == platform, Channel.is_active.is_(True))
    )
    if channel is not None:
        return channel.organization_id

    orgs = (await db.execute(
        select(Organization.id).where(Organization.is_active.is_(True)).limit(2)
    )).scalars().all()

    if len(orgs) == 1:
        return orgs[0]
    if not orgs:
        raise NotFoundError("No active organization exists to receive this webhook.")
    raise AppError(
        "Several organizations exist but no channel is registered for this platform. "
        "Connect the channel in Settings so inbound messages can be attributed.",
        code="ambiguous_tenant",
    )


# ── Webhook ingestion ────────────────────────────────────────────────────


@router.get("/webhooks/{platform}", include_in_schema=False)
async def verify_webhook(platform: str, request: Request) -> Response:
    """Meta's GET subscription handshake, and X's CRC challenge.

    Meta expects the raw challenge string as the body with a 200. Anything
    else — including a JSON-wrapped version of the right value — fails
    verification.
    """
    try:
        plat = Platform(platform.lower())
    except ValueError:
        return Response("Unknown platform", status_code=status.HTTP_404_NOT_FOUND)

    adapter = get_adapter(plat)
    echo = adapter.verify_challenge(dict(request.query_params))
    if echo is None:
        log.warning("webhook_verification_failed", platform=platform)
        return Response("Verification failed", status_code=status.HTTP_403_FORBIDDEN)

    log.info("webhook_verified", platform=platform)
    return Response(echo, media_type="text/plain")


@router.post("/webhooks/{platform}", response_model=list[InternalIngestResult])
async def ingest_webhook(
    platform: str,
    request: Request,
    db: DbDep,
    organization_id: uuid.UUID | None = None,
) -> list[InternalIngestResult]:
    """Verify, normalize and store an inbound webhook payload.

    Returns one result per message. Duplicates come back with
    ``created: false`` so the calling workflow can stop rather than replying
    to the same customer twice.
    """
    try:
        plat = Platform(platform.lower())
    except ValueError as exc:
        raise NotFoundError(f"Unknown platform '{platform}'.") from exc

    raw_body = await request.body()
    adapter = get_adapter(plat)

    headers = {k.lower(): v for k, v in request.headers.items()}
    if adapter.is_live and not adapter.verify_signature(raw_body, headers):
        # Do not say which check failed: that is a probing oracle.
        log.warning("webhook_signature_rejected", platform=platform)
        raise AppError("Payload could not be verified.", code="invalid_signature")

    payload: dict[str, Any] = await request.json()
    org_id = await _resolve_organization(db, plat, organization_id)
    organization_id_ctx.set(str(org_id))

    service = IngestionService(db, org_id)

    # Delivery receipts ride the same webhook; fold them in and move on.
    updates = adapter.parse_status_updates(payload)
    if updates:
        applied = await service.apply_status_updates(updates)
        log.info("status_updates_applied", platform=platform, count=applied)

    unified = adapter.parse_webhook(payload)
    if not unified:
        return []

    results = await service.ingest_many(unified)
    return [InternalIngestResult(**r.as_dict()) for r in results]


@router.post("/webhooks/{platform}/status", response_model=Ack)
async def ingest_status(platform: str, request: Request, db: DbDep) -> Ack:
    plat = Platform(platform.lower())
    adapter = get_adapter(plat)
    payload = await request.json()
    org_id = await _resolve_organization(db, plat)
    applied = await IngestionService(db, org_id).apply_status_updates(
        adapter.parse_status_updates(payload)
    )
    return Ack(message=f"Applied {applied} status update(s).")


# ── AI ───────────────────────────────────────────────────────────────────


@router.post("/ai/route")
async def route_message(body: InternalRouteRequest, db: DbDep) -> dict[str, Any]:
    """Classify a stored message and decide whether a person is needed."""
    organization_id_ctx.set(str(body.organization_id))

    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == body.conversation_id,
            Conversation.organization_id == body.organization_id,
        )
    )
    message = await db.scalar(
        select(Message).where(
            Message.id == body.message_id,
            Message.organization_id == body.organization_id,
        )
    )
    if conversation is None or message is None:
        raise NotFoundError("Conversation or message not found in this organization.")

    # An operator who turned AI off for this thread outranks the router.
    if not conversation.ai_enabled:
        return {
            "intent": "unknown", "confidence": 0.0, "action": "escalate",
            "lead_score": 0, "needs_human": True,
            "escalation_reason": "Automation is switched off for this conversation.",
            "conversation_id": str(conversation.id), "message_id": str(message.id),
            "organization_id": str(body.organization_id),
        }

    decision = await AIRouter(db, body.organization_id).route(
        conversation=conversation, message=message
    )
    return {
        **decision.as_dict(),
        "conversation_id": str(conversation.id),
        "message_id": str(message.id),
        "organization_id": str(body.organization_id),
    }


# ── Outbound ─────────────────────────────────────────────────────────────


@router.post("/messages/send")
async def send_message(body: InternalSendRequest, db: DbDep) -> dict[str, Any]:
    """Deliver a message and record it, whichever adapter is active."""
    organization_id_ctx.set(str(body.organization_id))

    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == body.conversation_id,
            Conversation.organization_id == body.organization_id,
        )
    )
    if conversation is None:
        raise NotFoundError("Conversation not found.")

    contact = conversation.contact if hasattr(conversation, "contact") else None
    if contact is None:
        from app.models import Contact
        contact = await db.get(Contact, conversation.contact_id)
    if contact is None:
        raise NotFoundError("Contact not found.")

    # Honour opt-out even for a reply the AI already composed.
    if contact.opted_out_at is not None:
        raise AppError(
            "This contact has opted out of messages.", code="contact_opted_out"
        )

    adapter = get_adapter(conversation.platform)
    receipt = await adapter.send_message(
        OutboundMessage(
            platform=conversation.platform,
            recipient_id=contact.external_user_id,
            conversation_id=conversation.external_conversation_id,
            text=body.text,
        )
    )

    service = IngestionService(db, body.organization_id)
    message = await service.record_outbound(
        conversation=conversation,
        text=body.text,
        sender_type=body.sender_type,
        sender_name="OmniAI" if body.sender_type is SenderType.AI else None,
        external_message_id=receipt.external_message_id,
        status=MessageStatus.SENT if receipt.accepted else MessageStatus.FAILED,
        confidence=body.confidence,
        ai_run_id=body.ai_run_id,
        error=receipt.error,
    )

    if not receipt.accepted:
        log.error("outbound_send_failed", platform=conversation.platform.value,
                  error=receipt.error)

    return {
        "accepted": receipt.accepted,
        "message_id": str(message.id),
        "external_message_id": receipt.external_message_id,
        "delivery_mode": "live" if adapter.is_live else "sandbox",
        "error": receipt.error,
    }


# ── Observability ────────────────────────────────────────────────────────


@router.post("/workflow-runs", response_model=Ack, status_code=status.HTTP_201_CREATED)
async def record_workflow_run(body: InternalWorkflowRun, db: DbDep) -> Ack:
    """Record a workflow outcome. Dead-letter and error nodes call this."""
    org_id = body.organization_id
    if org_id is None:
        orgs = (await db.execute(select(Organization.id).limit(1))).scalars().all()
        if not orgs:
            raise NotFoundError("No organization to attribute this run to.")
        org_id = orgs[0]

    try:
        run_status = RunStatus(body.status)
    except ValueError:
        run_status = RunStatus.FAILED

    workflow = await db.scalar(
        select(Workflow).where(
            Workflow.organization_id == org_id, Workflow.code == body.workflow_code
        )
    )

    db.add(WorkflowRun(
        organization_id=org_id,
        workflow_id=workflow.id if workflow else None,
        workflow_code=body.workflow_code,
        n8n_execution_id=body.n8n_execution_id,
        idempotency_key=body.idempotency_key,
        platform=body.platform,
        status=run_status,
        duration_ms=body.duration_ms,
        error=body.error,
        input_payload=body.input_payload,
        output_payload=body.output_payload,
        finished_at=datetime.now(UTC),
    ))

    if workflow is not None:
        workflow.last_run_at = datetime.now(UTC)
        if run_status is RunStatus.SUCCESS:
            workflow.success_count += 1
        elif run_status in (RunStatus.FAILED, RunStatus.DEAD_LETTER):
            workflow.failure_count += 1

    if run_status in (RunStatus.FAILED, RunStatus.DEAD_LETTER):
        db.add(AuditLog(
            organization_id=org_id,
            actor_type="system",
            action="workflow.failed",
            resource_type="workflow_run",
            resource_id=body.n8n_execution_id,
            request_id=request_id_ctx.get(),
            changes={"workflow": body.workflow_code, "node": body.failed_node,
                     "error": (body.error or "")[:500]},
        ))
        log.error("workflow_failed", workflow=body.workflow_code,
                  node=body.failed_node, execution=body.n8n_execution_id)

    return Ack(message="Run recorded.")


InternalGuard = Annotated[None, Depends(require_internal_service)]
