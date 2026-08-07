"""CRM, AI observability, knowledge base, content pipeline, workflows, ops."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.db import Base
from app.models.base import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ApprovalStatus,
    ContentStatus,
    DocumentStatus,
    Intent,
    LeadStatus,
    Platform,
    RunStatus,
)

# ── CRM ──────────────────────────────────────────────────────────────────


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_lead_pipeline", "organization_id", "status", "score"),
        UniqueConstraint("organization_id", "contact_id", name="uq_lead_org_contact"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False), nullable=False
    )
    interest: Mapped[str | None] = mapped_column(String(255))
    budget_band: Mapped[str | None] = mapped_column(String(32))   # low | medium | high
    requirements: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, name="lead_status_enum", native_enum=False),
        default=LeadStatus.NEW, nullable=False,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Follow-up guardrails (spec §14): never message someone forever.
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_follow_ups: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    activities: Mapped[list[LeadActivity]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class LeadActivity(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Append-only history: status changes, notes, follow-ups, score changes."""

    __tablename__ = "lead_activities"
    __table_args__ = (Index("ix_lead_activity_lead_time", "lead_id", "created_at"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(String(16), default="system", nullable=False)
    activity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    lead: Mapped[Lead] = relationship(back_populates="activities")


# ── AI ───────────────────────────────────────────────────────────────────


class AIAgent(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """A configured agent (router, support, sales, content) per organization."""

    __tablename__ = "ai_agents"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_agent_org_key"),)

    key: Mapped[str] = mapped_column(String(48), nullable=False)   # router | support | sales | content
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(64), default=settings.openai_chat_model,
                                       nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AIPrompt(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Versioned prompt template. Editing creates a new version, never a mutation."""

    __tablename__ = "ai_prompts"
    __table_args__ = (
        UniqueConstraint("organization_id", "agent_id", "version", name="uq_prompt_agent_version"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AIRun(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """One model invocation. This is the audit trail for every AI decision."""

    __tablename__ = "ai_runs"
    __table_args__ = (Index("ix_airun_org_time", "organization_id", "created_at"),)

    agent_key: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[Intent | None] = mapped_column(
        SAEnum(Intent, name="intent_enum", native_enum=False)
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict | None] = mapped_column(JSONB)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status_enum", native_enum=False),
        default=RunStatus.SUCCESS, nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)


# ── Knowledge base / RAG ─────────────────────────────────────────────────


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # pdf|txt|md|faq|manual
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(512))
    # Content hash — re-uploading an identical file is a no-op.
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, name="document_status_enum", native_enum=False),
        default=DocumentStatus.UPLOADED, nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """An embedded slice of a document.

    The HNSW index is created in the migration rather than here, because it
    needs the operator class (``vector_cosine_ops``) spelled out.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions)
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


# ── Content pipeline ─────────────────────────────────────────────────────


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(String(64))
    target_platforms: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    posts: Mapped[list[ContentPost]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class ContentPost(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """A publishable unit: one idea, one platform, one scheduled slot."""

    __tablename__ = "content_posts"
    __table_args__ = (Index("ix_post_schedule", "organization_id", "status", "scheduled_for"),)

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    call_to_action: Mapped[str | None] = mapped_column(String(255))
    media_urls: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[ContentStatus] = mapped_column(
        SAEnum(ContentStatus, name="content_status_enum", native_enum=False),
        default=ContentStatus.DRAFT, nullable=False, index=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_post_id: Mapped[str | None] = mapped_column(String(191))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    engagement: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    campaign: Mapped[Campaign | None] = relationship(back_populates="posts")
    variants: Mapped[list[ContentVariant]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class ContentVariant(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Alternative AI copy for the same post, kept for A/B choice and audit."""

    __tablename__ = "content_variants"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_posts.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(32), default="A", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    call_to_action: Mapped[str | None] = mapped_column(String(255))
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL")
    )
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    post: Mapped[ContentPost] = relationship(back_populates="variants")


class ApprovalRequest(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """The human-in-the-loop queue.

    Anything the AI wants to do but is not confident enough to do alone lands
    here: low-confidence replies, follow-up messages, content ready to publish.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approval_queue", "organization_id", "status", "created_at"),)

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)  # message|content|follow_up
    subject_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    proposed_content: Mapped[str | None] = mapped_column(Text)
    edited_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status_enum", native_enum=False),
        default=ApprovalStatus.PENDING_REVIEW, nullable=False,
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ── Workflows & ops ──────────────────────────────────────────────────────


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Backend-side registration of an n8n workflow, for dashboard visibility."""

    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_workflow_org_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)   # WF-01 …
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), default="incoming", nullable=False)
    n8n_workflow_id: Mapped[str | None] = mapped_column(String(64))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avg_duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    graph: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflowrun_org_status", "organization_id", "status", "created_at"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_run_org_idempotency"),
    )

    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL")
    )
    workflow_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    n8n_execution_id: Mapped[str | None] = mapped_column(String(64))
    # Derived from the platform's message id — the retry-safety key.
    idempotency_key: Mapped[str | None] = mapped_column(String(191))
    platform: Mapped[Platform | None] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False)
    )
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status_enum", native_enum=False),
        default=RunStatus.RUNNING, nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    input_payload: Mapped[dict | None] = mapped_column(JSONB)
    output_payload: Mapped[dict | None] = mapped_column(JSONB)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_user_unread", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(512))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Append-only record of who changed what. Never updated, never deleted."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_time", "organization_id", "created_at"),)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AnalyticsEvent(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Thin fact table. Dashboard charts aggregate from here, not from live tables."""

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_org_type_time", "organization_id", "event_type", "occurred_at"),
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[Platform | None] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False)
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    value: Mapped[float | None] = mapped_column(Float)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
