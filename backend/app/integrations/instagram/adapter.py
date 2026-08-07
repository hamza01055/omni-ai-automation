"""Instagram adapter (Messenger Platform for Instagram + Content Publishing API).

Status
------
Webhook parsing and signature verification are implemented. Sending DMs and
publishing media are implemented against Meta's documented endpoints but are
unverified without a live Instagram Professional account linked to a Facebook
Page. See docs/integrations.md for the exact permissions required
(instagram_basic, instagram_manage_messages, instagram_content_publish).

Note: Instagram content publishing is a two-step create-container/publish
flow and requires a publicly reachable image URL — it cannot accept raw bytes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import verify_meta_signature
from app.integrations.base import (
    ChannelAdapter, DeliveryReceipt, OutboundMessage,
    UnifiedAttachment, UnifiedMessage,
)
from app.models.enums import MessageType, Platform

log = get_logger("integrations.instagram")


class InstagramAdapter(ChannelAdapter):
    platform = Platform.INSTAGRAM

    def __init__(self, *, access_token: str | None = None,
                 ig_user_id: str | None = None, app_secret: str | None = None,
                 verify_token: str | None = None) -> None:
        self.access_token = access_token or settings.instagram_access_token
        self.ig_user_id = ig_user_id or settings.instagram_business_account_id
        self.app_secret = app_secret or settings.meta_app_secret
        self.verify_token = verify_token or settings.meta_verify_token
        self.api_version = settings.meta_graph_api_version
        self.is_live = bool(self.access_token and self.ig_user_id)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {"receive_messages": True, "send_messages": True,
                "publish_content": True, "delivery_receipts": False, "media": True}

    def verify_challenge(self, params: dict[str, str]) -> str | None:
        if (params.get("hub.mode") == "subscribe"
                and params.get("hub.verify_token") == self.verify_token
                and self.verify_token):
            return params.get("hub.challenge")
        return None

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        header = headers.get("x-hub-signature-256") or headers.get("X-Hub-Signature-256")
        return verify_meta_signature(raw_body, header, self.app_secret)

    def parse_webhook(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        """Handle `messaging` events (DMs) and `changes` events (comments)."""
        out: list[UnifiedMessage] = []
        for entry in payload.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                parsed = self._parse_dm(event)
                if parsed:
                    out.append(parsed)
            for change in entry.get("changes", []) or []:
                if change.get("field") == "comments":
                    parsed = self._parse_comment(change.get("value") or {})
                    if parsed:
                        out.append(parsed)
        return out

    def _parse_dm(self, event: dict[str, Any]) -> UnifiedMessage | None:
        msg = event.get("message") or {}
        # Echoes are our own outbound messages coming back; ignore them.
        if msg.get("is_echo"):
            return None
        sender = (event.get("sender") or {}).get("id")
        mid = msg.get("mid")
        if not sender or not mid:
            return None

        attachments: list[UnifiedAttachment] = []
        message_type = MessageType.TEXT
        for att in msg.get("attachments", []) or []:
            kind = {
                "image": MessageType.IMAGE, "video": MessageType.VIDEO,
                "audio": MessageType.AUDIO, "file": MessageType.DOCUMENT,
                "story_mention": MessageType.IMAGE, "share": MessageType.DOCUMENT,
            }.get(att.get("type", ""), MessageType.UNSUPPORTED)
            message_type = kind
            attachments.append(
                UnifiedAttachment(kind=kind, url=(att.get("payload") or {}).get("url"))
            )

        ts_ms = event.get("timestamp") or 0
        return UnifiedMessage(
            platform=self.platform,
            external_user_id=str(sender),
            conversation_id=str(sender),   # IG threads are per-user
            external_message_id=str(mid),
            text=msg.get("text"),
            message_type=message_type,
            attachments=attachments,
            timestamp=datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC)
            if ts_ms else datetime.now(UTC),
            raw=event,
        )

    def _parse_comment(self, value: dict[str, Any]) -> UnifiedMessage | None:
        from_ = value.get("from") or {}
        cid = value.get("id")
        if not cid or not from_.get("id"):
            return None
        return UnifiedMessage(
            platform=self.platform,
            external_user_id=str(from_["id"]),
            conversation_id=f"comment:{value.get('media', {}).get('id', cid)}",
            external_message_id=str(cid),
            sender_name=from_.get("username"),
            contact_handle=from_.get("username"),
            text=value.get("text"),
            message_type=MessageType.TEXT,
            timestamp=datetime.now(UTC),
            raw=value,
        )

    async def send_message(self, message: OutboundMessage) -> DeliveryReceipt:
        if not self.is_live:
            return DeliveryReceipt(
                accepted=False, status="failed",
                error="Instagram is not configured. Set INSTAGRAM_ACCESS_TOKEN "
                      "and INSTAGRAM_BUSINESS_ACCOUNT_ID.",
            )
        url = f"{self.base_url}/{self.ig_user_id}/messages"
        body = {"recipient": {"id": message.recipient_id},
                "message": {"text": message.text or ""}}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url, json=body, headers={"Authorization": f"Bearer {self.access_token}"}
            )
        if resp.status_code >= 400:
            return DeliveryReceipt(accepted=False, status="failed", error=resp.text[:300])
        data = resp.json()
        return DeliveryReceipt(accepted=True, external_message_id=data.get("message_id"),
                               status="sent", raw=data)

    async def publish_post(self, *, body: str, media_urls: list[str] | None = None,
                           **kwargs: Any) -> DeliveryReceipt:
        """Two-step publish: create a media container, then publish it.

        Instagram requires at least one image/video; text-only feed posts are
        not supported by the API.
        """
        if not self.is_live:
            return DeliveryReceipt(accepted=False, status="failed",
                                   error="Instagram is not configured.")
        if not media_urls:
            return DeliveryReceipt(
                accepted=False, status="failed",
                error="Instagram feed posts require at least one image or video URL.",
            )
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            create = await client.post(
                f"{self.base_url}/{self.ig_user_id}/media",
                params={"image_url": media_urls[0], "caption": body},
                headers=headers,
            )
            if create.status_code >= 400:
                return DeliveryReceipt(accepted=False, status="failed",
                                       error=create.text[:300])
            container_id = create.json().get("id")

            publish = await client.post(
                f"{self.base_url}/{self.ig_user_id}/media_publish",
                params={"creation_id": container_id}, headers=headers,
            )
        if publish.status_code >= 400:
            return DeliveryReceipt(accepted=False, status="failed", error=publish.text[:300])
        return DeliveryReceipt(accepted=True, external_message_id=publish.json().get("id"),
                               status="sent", raw=publish.json())
