"""The unified message contract and the adapter interface every channel implements.

This module is the seam between platform-specific reality and the rest of the
system. Nothing downstream of ``UnifiedMessage`` — not the router, not the
support agent, not the inbox — is allowed to know what WhatsApp's JSON looks
like. Adding a fifth channel means writing one adapter and changing nothing else.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import MessageType, Platform


class UnifiedAttachment(BaseModel):
    kind: MessageType = MessageType.DOCUMENT
    url: str | None = None
    external_media_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    caption: str | None = None


class UnifiedMessage(BaseModel):
    """The single internal shape for an inbound message from any platform."""

    platform: Platform
    external_user_id: str
    conversation_id: str = Field(
        description="Platform-side thread identifier, or a synthesized stable id."
    )
    external_message_id: str
    sender_name: str | None = None
    text: str | None = None
    message_type: MessageType = MessageType.TEXT
    attachments: list[UnifiedAttachment] = Field(default_factory=list)
    timestamp: datetime
    # Contact detail the platform happened to include (phone on WhatsApp,
    # handle on Instagram/X). Never invented by the adapter.
    contact_handle: str | None = None
    contact_phone: str | None = None
    contact_avatar_url: str | None = None
    locale: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def idempotency_key(self) -> str:
        """Stable key for de-duplicating retried webhook deliveries."""
        return f"{self.platform.value}:{self.external_message_id}"


class OutboundMessage(BaseModel):
    """What the system asks a platform to send."""

    platform: Platform
    recipient_id: str
    conversation_id: str | None = None
    text: str | None = None
    message_type: MessageType = MessageType.TEXT
    attachments: list[UnifiedAttachment] = Field(default_factory=list)
    reply_to_external_id: str | None = None


class DeliveryReceipt(BaseModel):
    """What the platform said back after we asked it to send something."""

    accepted: bool
    external_message_id: str | None = None
    status: Literal["pending", "sent", "delivered", "failed"] = "sent"
    error: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


class StatusUpdate(BaseModel):
    """Delivery/read receipt arriving on a webhook after the fact."""

    platform: Platform
    external_message_id: str
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: datetime
    error: str | None = None


class ChannelAdapter(abc.ABC):
    """Contract for a channel integration.

    Implementations must be pure translators plus HTTP clients. They may not
    touch the database, call the AI layer, or decide business outcomes — those
    belong to services.
    """

    platform: Platform

    #: False when running against a mock. The dashboard surfaces this so nobody
    #: mistakes sandbox traffic for live traffic.
    is_live: bool = False

    # ── Inbound ──────────────────────────────────────────────────────────

    @abc.abstractmethod
    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """Return True only if the payload provably came from the platform."""

    @abc.abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        """Translate one webhook body into zero or more unified messages.

        Must never raise on unexpected shapes: unknown event types are skipped,
        because a parse failure would make the platform retry forever.
        """

    def parse_status_updates(self, payload: dict[str, Any]) -> list[StatusUpdate]:
        """Extract delivery receipts. Default: the platform sends none."""
        return []

    def verify_challenge(self, params: dict[str, str]) -> str | None:
        """Handle the GET subscription handshake. Return the echo string or None."""
        return None

    # ── Outbound ─────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def send_message(self, message: OutboundMessage) -> DeliveryReceipt:
        """Deliver a message through the platform's official API."""

    async def publish_post(self, *, body: str, media_urls: list[str] | None = None,
                           **kwargs: Any) -> DeliveryReceipt:
        """Publish content. Channels without a publishing API raise."""
        raise NotImplementedError(
            f"{self.platform.value} does not support content publishing in this build."
        )

    # ── Capability advertisement ─────────────────────────────────────────

    @property
    def capabilities(self) -> dict[str, bool]:
        """What this channel can actually do, so the UI hides what it can't."""
        return {
            "receive_messages": True,
            "send_messages": True,
            "publish_content": False,
            "delivery_receipts": False,
            "media": False,
        }
