"""Adapter normalization tests.

These are the tests that matter most for the unified message contract: if an
adapter drifts, every downstream layer silently gets the wrong shape.
"""

from __future__ import annotations

import pytest

from app.integrations.base import OutboundMessage
from app.integrations.facebook.adapter import FacebookAdapter
from app.integrations.instagram.adapter import InstagramAdapter
from app.integrations.mock import MockAdapter
from app.integrations.registry import get_adapter
from app.integrations.whatsapp.adapter import WhatsAppAdapter
from app.models.enums import MessageType, Platform

WHATSAPP_TEXT = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "WABA_ID",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": "923001234567", "profile": {"name": "Ahmed"}}],
                "messages": [{
                    "from": "923001234567", "id": "wamid.HBg", "timestamp": "1754616600",
                    "type": "text", "text": {"body": "What are your prices?"},
                }],
            },
        }],
    }],
}

WHATSAPP_IMAGE = {
    "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "923009999999", "profile": {"name": "Sara"}}],
        "messages": [{
            "from": "923009999999", "id": "wamid.IMG", "timestamp": "1754616700",
            "type": "image",
            "image": {"id": "media-123", "mime_type": "image/jpeg", "caption": "Is this it?"},
        }],
    }}]}],
}

WHATSAPP_STATUS = {
    "entry": [{"changes": [{"value": {"statuses": [
        {"id": "wamid.HBg", "status": "delivered", "timestamp": "1754616800"}
    ]}}]}],
}


class TestWhatsAppAdapter:
    adapter = WhatsAppAdapter(access_token="", phone_number_id="")

    def test_text_message_normalized(self):
        [msg] = self.adapter.parse_webhook(WHATSAPP_TEXT)
        assert msg.platform is Platform.WHATSAPP
        assert msg.external_user_id == "923001234567"
        assert msg.external_message_id == "wamid.HBg"
        assert msg.sender_name == "Ahmed"
        assert msg.text == "What are your prices?"
        assert msg.message_type is MessageType.TEXT
        assert msg.contact_phone == "923001234567"
        assert msg.timestamp.year == 2025 or msg.timestamp.year == 2026

    def test_image_message_carries_attachment_and_caption(self):
        [msg] = self.adapter.parse_webhook(WHATSAPP_IMAGE)
        assert msg.message_type is MessageType.IMAGE
        assert msg.text == "Is this it?"
        assert len(msg.attachments) == 1
        assert msg.attachments[0].external_media_id == "media-123"

    def test_status_events_produce_no_messages(self):
        assert self.adapter.parse_webhook(WHATSAPP_STATUS) == []

    def test_status_updates_parsed(self):
        [update] = self.adapter.parse_status_updates(WHATSAPP_STATUS)
        assert update.external_message_id == "wamid.HBg"
        assert update.status == "delivered"

    def test_malformed_payload_does_not_raise(self):
        # Platforms retry forever on 5xx, so a parse must never explode.
        assert self.adapter.parse_webhook({}) == []
        assert self.adapter.parse_webhook({"entry": [{"changes": [{}]}]}) == []
        assert self.adapter.parse_webhook({"entry": [{"changes": [
            {"value": {"messages": [{"type": "text"}]}}
        ]}]}) == []

    def test_idempotency_key_is_stable(self):
        [a] = self.adapter.parse_webhook(WHATSAPP_TEXT)
        [b] = self.adapter.parse_webhook(WHATSAPP_TEXT)
        assert a.idempotency_key == b.idempotency_key == "whatsapp:wamid.HBg"

    def test_challenge_requires_matching_token(self):
        adapter = WhatsAppAdapter(verify_token="expected")
        assert adapter.verify_challenge({
            "hub.mode": "subscribe", "hub.verify_token": "expected", "hub.challenge": "42"
        }) == "42"
        assert adapter.verify_challenge({
            "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"
        }) is None

    @pytest.mark.asyncio
    async def test_send_without_credentials_fails_honestly(self):
        receipt = await self.adapter.send_message(
            OutboundMessage(platform=Platform.WHATSAPP, recipient_id="1", text="hi")
        )
        assert receipt.accepted is False
        assert "not configured" in (receipt.error or "")


class TestInstagramAdapter:
    adapter = InstagramAdapter(access_token="", ig_user_id="")

    def test_dm_normalized(self):
        payload = {"entry": [{"messaging": [{
            "sender": {"id": "ig_88213"}, "recipient": {"id": "page"},
            "timestamp": 1754616600000,
            "message": {"mid": "mid.abc", "text": "Do you ship to Lahore?"},
        }]}]}
        [msg] = self.adapter.parse_webhook(payload)
        assert msg.platform is Platform.INSTAGRAM
        assert msg.external_user_id == "ig_88213"
        assert msg.text == "Do you ship to Lahore?"

    def test_echo_of_our_own_message_ignored(self):
        payload = {"entry": [{"messaging": [{
            "sender": {"id": "page"}, "timestamp": 1754616600000,
            "message": {"mid": "mid.echo", "text": "our reply", "is_echo": True},
        }]}]}
        assert self.adapter.parse_webhook(payload) == []

    def test_comment_event_normalized(self):
        payload = {"entry": [{"changes": [{"field": "comments", "value": {
            "id": "comment_1", "text": "price?",
            "from": {"id": "u9", "username": "nadia"},
            "media": {"id": "media_5"},
        }}]}]}
        [msg] = self.adapter.parse_webhook(payload)
        assert msg.conversation_id == "comment:media_5"
        assert msg.contact_handle == "nadia"


class TestFacebookAdapter:
    def test_page_message_normalized(self):
        adapter = FacebookAdapter(access_token="", page_id="PAGE1")
        payload = {"entry": [{"id": "PAGE1", "messaging": [{
            "sender": {"id": "fb_44120"}, "recipient": {"id": "PAGE1"},
            "timestamp": 1754616600000,
            "message": {"mid": "m_1", "text": "Do you integrate with Shopify?"},
        }]}]}
        [msg] = adapter.parse_webhook(payload)
        assert msg.platform is Platform.FACEBOOK
        assert msg.external_user_id == "fb_44120"

    def test_message_from_our_own_page_ignored(self):
        adapter = FacebookAdapter(access_token="", page_id="PAGE1")
        payload = {"entry": [{"id": "PAGE1", "messaging": [{
            "sender": {"id": "PAGE1"}, "timestamp": 1754616600000,
            "message": {"mid": "m_2", "text": "hello from the page"},
        }]}]}
        assert adapter.parse_webhook(payload) == []


class TestRegistry:
    def test_falls_back_to_mock_without_credentials(self):
        for platform in Platform:
            adapter = get_adapter(platform)
            assert isinstance(adapter, MockAdapter)
            assert adapter.is_live is False

    @pytest.mark.asyncio
    async def test_mock_send_is_recorded_not_pretended_live(self):
        adapter = get_adapter(Platform.WHATSAPP)
        receipt = await adapter.send_message(
            OutboundMessage(platform=Platform.WHATSAPP, recipient_id="923001234567",
                            text="Thanks for reaching out.")
        )
        assert receipt.accepted
        assert receipt.external_message_id.startswith("mock_")
        assert adapter.is_live is False
