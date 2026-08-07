"""WhatsApp Cloud API adapter (Meta Graph API).

Status
------
Webhook parsing and signature verification are implemented and unit-tested
against captured payloads in ``n8n/test-payloads/``. Outbound sending is
implemented against the documented Graph endpoint but is **not verified
end-to-end** in this build — it needs a live Business account. Setup steps
are in ``docs/integrations.md``. With no token configured the adapter refuses
to send rather than pretending success.

Reference: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import verify_meta_signature
from app.integrations.base import (
    ChannelAdapter,
    DeliveryReceipt,
    OutboundMessage,
    StatusUpdate,
    UnifiedAttachment,
    UnifiedMessage,
)
from app.models.enums import MessageType, Platform

log = get_logger("integrations.whatsapp")

# WhatsApp message type -> our internal vocabulary.
_TYPE_MAP: dict[str, MessageType] = {
    "text": MessageType.TEXT,
    "image": MessageType.IMAGE,
    "video": MessageType.VIDEO,
    "audio": MessageType.AUDIO,
    "voice": MessageType.AUDIO,
    "document": MessageType.DOCUMENT,
    "sticker": MessageType.STICKER,
    "location": MessageType.LOCATION,
    "reaction": MessageType.REACTION,
}

_MEDIA_TYPES = {"image", "video", "audio", "voice", "document", "sticker"}


class WhatsAppAdapter(ChannelAdapter):
    platform = Platform.WHATSAPP

    def __init__(
        self,
        *,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        app_secret: str | None = None,
        verify_token: str | None = None,
    ) -> None:
        self.access_token = access_token or settings.whatsapp_access_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.app_secret = app_secret or settings.whatsapp_app_secret
        self.verify_token = verify_token or settings.whatsapp_verify_token
        self.api_version = settings.meta_graph_api_version
        self.is_live = bool(self.access_token and self.phone_number_id)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "receive_messages": True,
            "send_messages": True,
            "publish_content": False,     # WhatsApp has no feed to post to
            "delivery_receipts": True,
            "media": True,
        }

    # ── Inbound ──────────────────────────────────────────────────────────

    def verify_challenge(self, params: dict[str, str]) -> str | None:
        """Meta's GET handshake: echo hub.challenge iff the verify token matches."""
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token")
            and params.get("hub.verify_token") == self.verify_token
        ):
            return params.get("hub.challenge")
        return None

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        header = headers.get("x-hub-signature-256") or headers.get("X-Hub-Signature-256")
        return verify_meta_signature(raw_body, header, self.app_secret)

    def parse_webhook(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        out: list[UnifiedMessage] = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}
                # Contact profile names arrive alongside, keyed by wa_id.
                profiles = {
                    c.get("wa_id"): (c.get("profile") or {}).get("name")
                    for c in value.get("contacts", []) or []
                }
                for raw in value.get("messages", []) or []:
                    parsed = self._parse_one(raw, profiles)
                    if parsed is not None:
                        out.append(parsed)
        return out

    def _parse_one(self, raw: dict[str, Any], profiles: dict[str, str]) -> UnifiedMessage | None:
        wa_id = raw.get("from")
        msg_id = raw.get("id")
        if not wa_id or not msg_id:
            log.warning("whatsapp_message_missing_ids", keys=list(raw))
            return None

        wa_type = raw.get("type", "text")
        message_type = _TYPE_MAP.get(wa_type, MessageType.UNSUPPORTED)

        text: str | None = None
        attachments: list[UnifiedAttachment] = []

        if wa_type == "text":
            text = (raw.get("text") or {}).get("body")
        elif wa_type in _MEDIA_TYPES:
            media = raw.get(wa_type) or {}
            text = media.get("caption")
            attachments.append(
                UnifiedAttachment(
                    kind=message_type,
                    external_media_id=media.get("id"),
                    mime_type=media.get("mime_type"),
                    file_name=media.get("filename"),
                    caption=media.get("caption"),
                )
            )
        elif wa_type == "location":
            loc = raw.get("location") or {}
            text = loc.get("name") or f"{loc.get('latitude')},{loc.get('longitude')}"
        elif wa_type == "reaction":
            text = (raw.get("reaction") or {}).get("emoji")
        elif wa_type == "interactive":
            # Button / list replies carry the user's choice as their "text".
            inter = raw.get("interactive") or {}
            payload_ = inter.get("button_reply") or inter.get("list_reply") or {}
            text = payload_.get("title")
            message_type = MessageType.TEXT
        else:
            log.info("whatsapp_unsupported_type", type=wa_type)

        # WhatsApp sends a unix timestamp as a string.
        try:
            ts = datetime.fromtimestamp(int(raw.get("timestamp", 0)), tz=UTC)
        except (TypeError, ValueError):
            ts = datetime.now(UTC)

        return UnifiedMessage(
            platform=self.platform,
            external_user_id=wa_id,
            # WhatsApp has no thread id — the phone number is the thread.
            conversation_id=wa_id,
            external_message_id=msg_id,
            sender_name=profiles.get(wa_id),
            text=text,
            message_type=message_type,
            attachments=attachments,
            timestamp=ts,
            contact_phone=wa_id,
            raw=raw,
        )

    def parse_status_updates(self, payload: dict[str, Any]) -> list[StatusUpdate]:
        updates: list[StatusUpdate] = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                for st in (change.get("value") or {}).get("statuses", []) or []:
                    status = st.get("status")
                    if status not in {"sent", "delivered", "read", "failed"}:
                        continue
                    try:
                        ts = datetime.fromtimestamp(int(st.get("timestamp", 0)), tz=UTC)
                    except (TypeError, ValueError):
                        ts = datetime.now(UTC)
                    errors = st.get("errors") or []
                    updates.append(
                        StatusUpdate(
                            platform=self.platform,
                            external_message_id=st.get("id", ""),
                            status=status,
                            timestamp=ts,
                            error=errors[0].get("title") if errors else None,
                        )
                    )
        return updates

    # ── Outbound ─────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        reraise=True,
    )
    async def send_message(self, message: OutboundMessage) -> DeliveryReceipt:
        if not self.is_live:
            return DeliveryReceipt(
                accepted=False,
                status="failed",
                error=(
                    "WhatsApp is not configured. Set WHATSAPP_ACCESS_TOKEN and "
                    "WHATSAPP_PHONE_NUMBER_ID, or use the mock adapter."
                ),
            )

        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": message.recipient_id,
            "type": "text",
            "text": {"preview_url": False, "body": message.text or ""},
        }
        if message.reply_to_external_id:
            body["context"] = {"message_id": message.reply_to_external_id}

        url = f"{self.base_url}/{self.phone_number_id}/messages"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )

        if resp.status_code >= 400:
            detail = _graph_error(resp)
            log.error("whatsapp_send_failed", status=resp.status_code, detail=detail)
            return DeliveryReceipt(accepted=False, status="failed", error=detail)

        data = resp.json()
        sent_id = (data.get("messages") or [{}])[0].get("id")
        return DeliveryReceipt(
            accepted=True, external_message_id=sent_id, status="sent", raw=data
        )

    async def resolve_media_url(self, media_id: str) -> str | None:
        """Exchange a media id for a short-lived download URL."""
        if not self.is_live:
            return None
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self.base_url}/{media_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        return resp.json().get("url") if resp.status_code < 400 else None


def _graph_error(resp: httpx.Response) -> str:
    """Pull the human-readable message out of a Graph API error body."""
    try:
        err = resp.json().get("error", {})
        return err.get("message") or resp.text[:300]
    except Exception:  # noqa: BLE001 - error path must never raise
        return resp.text[:300]
