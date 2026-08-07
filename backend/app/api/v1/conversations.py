"""Unified inbox: conversations, messages, and human replies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserDep, DbDep
from app.core.errors import AppError, NotFoundError
from app.integrations.base import OutboundMessage
from app.integrations.registry import get_adapter
from app.models import Contact, Conversation, Lead, Message
from app.models.enums import (
    ConversationStatus, MessageStatus, Platform, Role, SenderType,
)
from app.schemas.common import Page
from app.schemas.messaging import (
    ContactOut, ConversationDetail, ConversationOut, ConversationPatch,
    MessageOut, ReplyRequest,
)
from app.services.ingestion import IngestionService

router = APIRouter(tags=["inbox"])


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    user: CurrentUserDep,
    db: DbDep,
    platform: Platform | None = None,
    status: ConversationStatus | None = None,
    assigned_to_me: bool = False,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ConversationOut]:
    """The inbox list. Always scoped to the caller's organization."""
    base = (
        select(Conversation)
        .where(Conversation.organization_id == user.organization_id)
        .options(selectinload(Conversation.contact))
    )
    if platform:
        base = base.where(Conversation.platform == platform)
    if status:
        base = base.where(Conversation.status == status)
    if assigned_to_me:
        base = base.where(Conversation.assigned_user_id == user.id)
    if search:
        base = base.join(Contact, Contact.id == Conversation.contact_id).where(
            Contact.display_name.ilike(f"%{search}%")
        )

    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    ) or 0

    rows = await db.execute(
        base.order_by(desc(Conversation.last_message_at)).limit(limit).offset(offset)
    )
    conversations = list(rows.scalars().all())

    # One extra query each for previews and lead scores, rather than N+1.
    previews = await _last_message_previews(db, [c.id for c in conversations])
    scores = await _lead_scores(db, user.organization_id,
                               [c.contact_id for c in conversations])

    items = []
    for conversation in conversations:
        out = ConversationOut.model_validate(conversation)
        out.last_message_preview = previews.get(conversation.id)
        out.lead_score = scores.get(conversation.contact_id)
        items.append(out)

    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> ConversationDetail:
    conversation = await _load(db, conversation_id, user.organization_id)

    rows = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .options(selectinload(Message.attachments))
        .order_by(desc(Message.sent_at))
        .limit(limit)
    )
    messages = list(reversed(rows.scalars().all()))

    # Opening a conversation is what marks it read.
    conversation.unread_count = 0

    detail = ConversationDetail.model_validate(conversation)
    detail.messages = [MessageOut.model_validate(m) for m in messages]
    return detail


@router.post("/conversations/{conversation_id}/reply", response_model=MessageOut)
async def reply(
    conversation_id: uuid.UUID,
    body: ReplyRequest,
    user: CurrentUserDep,
    db: DbDep,
) -> MessageOut:
    """Send a reply as the signed-in person."""
    user.require(Role.AGENT)
    conversation = await _load(db, conversation_id, user.organization_id)

    contact = await db.get(Contact, conversation.contact_id)
    if contact is None:
        raise NotFoundError("Contact not found.")
    if contact.opted_out_at is not None:
        raise AppError("This contact has opted out of messages.",
                       code="contact_opted_out")

    adapter = get_adapter(conversation.platform)
    receipt = await adapter.send_message(
        OutboundMessage(
            platform=conversation.platform,
            recipient_id=contact.external_user_id,
            conversation_id=conversation.external_conversation_id,
            text=body.text,
        )
    )

    message = await IngestionService(db, user.organization_id).record_outbound(
        conversation=conversation,
        text=body.text,
        sender_type=SenderType.HUMAN,
        sender_user_id=user.id,
        sender_name=user.full_name,
        external_message_id=receipt.external_message_id,
        status=MessageStatus.SENT if receipt.accepted else MessageStatus.FAILED,
        error=receipt.error,
    )

    # A person stepping in takes the conversation off the pending queue.
    if conversation.status is ConversationStatus.PENDING_HUMAN:
        conversation.status = ConversationStatus.OPEN

    return MessageOut.model_validate(message)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatch,
    user: CurrentUserDep,
    db: DbDep,
) -> ConversationOut:
    user.require(Role.AGENT)
    conversation = await _load(db, conversation_id, user.organization_id)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(conversation, field, value)

    return ConversationOut.model_validate(conversation)


@router.get("/contacts", response_model=Page[ContactOut])
async def list_contacts(
    user: CurrentUserDep,
    db: DbDep,
    platform: Platform | None = None,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ContactOut]:
    base = select(Contact).where(
        Contact.organization_id == user.organization_id,
        Contact.merged_into_id.is_(None),
    )
    if platform:
        base = base.where(Contact.platform == platform)
    if search:
        base = base.where(Contact.display_name.ilike(f"%{search}%"))

    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    ) or 0
    rows = await db.execute(
        base.order_by(desc(Contact.created_at)).limit(limit).offset(offset)
    )
    return Page(
        items=[ContactOut.model_validate(c) for c in rows.scalars().all()],
        total=total, limit=limit, offset=offset,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


async def _load(db, conversation_id: uuid.UUID, org_id: uuid.UUID) -> Conversation:
    """Load a conversation, or 404. The org filter is the isolation boundary —
    a wrong-tenant id is indistinguishable from a missing one, by design."""
    conversation = await db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id,
               Conversation.organization_id == org_id)
        .options(selectinload(Conversation.contact))
    )
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


async def _last_message_previews(db, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    newest = (
        select(Message.conversation_id, func.max(Message.sent_at).label("at"))
        .where(Message.conversation_id.in_(ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    rows = await db.execute(
        select(Message.conversation_id, Message.text)
        .join(newest, (Message.conversation_id == newest.c.conversation_id)
              & (Message.sent_at == newest.c.at))
    )
    return {cid: (text or "")[:140] for cid, text in rows.all()}


async def _lead_scores(db, org_id: uuid.UUID,
                       contact_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not contact_ids:
        return {}
    rows = await db.execute(
        select(Lead.contact_id, Lead.score).where(
            Lead.organization_id == org_id, Lead.contact_id.in_(contact_ids)
        )
    )
    return dict(rows.all())
