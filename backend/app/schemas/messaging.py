"""Conversation, message and contact response shapes."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    ConversationStatus, Intent, MessageDirection, MessageStatus,
    MessageType, Platform, SenderType,
)
from app.schemas.common import ORMModel


class ContactOut(ORMModel):
    id: uuid.UUID
    platform: Platform
    external_user_id: str
    display_name: str
    handle: str | None = None
    phone: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    tags: list = []
    opted_out_at: datetime | None = None
    created_at: datetime


class AttachmentOut(ORMModel):
    id: uuid.UUID
    kind: MessageType
    url: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    caption: str | None = None


class MessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    platform: Platform
    direction: MessageDirection
    sender_type: SenderType
    sender_name: str | None = None
    message_type: MessageType
    text: str | None = None
    status: MessageStatus
    error_message: str | None = None
    confidence: float | None = None
    sent_at: datetime
    attachments: list[AttachmentOut] = []


class ConversationOut(ORMModel):
    id: uuid.UUID
    platform: Platform
    status: ConversationStatus
    subject: str | None = None
    contact: ContactOut
    assigned_user_id: uuid.UUID | None = None
    ai_enabled: bool
    last_intent: Intent | None = None
    last_confidence: float | None = None
    unread_count: int
    message_count: int
    last_message_at: datetime | None = None
    # Denormalized for the list view so the inbox needs one query, not N+1.
    last_message_preview: str | None = None
    lead_score: int | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []


class ReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ConversationPatch(BaseModel):
    status: ConversationStatus | None = None
    assigned_user_id: uuid.UUID | None = None
    ai_enabled: bool | None = None


# ── Internal (n8n) ───────────────────────────────────────────────────────


class InternalIngestResult(BaseModel):
    created: bool
    organization_id: str
    message_id: str
    conversation_id: str
    contact_id: str
    platform: str
    text: str | None = None
    ai_enabled: bool
    contact_opted_out: bool


class InternalRouteRequest(BaseModel):
    organization_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID


class InternalSendRequest(BaseModel):
    organization_id: uuid.UUID
    conversation_id: uuid.UUID
    text: str = Field(min_length=1, max_length=4000)
    sender_type: SenderType = SenderType.AI
    confidence: float | None = None
    ai_run_id: uuid.UUID | None = None


class InternalWorkflowRun(BaseModel):
    workflow_code: str
    n8n_execution_id: str | None = None
    organization_id: uuid.UUID | None = None
    status: str = "failed"
    platform: Platform | None = None
    error: str | None = None
    failed_node: str | None = None
    duration_ms: int | None = None
    idempotency_key: str | None = None
    input_payload: dict | None = None
    output_payload: dict | None = None
