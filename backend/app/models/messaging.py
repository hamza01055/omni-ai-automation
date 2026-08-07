"""Channels, contacts, conversations and messages.

The uniqueness constraints here are what make webhook delivery idempotent:
platforms retry aggressively, and every inbound message is keyed on
``(organization_id, platform, external_message_id)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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

from app.core.db import Base
from app.models.base import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ConversationStatus,
    Intent,
    MessageDirection,
    MessageStatus,
    MessageType,
    Platform,
    SenderType,
)


class Channel(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """One connected account on one platform (e.g. a specific WhatsApp number)."""

    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("organization_id", "platform", "external_account_id",
                         name="uq_channel_org_platform_account"),
    )

    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # True while the channel runs against its mock adapter (no live credentials).
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    webhook_verify_token: Mapped[str | None] = mapped_column(String(128))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    credentials: Mapped[list[ChannelCredential]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class ChannelCredential(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """Encrypted secret for a channel.

    ``value_encrypted`` is Fernet ciphertext produced by
    ``app.core.security.encrypt_secret``. Plaintext never leaves the backend
    and is never serialized into an API response.
    """

    __tablename__ = "channel_credentials"
    __table_args__ = (
        UniqueConstraint("channel_id", "key", name="uq_credential_channel_key"),
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)   # e.g. "access_token"
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    channel: Mapped[Channel] = relationship(back_populates="credentials")


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """A person the organization talks to, identified per platform.

    The same human on WhatsApp and Instagram is two rows until an operator
    merges them via ``merged_into_id``.
    """

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("organization_id", "platform", "external_user_id",
                         name="uq_contact_org_platform_user"),
        Index("ix_contact_org_name", "organization_id", "display_name"),
    )

    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False), nullable=False
    )
    external_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    locale: Mapped[str | None] = mapped_column(String(16))
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Set when the contact asks to stop receiving proactive follow-ups.
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )

    conversations: Mapped[list[Conversation]] = relationship(back_populates="contact")


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """A thread with one contact on one channel."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("organization_id", "platform", "external_conversation_id",
                         name="uq_conversation_org_platform_external"),
        Index("ix_conversation_inbox", "organization_id", "status", "last_message_at"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL")
    )
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False), nullable=False
    )
    external_conversation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ConversationStatus] = mapped_column(
        SAEnum(ConversationStatus, name="conversation_status_enum", native_enum=False),
        default=ConversationStatus.OPEN, nullable=False, index=True,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # True while AI is allowed to reply without a person in the loop.
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_intent: Mapped[Intent | None] = mapped_column(
        SAEnum(Intent, name="intent_enum", native_enum=False)
    )
    last_confidence: Mapped[float | None] = mapped_column(Float)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    contact: Mapped[Contact] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    """A single message in the unified schema — the only shape the AI layer sees."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "platform", "external_message_id",
                         name="uq_message_org_platform_external"),
        Index("ix_message_conversation_time", "conversation_id", "sent_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )
    platform: Mapped[Platform] = mapped_column(
        SAEnum(Platform, name="platform_enum", native_enum=False), nullable=False
    )
    # Null for outbound messages we created before the platform assigned an id.
    external_message_id: Mapped[str | None] = mapped_column(String(191))
    direction: Mapped[MessageDirection] = mapped_column(
        SAEnum(MessageDirection, name="message_direction_enum", native_enum=False),
        nullable=False, index=True,
    )
    sender_type: Mapped[SenderType] = mapped_column(
        SAEnum(SenderType, name="sender_type_enum", native_enum=False), nullable=False
    )
    sender_name: Mapped[str | None] = mapped_column(String(160))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    message_type: Mapped[MessageType] = mapped_column(
        SAEnum(MessageType, name="message_type_enum", native_enum=False),
        default=MessageType.TEXT, nullable=False,
    )
    text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[MessageStatus] = mapped_column(
        SAEnum(MessageStatus, name="message_status_enum", native_enum=False),
        default=MessageStatus.SENT, nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    # AI provenance — populated when sender_type is AI.
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Untouched platform payload, kept for debugging and replay only.
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    attachments: Mapped[list[MessageAttachment]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessageAttachment(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "message_attachments"

    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[MessageType] = mapped_column(
        SAEnum(MessageType, name="message_type_enum", native_enum=False), nullable=False
    )
    url: Mapped[str | None] = mapped_column(String(1024))
    external_media_id: Mapped[str | None] = mapped_column(String(191))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    file_name: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    caption: Mapped[str | None] = mapped_column(Text)

    message: Mapped[Message] = relationship(back_populates="attachments")
