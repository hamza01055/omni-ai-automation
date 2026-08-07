"""Ingestion tests against a real SQLite schema.

pgvector columns are the only Postgres-specific piece, so the knowledge tables
are excluded from the test schema; everything ingestion touches is portable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.integrations.base import StatusUpdate, UnifiedMessage
from app.integrations.whatsapp.adapter import WhatsAppAdapter
from app.models import Message, Organization
from app.models.enums import MessageStatus, MessageType, Platform, SenderType
from app.services.ingestion import IngestionService

SKIP_TABLES = {"knowledge_chunks"}  # pgvector column, not creatable on SQLite


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def org(session):
    organization = Organization(name="Test Co", slug=f"test-{uuid.uuid4().hex[:6]}")
    session.add(organization)
    await session.flush()
    return organization


def unified(text="Hello", message_id="wamid.A1", user="923001234567"):
    return UnifiedMessage(
        platform=Platform.WHATSAPP,
        external_user_id=user,
        conversation_id=user,
        external_message_id=message_id,
        sender_name="Ahmed",
        text=text,
        message_type=MessageType.TEXT,
        timestamp=datetime.now(UTC),
        contact_phone=user,
    )


@pytest.mark.asyncio
class TestIngestion:
    async def test_creates_contact_conversation_and_message(self, session, org):
        result = await IngestionService(session, org.id).ingest(unified())
        assert result.created is True
        assert result.contact.display_name == "Ahmed"
        assert result.conversation.message_count == 1
        assert result.conversation.unread_count == 1
        assert result.message.text == "Hello"
        assert result.message.sender_type is SenderType.CONTACT

    async def test_redelivery_is_idempotent(self, session, org):
        service = IngestionService(session, org.id)
        first = await service.ingest(unified())
        second = await service.ingest(unified())

        assert first.created is True
        assert second.created is False
        assert first.message.id == second.message.id
        # Critically: the counter did not move, so no second AI reply fires.
        assert second.conversation.message_count == 1

    async def test_second_message_reuses_conversation(self, session, org):
        service = IngestionService(session, org.id)
        first = await service.ingest(unified(text="Hi", message_id="wamid.A1"))
        second = await service.ingest(unified(text="Still there?", message_id="wamid.A2"))

        assert first.conversation.id == second.conversation.id
        assert first.contact.id == second.contact.id
        assert second.conversation.message_count == 2

    async def test_different_contacts_get_separate_conversations(self, session, org):
        service = IngestionService(session, org.id)
        a = await service.ingest(unified(message_id="m1", user="111"))
        b = await service.ingest(unified(message_id="m2", user="222"))
        assert a.conversation.id != b.conversation.id

    async def test_organizations_are_isolated(self, session, org):
        other = Organization(name="Other Co", slug="other-co")
        session.add(other)
        await session.flush()

        a = await IngestionService(session, org.id).ingest(unified())
        # Same platform message id, different tenant: must be a distinct row.
        b = await IngestionService(session, other.id).ingest(unified())

        assert a.message.id != b.message.id
        assert b.created is True

    async def test_missing_sender_name_gets_readable_fallback(self, session, org):
        message = unified()
        message.sender_name = None
        result = await IngestionService(session, org.id).ingest(message)
        assert result.contact.display_name == "Whatsapp contact"

    async def test_outbound_clears_unread_and_counts(self, session, org):
        service = IngestionService(session, org.id)
        result = await service.ingest(unified())
        await service.record_outbound(
            conversation=result.conversation,
            text="Our pricing starts at $49.",
            sender_type=SenderType.AI,
            confidence=0.94,
        )
        assert result.conversation.unread_count == 0
        assert result.conversation.message_count == 2

    async def test_status_updates_never_downgrade(self, session, org):
        service = IngestionService(session, org.id)
        result = await service.ingest(unified())
        result.message.status = MessageStatus.READ

        await service.apply_status_updates([
            StatusUpdate(platform=Platform.WHATSAPP, external_message_id="wamid.A1",
                         status="delivered", timestamp=datetime.now(UTC))
        ])
        # Out-of-order receipts are normal; READ must not fall back to DELIVERED.
        assert result.message.status is MessageStatus.READ

    async def test_status_update_upgrades(self, session, org):
        service = IngestionService(session, org.id)
        result = await service.ingest(unified())
        result.message.status = MessageStatus.SENT

        await service.apply_status_updates([
            StatusUpdate(platform=Platform.WHATSAPP, external_message_id="wamid.A1",
                         status="read", timestamp=datetime.now(UTC))
        ])
        assert result.message.status is MessageStatus.READ

    async def test_end_to_end_from_raw_platform_payload(self, session, org):
        """The full path a real webhook takes: raw JSON to stored rows."""
        payload = {
            "entry": [{"changes": [{"value": {
                "contacts": [{"wa_id": "923001234567", "profile": {"name": "Ahmed"}}],
                "messages": [{
                    "from": "923001234567", "id": "wamid.E2E", "timestamp": "1754616600",
                    "type": "text", "text": {"body": "What are your prices?"},
                }],
            }}]}]
        }
        parsed = WhatsAppAdapter(access_token="", phone_number_id="").parse_webhook(payload)
        [result] = await IngestionService(session, org.id).ingest_many(parsed)

        stored = await session.get(Message, result.message.id)
        assert stored is not None
        assert stored.text == "What are your prices?"
        assert stored.platform is Platform.WHATSAPP
        assert stored.organization_id == org.id
