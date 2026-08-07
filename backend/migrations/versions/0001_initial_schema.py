"""Initial schema: identity, messaging, CRM, AI, knowledge, content, ops.

Generated from the ORM models and then hand-checked. Two things Alembic cannot
infer are added explicitly at the bottom: the pgvector extension, and the HNSW
index on knowledge_chunks.embedding with the cosine operator class.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
JSONB = pg.JSONB
TS = sa.DateTime(timezone=True)

EMBEDDING_DIMENSIONS = 1536  # keep in step with settings.embedding_dimensions

PLATFORM = sa.Enum("whatsapp", "instagram", "facebook", "x",
                   name="platform_enum", native_enum=False)
ROLE = sa.Enum("owner", "admin", "manager", "agent", "viewer",
               name="role_enum", native_enum=False)
DIRECTION = sa.Enum("inbound", "outbound", name="message_direction_enum", native_enum=False)
MSG_TYPE = sa.Enum("text", "image", "video", "audio", "document", "location",
                   "sticker", "reaction", "system", "unsupported",
                   name="message_type_enum", native_enum=False)
MSG_STATUS = sa.Enum("pending", "sent", "delivered", "read", "failed",
                     name="message_status_enum", native_enum=False)
SENDER = sa.Enum("contact", "ai", "human", "system", name="sender_type_enum",
                 native_enum=False)
CONV_STATUS = sa.Enum("open", "pending_human", "snoozed", "closed",
                      name="conversation_status_enum", native_enum=False)
INTENT = sa.Enum("support", "pricing", "product_question", "purchase_intent",
                 "lead_generation", "complaint", "refund", "booking", "general",
                 "spam", "unknown", name="intent_enum", native_enum=False)
LEAD_STATUS = sa.Enum("new", "qualified", "contacted", "meeting", "won", "lost",
                      name="lead_status_enum", native_enum=False)
APPROVAL = sa.Enum("draft", "pending_review", "approved", "rejected",
                   name="approval_status_enum", native_enum=False)
CONTENT_STATUS = sa.Enum("draft", "pending_review", "approved", "scheduled",
                         "publishing", "published", "failed", "rejected",
                         name="content_status_enum", native_enum=False)
RUN_STATUS = sa.Enum("running", "success", "failed", "retrying", "dead_letter",
                     name="run_status_enum", native_enum=False)
DOC_STATUS = sa.Enum("uploaded", "processing", "indexed", "failed",
                     name="document_status_enum", native_enum=False)


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", UUID, primary_key=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False,
                  index=True),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
    ]


def _org() -> sa.Column:
    return sa.Column(
        "organization_id", UUID,
        sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # ── Identity ─────────────────────────────────────────────────────────
    op.create_table(
        "organizations", *_base(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True, index=True),
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("settings", JSONB, server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
    )
    op.create_table(
        "users", *_base(),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("avatar_url", sa.String(512)),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", TS),
    )
    op.create_table(
        "organization_members", *_base(), _org(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", ROLE, server_default="agent", nullable=False),
        sa.Column("is_default", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_member_org_user"),
    )
    op.create_index("ix_member_user", "organization_members", ["user_id"])

    op.create_table(
        "refresh_sessions", *_base(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("organization_id", UUID,
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
    )
    op.create_index("ix_refresh_user_active", "refresh_sessions", ["user_id", "revoked_at"])

    # ── Channels ─────────────────────────────────────────────────────────
    op.create_table(
        "channels", *_base(), _org(),
        sa.Column("platform", PLATFORM, nullable=False, index=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("external_account_id", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("is_sandbox", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("webhook_verify_token", sa.String(128)),
        sa.Column("last_event_at", TS),
        sa.Column("config", JSONB, server_default="{}", nullable=False),
        sa.UniqueConstraint("organization_id", "platform", "external_account_id",
                            name="uq_channel_org_platform_account"),
    )
    op.create_table(
        "channel_credentials", *_base(), _org(),
        sa.Column("channel_id", UUID, sa.ForeignKey("channels.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value_encrypted", sa.Text, nullable=False),
        sa.Column("expires_at", TS),
        sa.Column("rotated_at", TS),
        sa.UniqueConstraint("channel_id", "key", name="uq_credential_channel_key"),
    )

    # ── Contacts / conversations / messages ──────────────────────────────
    op.create_table(
        "contacts", *_base(), _org(),
        sa.Column("platform", PLATFORM, nullable=False),
        sa.Column("external_user_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("handle", sa.String(160)),
        sa.Column("phone", sa.String(32), index=True),
        sa.Column("email", sa.String(255), index=True),
        sa.Column("avatar_url", sa.String(512)),
        sa.Column("locale", sa.String(16)),
        sa.Column("tags", JSONB, server_default="[]", nullable=False),
        sa.Column("attributes", JSONB, server_default="{}", nullable=False),
        sa.Column("opted_out_at", TS),
        sa.Column("merged_into_id", UUID, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.UniqueConstraint("organization_id", "platform", "external_user_id",
                            name="uq_contact_org_platform_user"),
    )
    op.create_index("ix_contact_org_name", "contacts", ["organization_id", "display_name"])

    op.create_table(
        "conversations", *_base(), _org(),
        sa.Column("contact_id", UUID, sa.ForeignKey("contacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("channel_id", UUID, sa.ForeignKey("channels.id", ondelete="SET NULL")),
        sa.Column("platform", PLATFORM, nullable=False),
        sa.Column("external_conversation_id", sa.String(160), nullable=False),
        sa.Column("subject", sa.String(255)),
        sa.Column("status", CONV_STATUS, server_default="open", nullable=False, index=True),
        sa.Column("assigned_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"),
                  index=True),
        sa.Column("ai_enabled", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("last_intent", INTENT),
        sa.Column("last_confidence", sa.Float),
        sa.Column("unread_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("message_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_message_at", TS, index=True),
        sa.Column("snoozed_until", TS),
        sa.Column("meta", JSONB, server_default="{}", nullable=False),
        sa.UniqueConstraint("organization_id", "platform", "external_conversation_id",
                            name="uq_conversation_org_platform_external"),
    )
    op.create_index("ix_conversation_inbox", "conversations",
                    ["organization_id", "status", "last_message_at"])

    op.create_table(
        "ai_runs", *_base(), _org(),
        sa.Column("agent_key", sa.String(48), nullable=False, index=True),
        sa.Column("conversation_id", UUID,
                  sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("message_id", UUID),
        sa.Column("workflow_run_id", UUID),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("intent", INTENT),
        sa.Column("confidence", sa.Float),
        sa.Column("needs_human", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("input_summary", sa.Text),
        sa.Column("output", JSONB),
        sa.Column("prompt_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("status", RUN_STATUS, server_default="success", nullable=False),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_airun_org_time", "ai_runs", ["organization_id", "created_at"])

    op.create_table(
        "messages", *_base(), _org(),
        sa.Column("conversation_id", UUID,
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", UUID, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("platform", PLATFORM, nullable=False),
        sa.Column("external_message_id", sa.String(191)),
        sa.Column("direction", DIRECTION, nullable=False, index=True),
        sa.Column("sender_type", SENDER, nullable=False),
        sa.Column("sender_name", sa.String(160)),
        sa.Column("sender_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("message_type", MSG_TYPE, server_default="text", nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("status", MSG_STATUS, server_default="sent", nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("ai_run_id", UUID, sa.ForeignKey("ai_runs.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Float),
        sa.Column("sent_at", TS, nullable=False, index=True),
        sa.Column("raw_payload", JSONB),
        sa.UniqueConstraint("organization_id", "platform", "external_message_id",
                            name="uq_message_org_platform_external"),
    )
    op.create_index("ix_message_conversation_time", "messages",
                    ["conversation_id", "sent_at"])

    op.create_table(
        "message_attachments", *_base(), _org(),
        sa.Column("message_id", UUID, sa.ForeignKey("messages.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", MSG_TYPE, nullable=False),
        sa.Column("url", sa.String(1024)),
        sa.Column("external_media_id", sa.String(191)),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("file_name", sa.String(255)),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("caption", sa.Text),
    )

    # ── CRM ──────────────────────────────────────────────────────────────
    op.create_table(
        "leads", *_base(), _org(),
        sa.Column("contact_id", UUID, sa.ForeignKey("contacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("conversation_id", UUID,
                  sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("source_platform", PLATFORM, nullable=False),
        sa.Column("interest", sa.String(255)),
        sa.Column("budget_band", sa.String(32)),
        sa.Column("requirements", sa.Text),
        sa.Column("score", sa.Integer, server_default="0", nullable=False, index=True),
        sa.Column("score_breakdown", JSONB, server_default="{}", nullable=False),
        sa.Column("status", LEAD_STATUS, server_default="new", nullable=False),
        sa.Column("assigned_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"),
                  index=True),
        sa.Column("follow_up_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("max_follow_ups", sa.Integer, server_default="3", nullable=False),
        sa.Column("next_follow_up_at", TS, index=True),
        sa.Column("last_contact_at", TS),
        sa.Column("closed_at", TS),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint("organization_id", "contact_id", name="uq_lead_org_contact"),
    )
    op.create_index("ix_lead_pipeline", "leads", ["organization_id", "status", "score"])

    op.create_table(
        "lead_activities", *_base(), _org(),
        sa.Column("lead_id", UUID, sa.ForeignKey("leads.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("actor_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_type", sa.String(16), server_default="system", nullable=False),
        sa.Column("activity_type", sa.String(48), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("payload", JSONB, server_default="{}", nullable=False),
    )
    op.create_index("ix_lead_activity_lead_time", "lead_activities", ["lead_id", "created_at"])

    # ── AI configuration ─────────────────────────────────────────────────
    op.create_table(
        "ai_agents", *_base(), _org(),
        sa.Column("key", sa.String(48), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("temperature", sa.Float, server_default="0.2", nullable=False),
        sa.Column("is_enabled", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("config", JSONB, server_default="{}", nullable=False),
        sa.UniqueConstraint("organization_id", "key", name="uq_agent_org_key"),
    )
    op.create_table(
        "ai_prompts", *_base(), _org(),
        sa.Column("agent_id", UUID, sa.ForeignKey("ai_agents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("variables", JSONB, server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("organization_id", "agent_id", "version",
                            name="uq_prompt_agent_version"),
    )

    # ── Knowledge base ───────────────────────────────────────────────────
    op.create_table(
        "knowledge_documents", *_base(), _org(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("file_name", sa.String(255)),
        sa.Column("file_path", sa.String(512)),
        sa.Column("content_hash", sa.String(64), index=True),
        sa.Column("status", DOC_STATUS, server_default="uploaded", nullable=False),
        sa.Column("chunk_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("uploaded_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("meta", JSONB, server_default="{}", nullable=False),
    )
    op.create_table(
        "knowledge_chunks", *_base(), _org(),
        sa.Column("document_id", UUID,
                  sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS)),
        sa.Column("meta", JSONB, server_default="{}", nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
    )
    # HNSW beats IVFFlat here: the corpus is small per tenant and grows by
    # incremental upload, so we want an index that does not need retraining.
    op.execute(
        "CREATE INDEX ix_chunk_embedding_hnsw ON knowledge_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index("ix_chunk_org_doc", "knowledge_chunks",
                    ["organization_id", "document_id"])

    # ── Content ──────────────────────────────────────────────────────────
    op.create_table(
        "campaigns", *_base(), _org(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("goal", sa.Text),
        sa.Column("audience", sa.Text),
        sa.Column("tone", sa.String(64)),
        sa.Column("target_platforms", JSONB, server_default="[]", nullable=False),
        sa.Column("starts_at", TS),
        sa.Column("ends_at", TS),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_table(
        "content_posts", *_base(), _org(),
        sa.Column("campaign_id", UUID, sa.ForeignKey("campaigns.id", ondelete="CASCADE")),
        sa.Column("platform", PLATFORM, nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("hashtags", JSONB, server_default="[]", nullable=False),
        sa.Column("call_to_action", sa.String(255)),
        sa.Column("media_urls", JSONB, server_default="[]", nullable=False),
        sa.Column("status", CONTENT_STATUS, server_default="draft", nullable=False,
                  index=True),
        sa.Column("scheduled_for", TS),
        sa.Column("published_at", TS),
        sa.Column("external_post_id", sa.String(191)),
        sa.Column("publish_attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_error", sa.Text),
        sa.Column("approved_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", TS),
        sa.Column("engagement", JSONB, server_default="{}", nullable=False),
    )
    op.create_index("ix_post_schedule", "content_posts",
                    ["organization_id", "status", "scheduled_for"])

    op.create_table(
        "content_variants", *_base(), _org(),
        sa.Column("post_id", UUID, sa.ForeignKey("content_posts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("label", sa.String(32), server_default="A", nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("hashtags", JSONB, server_default="[]", nullable=False),
        sa.Column("call_to_action", sa.String(255)),
        sa.Column("ai_run_id", UUID, sa.ForeignKey("ai_runs.id", ondelete="SET NULL")),
        sa.Column("is_selected", sa.Boolean, server_default=sa.false(), nullable=False),
    )

    op.create_table(
        "approval_requests", *_base(), _org(),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", UUID),
        sa.Column("conversation_id", UUID,
                  sa.ForeignKey("conversations.id", ondelete="CASCADE")),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("proposed_content", sa.Text),
        sa.Column("edited_content", sa.Text),
        sa.Column("status", APPROVAL, server_default="pending_review", nullable=False),
        sa.Column("decided_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", TS),
        sa.Column("payload", JSONB, server_default="{}", nullable=False),
    )
    op.create_index("ix_approval_queue", "approval_requests",
                    ["organization_id", "status", "created_at"])

    # ── Workflows and ops ────────────────────────────────────────────────
    op.create_table(
        "workflows", *_base(), _org(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("category", sa.String(32), server_default="incoming", nullable=False),
        sa.Column("n8n_workflow_id", sa.String(64)),
        sa.Column("is_enabled", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("success_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("failure_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_run_at", TS),
        sa.Column("avg_duration_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("graph", JSONB, server_default="{}", nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_workflow_org_code"),
    )
    op.create_table(
        "workflow_runs", *_base(), _org(),
        sa.Column("workflow_id", UUID, sa.ForeignKey("workflows.id", ondelete="SET NULL")),
        sa.Column("workflow_code", sa.String(32), nullable=False, index=True),
        sa.Column("n8n_execution_id", sa.String(64)),
        sa.Column("idempotency_key", sa.String(191)),
        sa.Column("platform", PLATFORM),
        sa.Column("status", RUN_STATUS, server_default="running", nullable=False),
        sa.Column("attempt", sa.Integer, server_default="1", nullable=False),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("input_payload", JSONB),
        sa.Column("output_payload", JSONB),
        sa.Column("finished_at", TS),
        sa.UniqueConstraint("organization_id", "idempotency_key",
                            name="uq_run_org_idempotency"),
    )
    op.create_index("ix_workflowrun_org_status", "workflow_runs",
                    ["organization_id", "status", "created_at"])

    op.create_table(
        "notifications", *_base(), _org(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("link", sa.String(512)),
        sa.Column("read_at", TS),
    )
    op.create_index("ix_notification_user_unread", "notifications", ["user_id", "read_at"])

    op.create_table(
        "audit_logs", *_base(), _org(),
        sa.Column("actor_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_type", sa.String(16), server_default="user", nullable=False),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("resource_type", sa.String(48), nullable=False),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("changes", JSONB, server_default="{}", nullable=False),
    )
    op.create_index("ix_audit_org_time", "audit_logs", ["organization_id", "created_at"])

    op.create_table(
        "analytics_events", *_base(), _org(),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("platform", PLATFORM),
        sa.Column("conversation_id", UUID),
        sa.Column("lead_id", UUID),
        sa.Column("campaign_id", UUID),
        sa.Column("value", sa.Float),
        sa.Column("properties", JSONB, server_default="{}", nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
    )
    op.create_index("ix_analytics_org_type_time", "analytics_events",
                    ["organization_id", "event_type", "occurred_at"])


def downgrade() -> None:
    for table in (
        "analytics_events", "audit_logs", "notifications", "workflow_runs", "workflows",
        "approval_requests", "content_variants", "content_posts", "campaigns",
        "knowledge_chunks", "knowledge_documents", "ai_prompts", "ai_agents",
        "lead_activities", "leads", "message_attachments", "messages", "ai_runs",
        "conversations", "contacts", "channel_credentials", "channels",
        "refresh_sessions", "organization_members", "users", "organizations",
    ):
        op.drop_table(table)
