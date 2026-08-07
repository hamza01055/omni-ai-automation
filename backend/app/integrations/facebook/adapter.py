"""Facebook Page adapter (Messenger Platform + Page feed publishing).

Status
------
Webhook parsing and signature verification are implemented. Message sending
and feed publishing follow Meta's documented endpoints; both require a Page
access token with pages_messaging and pages_manage_posts. Unverified without
a live Page — see docs/integrations.md.
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

log = get_logger("integrations.facebook")


class FacebookAdapter(ChannelAdapter):
    platform = Platform.FACEBOOK

    def __init__(self, *, access_token: str | None = None, page_id: str | None = None,
                 app_secret: str | None = None, verify_token: str | None = None) -> None:
        self.access_token = access_token or settings.facebook_access_token
        self.page_id = page_id or settings.facebook_page_id
        self.app_secret = app_secret or settings.meta_app_secret
        self.verify_token = verify_token or settings.meta_verify_token
        self.api_version = settings.meta_graph_api_version
        self.is_live = bool(self.access_token and self.page_id)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {"receive_messages": True, "send_messages": True,
                "publish_content": True, "delivery_receipts": True, "media": True}

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
        out: list[UnifiedMessage] = []
        for entry in payload.get("entry", []) or []:
            page_id = str(entry.get("id", ""))
            for event in entry.get("messaging", []) or []:
                msg = event.get("message") or {}
                if msg.get("is_echo"):
                    continue
                sender = (event.get("sender") or {}).get("id")
                mid = msg.get("mid")
                if not sender or not mid:
                    continue
                # Skip our own page's messages if they arrive as sender.
                if page_id and str(sender) == page_id:
                    continue

                attachments = [
                    UnifiedAttachment(
                        kind={"image": MessageType.IMAGE, "video": MessageType.VIDEO,
                              "audio": MessageType.AUDIO, "file": MessageType.DOCUMENT}
                        .get(a.get("type", ""), MessageType.UNSUPPORTED),
                        url=(a.get("payload") or {}).get("url"),
                    )
                    for a in msg.get("attachments", []) or []
                ]
                ts_ms = event.get("timestamp") or 0
                out.append(UnifiedMessage(
                    platform=self.platform,
                    external_user_id=str(sender),
                    conversation_id=str(sender),
                    external_message_id=str(mid),
                    text=msg.get("text"),
                    message_type=attachments[0].kind if attachments else MessageType.TEXT,
                    attachments=attachments,
                    timestamp=datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC)
                    if ts_ms else datetime.now(UTC),
                    raw=event,
                ))
        return out

    async def send_message(self, message: OutboundMessage) -> DeliveryReceipt:
        if not self.is_live:
            return DeliveryReceipt(
                accepted=False, status="failed",
                error="Facebook is not configured. Set FACEBOOK_ACCESS_TOKEN and FACEBOOK_PAGE_ID.",
            )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.base_url}/{self.page_id}/messages",
                params={"access_token": self.access_token},
                json={"recipient": {"id": message.recipient_id},
                      "messaging_type": "RESPONSE",
                      "message": {"text": message.text or ""}},
            )
        if resp.status_code >= 400:
            return DeliveryReceipt(accepted=False, status="failed", error=resp.text[:300])
        data = resp.json()
        return DeliveryReceipt(accepted=True, external_message_id=data.get("message_id"),
                               status="sent", raw=data)

    async def publish_post(self, *, body: str, media_urls: list[str] | None = None,
                           **kwargs: Any) -> DeliveryReceipt:
        if not self.is_live:
            return DeliveryReceipt(accepted=False, status="failed",
                                   error="Facebook is not configured.")
        endpoint = "photos" if media_urls else "feed"
        params: dict[str, Any] = {"access_token": self.access_token}
        params["caption" if media_urls else "message"] = body
        if media_urls:
            params["url"] = media_urls[0]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/{self.page_id}/{endpoint}", params=params)
        if resp.status_code >= 400:
            return DeliveryReceipt(accepted=False, status="failed", error=resp.text[:300])
        data = resp.json()
        return DeliveryReceipt(accepted=True,
                               external_message_id=data.get("post_id") or data.get("id"),
                               status="sent", raw=data)
