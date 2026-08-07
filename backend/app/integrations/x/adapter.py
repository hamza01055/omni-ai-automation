"""X (Twitter) API v2 adapter.

Status
------
Posting and replying are implemented against ``POST /2/tweets`` using OAuth
1.0a user-context signing (required for write operations). Mention ingestion
uses ``GET /2/users/:id/mentions`` on a schedule rather than webhooks, because
Account Activity API access is a separate, gated product — this is documented
rather than faked. DM ingestion likewise requires elevated access.

Reference: https://docs.x.com/x-api
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import verify_x_signature
from app.integrations.base import (
    ChannelAdapter, DeliveryReceipt, OutboundMessage, UnifiedMessage,
)
from app.models.enums import MessageType, Platform

log = get_logger("integrations.x")

API = "https://api.x.com"
MAX_TWEET_CHARS = 280


class XAdapter(ChannelAdapter):
    platform = Platform.X

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None,
                 access_token: str | None = None, access_secret: str | None = None,
                 bearer_token: str | None = None, webhook_secret: str | None = None) -> None:
        self.api_key = api_key or settings.x_api_key
        self.api_secret = api_secret or settings.x_api_secret
        self.access_token = access_token or settings.x_access_token
        self.access_secret = access_secret or settings.x_access_secret
        self.bearer_token = bearer_token or settings.x_bearer_token
        self.webhook_secret = webhook_secret or settings.x_webhook_secret
        self.is_live = all([self.api_key, self.api_secret,
                            self.access_token, self.access_secret])

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "receive_messages": bool(self.bearer_token),  # polling, not push
            "send_messages": self.is_live,
            "publish_content": self.is_live,
            "delivery_receipts": False,
            "media": False,   # media upload uses the v1.1 endpoint; out of scope here
        }

    # ── OAuth 1.0a signing (required for write endpoints) ────────────────

    def _oauth_header(self, method: str, url: str,
                      params: dict[str, str] | None = None) -> str:
        oauth = {
            "oauth_consumer_key": self.api_key,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.access_token,
            "oauth_version": "1.0",
        }
        signing = {**oauth, **(params or {})}
        encoded = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted(signing.items())
        )
        base = "&".join([
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(encoded, safe=""),
        ])
        key = f"{urllib.parse.quote(self.api_secret, safe='')}&" \
              f"{urllib.parse.quote(self.access_secret, safe='')}"
        signature = base64.b64encode(
            hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
        ).decode()
        oauth["oauth_signature"] = signature
        return "OAuth " + ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth.items())
        )

    # ── Inbound ──────────────────────────────────────────────────────────

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        header = headers.get("x-twitter-webhooks-signature") or headers.get("x-signature")
        return verify_x_signature(raw_body, header, self.webhook_secret)

    def verify_challenge(self, params: dict[str, str]) -> str | None:
        """X uses a CRC token handshake rather than an echo parameter."""
        crc = params.get("crc_token")
        if not crc or not self.webhook_secret:
            return None
        digest = hmac.new(self.webhook_secret.encode(), crc.encode(), hashlib.sha256).digest()
        return "sha256=" + base64.b64encode(digest).decode()

    def parse_webhook(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        """Parse Account Activity events: DMs and mention tweets."""
        out: list[UnifiedMessage] = []
        users = payload.get("users", {}) or {}

        for ev in payload.get("direct_message_events", []) or []:
            msg = (ev.get("message_create") or {})
            sender = (msg.get("sender_id") or "")
            text = ((msg.get("message_data") or {}).get("text"))
            eid = ev.get("id")
            if not (sender and eid):
                continue
            profile = users.get(sender, {})
            out.append(UnifiedMessage(
                platform=self.platform, external_user_id=str(sender),
                conversation_id=f"dm:{sender}", external_message_id=str(eid),
                sender_name=profile.get("name"), contact_handle=profile.get("screen_name"),
                text=text, message_type=MessageType.TEXT,
                timestamp=_ms_to_dt(ev.get("created_timestamp")), raw=ev,
            ))

        for tw in payload.get("tweet_create_events", []) or []:
            user = tw.get("user") or {}
            uid, tid = user.get("id_str"), tw.get("id_str")
            if not (uid and tid):
                continue
            out.append(UnifiedMessage(
                platform=self.platform, external_user_id=str(uid),
                conversation_id=f"thread:{tw.get('conversation_id', tid)}",
                external_message_id=str(tid),
                sender_name=user.get("name"), contact_handle=user.get("screen_name"),
                text=tw.get("text"), message_type=MessageType.TEXT,
                timestamp=datetime.now(UTC), raw=tw,
            ))
        return out

    async def fetch_mentions(self, user_id: str, since_id: str | None = None
                             ) -> list[UnifiedMessage]:
        """Poll recent mentions. Used by the scheduled n8n workflow WF-04."""
        if not self.bearer_token:
            return []
        params: dict[str, Any] = {
            "max_results": 25,
            "tweet.fields": "created_at,conversation_id,author_id",
            "expansions": "author_id",
            "user.fields": "name,username,profile_image_url",
        }
        if since_id:
            params["since_id"] = since_id
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{API}/2/users/{user_id}/mentions", params=params,
                headers={"Authorization": f"Bearer {self.bearer_token}"},
            )
        if resp.status_code >= 400:
            log.error("x_mentions_failed", status=resp.status_code, body=resp.text[:200])
            return []
        data = resp.json()
        authors = {u["id"]: u for u in (data.get("includes", {}).get("users") or [])}
        result = []
        for tw in data.get("data", []) or []:
            author = authors.get(tw.get("author_id"), {})
            result.append(UnifiedMessage(
                platform=self.platform, external_user_id=str(tw.get("author_id")),
                conversation_id=f"thread:{tw.get('conversation_id', tw['id'])}",
                external_message_id=str(tw["id"]),
                sender_name=author.get("name"), contact_handle=author.get("username"),
                contact_avatar_url=author.get("profile_image_url"),
                text=tw.get("text"), message_type=MessageType.TEXT,
                timestamp=_iso_to_dt(tw.get("created_at")), raw=tw,
            ))
        return result

    # ── Outbound ─────────────────────────────────────────────────────────

    async def send_message(self, message: OutboundMessage) -> DeliveryReceipt:
        """Replies are public tweets in-thread. X DMs need elevated access."""
        return await self._post_tweet(
            message.text or "", reply_to=message.reply_to_external_id
        )

    async def publish_post(self, *, body: str, media_urls: list[str] | None = None,
                           **kwargs: Any) -> DeliveryReceipt:
        return await self._post_tweet(body)

    async def _post_tweet(self, text: str, reply_to: str | None = None) -> DeliveryReceipt:
        if not self.is_live:
            return DeliveryReceipt(
                accepted=False, status="failed",
                error="X is not configured. Set X_API_KEY, X_API_SECRET, "
                      "X_ACCESS_TOKEN and X_ACCESS_SECRET.",
            )
        if len(text) > MAX_TWEET_CHARS:
            return DeliveryReceipt(
                accepted=False, status="failed",
                error=f"Post is {len(text)} characters; X allows {MAX_TWEET_CHARS}.",
            )
        url = f"{API}/2/tweets"
        payload: dict[str, Any] = {"text": text}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url, json=payload,
                headers={"Authorization": self._oauth_header("POST", url),
                         "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            log.error("x_post_failed", status=resp.status_code, body=resp.text[:200])
            return DeliveryReceipt(accepted=False, status="failed", error=resp.text[:300])
        data = resp.json().get("data", {})
        return DeliveryReceipt(accepted=True, external_message_id=data.get("id"),
                               status="sent", raw=resp.json())


def _ms_to_dt(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _iso_to_dt(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.now(UTC)
