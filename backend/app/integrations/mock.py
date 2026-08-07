"""Mock adapter used when a channel has no live credentials.

This is deliberately honest: it accepts sends, records them in memory, and
labels itself as sandbox so nothing in the dashboard can mistake a mock
delivery for a real one. It exists so the whole pipeline — webhook to inbox to
AI to reply — can be exercised locally without a Meta or X developer account.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.core.logging import get_logger
from app.integrations.base import (
    ChannelAdapter, DeliveryReceipt, OutboundMessage, UnifiedMessage,
)
from app.models.enums import MessageType, Platform

log = get_logger("integrations.mock")


class MockAdapter(ChannelAdapter):
    """Stands in for any platform. ``is_live`` is always False."""

    #: Everything "sent" during this process, for tests and the sandbox UI.
    outbox: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.is_live = False

    @property
    def capabilities(self) -> dict[str, bool]:
        return {"receive_messages": True, "send_messages": True,
                "publish_content": True, "delivery_receipts": True, "media": True}

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        # Sandbox mode accepts unsigned payloads so you can curl the webhook.
        return True

    def verify_challenge(self, params: dict[str, str]) -> str | None:
        return params.get("hub.challenge") or params.get("crc_token")

    def parse_webhook(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        """Accept an already-unified payload, so tests can post the internal shape."""
        items = payload.get("messages") if isinstance(payload.get("messages"), list) else [payload]
        out: list[UnifiedMessage] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            out.append(UnifiedMessage(
                platform=self.platform,
                external_user_id=str(item.get("external_user_id", "mock-user-1")),
                conversation_id=str(item.get("conversation_id",
                                             item.get("external_user_id", "mock-user-1"))),
                external_message_id=str(item.get("external_message_id", uuid.uuid4().hex)),
                sender_name=item.get("sender_name", "Sandbox Contact"),
                text=item.get("text"),
                message_type=MessageType(item.get("message_type", "text")),
                timestamp=datetime.now(UTC),
                raw=item,
            ))
        return out

    async def send_message(self, message: OutboundMessage) -> DeliveryReceipt:
        mid = f"mock_{uuid.uuid4().hex[:16]}"
        self.outbox.append({
            "platform": self.platform.value, "recipient": message.recipient_id,
            "text": message.text, "id": mid, "at": datetime.now(UTC).isoformat(),
        })
        log.info("mock_send", platform=self.platform.value, recipient=message.recipient_id)
        return DeliveryReceipt(accepted=True, external_message_id=mid, status="sent")

    async def publish_post(self, *, body: str, media_urls: list[str] | None = None,
                           **kwargs: Any) -> DeliveryReceipt:
        pid = f"mock_post_{uuid.uuid4().hex[:12]}"
        self.outbox.append({"platform": self.platform.value, "post": body, "id": pid})
        return DeliveryReceipt(accepted=True, external_message_id=pid, status="sent")
