"""Inbound message ingestion.

This is the funnel every channel passes through. Its job is narrow and it
matters that it stays narrow: take a `UnifiedMessage`, land it in the database
exactly once, and return enough context for the AI layer to act.

Idempotency
-----------
Platforms retry. Meta will re-deliver a webhook for roughly 24 hours until it
sees a 200, and a slow AI call is exactly the kind of thing that causes a
timeout mid-processing. So ingestion is keyed on
``(organization_id, platform, external_message_id)``: a second delivery of the
same message finds the existing row and returns it with ``created=False``
rather than duplicating the conversation or triggering a second AI reply.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.base import StatusUpdate, UnifiedMessage
from app.models import (
    AnalyticsEvent,
    Channel,
    Contact,
    Conversation,
    Message,
    MessageAttachment,
)
from app.models.enums import (
    ConversationStatus,
    MessageDirection,
    MessageStatus,
    Platform,
    SenderType,
)

log = get_logger("ingest")


@dataclass(slots=True)
class IngestResult:
    message: Message
    conversation: Conversation
    contact: Contact
    created: bool
    """False when this was a duplicate delivery of a message we already have."""

    def as_dict(self) -> dict:
        """The payload n8n receives back, and passes on to the AI router."""
        return {
            "created": self.created,
            "organization_id": str(self.conversation.organization_id),
            "message_id": str(self.message.id),
            "conversation_id": str(self.conversation.id),
            "contact_id": str(self.contact.id),
            "platform": self.conversation.platform.value,
            "text": self.message.text,
            "ai_enabled": self.conversation.ai_enabled,
            "contact_opted_out": self.contact.opted_out_at is not None,
        }


class IngestionService:
    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.org_id = organization_id

    async def ingest(self, unified: UnifiedMessage) -> IngestResult:
        existing = await self._find_existing(unified)
        if existing is not None:
            log.info(
                "message_already_ingested",
                platform=unified.platform.value,
                external_message_id=unified.external_message_id,
            )
            conversation = await self.db.get(Conversation, existing.conversation_id)
            contact = await self.db.get(Contact, existing.contact_id)
            # Both are guaranteed present: the message row cannot exist without them.
            return IngestResult(existing, conversation, contact, created=False)  # type: ignore[arg-type]

        contact = await self._upsert_contact(unified)
        conversation = await self._upsert_conversation(unified, contact)
        message = await self._create_message(unified, contact, conversation)

        self._bump_conversation(conversation, message)
        await self._record_analytics(unified, conversation)

        try:
            await self.db.flush()
        except IntegrityError:
            # A concurrent delivery of the same message won the race. Roll back
            # to the savepoint and return what the other request stored.
            await self.db.rollback()
            duplicate = await self._find_existing(unified)
            if duplicate is None:
                raise
            log.info("message_race_resolved",
                     external_message_id=unified.external_message_id)
            conv = await self.db.get(Conversation, duplicate.conversation_id)
            cont = await self.db.get(Contact, duplicate.contact_id)
            return IngestResult(duplicate, conv, cont, created=False)  # type: ignore[arg-type]

        log.info(
            "message_ingested",
            platform=unified.platform.value,
            conversation_id=str(conversation.id),
            message_id=str(message.id),
        )
        return IngestResult(message, conversation, contact, created=True)

    async def ingest_many(self, messages: list[UnifiedMessage]) -> list[IngestResult]:
        return [await self.ingest(m) for m in messages]

    # ── Steps ────────────────────────────────────────────────────────────

    async def _find_existing(self, unified: UnifiedMessage) -> Message | None:
        return await self.db.scalar(
            select(Message).where(
                Message.organization_id == self.org_id,
                Message.platform == unified.platform,
                Message.external_message_id == unified.external_message_id,
            )
        )

    async def _upsert_contact(self, unified: UnifiedMessage) -> Contact:
        contact = await self.db.scalar(
            select(Contact).where(
                Contact.organization_id == self.org_id,
                Contact.platform == unified.platform,
                Contact.external_user_id == unified.external_user_id,
            )
        )
        if contact is None:
            contact = Contact(
                organization_id=self.org_id,
                platform=unified.platform,
                external_user_id=unified.external_user_id,
                # Platforms don't always send a name. Fall back to the handle,
                # then to a readable placeholder — never to an empty string,
                # because the inbox has to render something.
                display_name=(
                    unified.sender_name
                    or unified.contact_handle
                    or f"{unified.platform.value.title()} contact"
                ),
                handle=unified.contact_handle,
                phone=unified.contact_phone,
                avatar_url=unified.contact_avatar_url,
                locale=unified.locale,
            )
            self.db.add(contact)
            await self.db.flush()
        else:
            # Only fill gaps. A name an operator typed should not be
            # overwritten by whatever the platform sent this time.
            if unified.sender_name and contact.display_name.endswith("contact"):
                contact.display_name = unified.sender_name
            contact.handle = contact.handle or unified.contact_handle
            contact.phone = contact.phone or unified.contact_phone
            contact.avatar_url = unified.contact_avatar_url or contact.avatar_url

        return contact

    async def _upsert_conversation(
        self, unified: UnifiedMessage, contact: Contact
    ) -> Conversation:
        conversation = await self.db.scalar(
            select(Conversation).where(
                Conversation.organization_id == self.org_id,
                Conversation.platform == unified.platform,
                Conversation.external_conversation_id == unified.conversation_id,
            )
        )
        if conversation is None:
            channel = await self.db.scalar(
                select(Channel).where(
                    Channel.organization_id == self.org_id,
                    Channel.platform == unified.platform,
                    Channel.is_active.is_(True),
                )
            )
            conversation = Conversation(
                organization_id=self.org_id,
                contact_id=contact.id,
                channel_id=channel.id if channel else None,
                platform=unified.platform,
                external_conversation_id=unified.conversation_id,
                status=ConversationStatus.OPEN,
            )
            self.db.add(conversation)
            await self.db.flush()
        elif conversation.status is ConversationStatus.CLOSED:
            # A new message reopens a closed thread — otherwise it would sit
            # invisible in the inbox while the customer waits.
            conversation.status = ConversationStatus.OPEN

        return conversation

    async def _create_message(
        self, unified: UnifiedMessage, contact: Contact, conversation: Conversation
    ) -> Message:
        message = Message(
            organization_id=self.org_id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            platform=unified.platform,
            external_message_id=unified.external_message_id,
            direction=MessageDirection.INBOUND,
            sender_type=SenderType.CONTACT,
            sender_name=unified.sender_name or contact.display_name,
            message_type=unified.message_type,
            text=unified.text,
            status=MessageStatus.DELIVERED,
            sent_at=unified.timestamp,
            raw_payload=unified.raw or None,
        )
        self.db.add(message)
        await self.db.flush()

        for attachment in unified.attachments:
            self.db.add(
                MessageAttachment(
                    organization_id=self.org_id,
                    message_id=message.id,
                    kind=attachment.kind,
                    url=attachment.url,
                    external_media_id=attachment.external_media_id,
                    mime_type=attachment.mime_type,
                    file_name=attachment.file_name,
                    size_bytes=attachment.size_bytes,
                    caption=attachment.caption,
                )
            )
        return message

    def _bump_conversation(self, conversation: Conversation, message: Message) -> None:
        conversation.message_count += 1
        conversation.unread_count += 1
        # Out-of-order webhook delivery is normal, so only move the clock forward.
        if (
            conversation.last_message_at is None
            or message.sent_at > conversation.last_message_at
        ):
            conversation.last_message_at = message.sent_at

    async def _record_analytics(
        self, unified: UnifiedMessage, conversation: Conversation
    ) -> None:
        self.db.add(
            AnalyticsEvent(
                organization_id=self.org_id,
                event_type="message_received",
                platform=unified.platform,
                conversation_id=conversation.id,
                occurred_at=unified.timestamp,
                properties={"message_type": unified.message_type.value},
            )
        )

    # ── Outbound & status ────────────────────────────────────────────────

    async def record_outbound(
        self,
        *,
        conversation: Conversation,
        text: str,
        sender_type: SenderType,
        sender_user_id: uuid.UUID | None = None,
        sender_name: str | None = None,
        external_message_id: str | None = None,
        status: MessageStatus = MessageStatus.SENT,
        confidence: float | None = None,
        ai_run_id: uuid.UUID | None = None,
        error: str | None = None,
    ) -> Message:
        """Store a message we sent, whether a person or the AI wrote it."""
        now = datetime.now(UTC)
        message = Message(
            organization_id=self.org_id,
            conversation_id=conversation.id,
            contact_id=conversation.contact_id,
            platform=conversation.platform,
            external_message_id=external_message_id,
            direction=MessageDirection.OUTBOUND,
            sender_type=sender_type,
            sender_name=sender_name,
            sender_user_id=sender_user_id,
            text=text,
            status=status,
            error_message=error,
            confidence=confidence,
            ai_run_id=ai_run_id,
            sent_at=now,
        )
        self.db.add(message)

        conversation.message_count += 1
        conversation.last_message_at = now
        # Replying clears the unread marker regardless of who replied.
        conversation.unread_count = 0

        self.db.add(
            AnalyticsEvent(
                organization_id=self.org_id,
                event_type="message_sent",
                platform=conversation.platform,
                conversation_id=conversation.id,
                occurred_at=now,
                properties={
                    "sender_type": sender_type.value,
                    "automated": sender_type is SenderType.AI,
                },
            )
        )
        await self.db.flush()
        return message

    async def apply_status_updates(self, updates: list[StatusUpdate]) -> int:
        """Fold delivery receipts into messages we already sent."""
        mapping = {
            "sent": MessageStatus.SENT,
            "delivered": MessageStatus.DELIVERED,
            "read": MessageStatus.READ,
            "failed": MessageStatus.FAILED,
        }
        # Receipts arrive out of order; never downgrade a message's state.
        rank = {
            MessageStatus.PENDING: 0, MessageStatus.SENT: 1,
            MessageStatus.DELIVERED: 2, MessageStatus.READ: 3,
            MessageStatus.FAILED: 4,
        }

        applied = 0
        for update in updates:
            message = await self.db.scalar(
                select(Message).where(
                    Message.organization_id == self.org_id,
                    Message.platform == update.platform,
                    Message.external_message_id == update.external_message_id,
                )
            )
            if message is None:
                continue
            new_status = mapping[update.status]
            if rank[new_status] > rank[message.status]:
                message.status = new_status
                message.error_message = update.error
                applied += 1
        return applied


def resolve_platform(value: str) -> Platform:
    try:
        return Platform(value.lower())
    except ValueError as exc:
        raise ValueError(f"Unknown platform '{value}'.") from exc
