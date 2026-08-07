"""Operator commands.  Usage:  python -m app.cli seed"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.models import (
    Contact, Conversation, Lead, Message, Organization, OrganizationMember, User, Workflow,
)
from app.models.enums import (
    ConversationStatus, Intent, LeadStatus, MessageDirection, MessageStatus,
    MessageType, Platform, Role, SenderType,
)
from app.services.auth_service import slugify

log = get_logger("cli")

DEMO_PASSWORD = "OmniDemo!2026"   # noqa: S105 - local demo data only

WORKFLOWS = [
    ("WF-01", "WhatsApp Incoming", "incoming"),
    ("WF-02", "Instagram Incoming", "incoming"),
    ("WF-03", "Facebook Incoming", "incoming"),
    ("WF-04", "X Mentions & DMs", "incoming"),
    ("WF-10", "AI Router", "ai"),
    ("WF-20", "Lead Follow-up", "sales"),
    ("WF-30", "Content Generation", "content"),
    ("WF-40", "Scheduled Publishing", "publishing"),
    ("WF-90", "Error Handler", "monitoring"),
]

CONVERSATIONS = [
    (Platform.INSTAGRAM, "ig_88213", "Ahmed Raza", "What are your prices for the automation package?", Intent.PRICING, 87),
    (Platform.WHATSAPP, "923001234567", "Sarah Malik", "Hi, my last invoice looks wrong. Can someone check?", Intent.COMPLAINT, 0),
    (Platform.FACEBOOK, "fb_44120", "Ali Hassan", "Do you integrate with Shopify?", Intent.PRODUCT_QUESTION, 41),
    (Platform.X, "x_7781", "Nadia K", "Booking a demo for next week — who do I talk to?", Intent.BOOKING, 72),
]


async def seed() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(Organization).where(Organization.slug == "demo-co")):
            log.info("seed_skipped", reason="demo workspace already exists")
            return

        org = Organization(name="Demo Co", slug=slugify("demo-co"))
        db.add(org)
        await db.flush()

        for email, name, role in [
            ("owner@demo.co", "Zara Owner", Role.OWNER),
            ("agent@demo.co", "Bilal Agent", Role.AGENT),
        ]:
            user = User(email=email, full_name=name,
                        hashed_password=hash_password(DEMO_PASSWORD))
            db.add(user)
            await db.flush()
            db.add(OrganizationMember(organization_id=org.id, user_id=user.id,
                                      role=role, is_default=True))

        for code, name, category in WORKFLOWS:
            db.add(Workflow(organization_id=org.id, code=code, name=name, category=category))

        now = datetime.now(UTC)
        for i, (platform, ext_id, name, text, intent, score) in enumerate(CONVERSATIONS):
            contact = Contact(organization_id=org.id, platform=platform,
                              external_user_id=ext_id, display_name=name)
            db.add(contact)
            await db.flush()

            sent_at = now - timedelta(hours=i * 3 + 1)
            conv = Conversation(
                organization_id=org.id, contact_id=contact.id, platform=platform,
                external_conversation_id=ext_id, status=ConversationStatus.OPEN,
                last_intent=intent, last_confidence=0.93 - i * 0.09,
                unread_count=1, message_count=1, last_message_at=sent_at,
            )
            db.add(conv)
            await db.flush()

            db.add(Message(
                organization_id=org.id, conversation_id=conv.id, contact_id=contact.id,
                platform=platform, external_message_id=f"seed_{ext_id}_1",
                direction=MessageDirection.INBOUND, sender_type=SenderType.CONTACT,
                sender_name=name, message_type=MessageType.TEXT, text=text,
                status=MessageStatus.DELIVERED, sent_at=sent_at,
            ))

            if score:
                db.add(Lead(
                    organization_id=org.id, contact_id=contact.id, conversation_id=conv.id,
                    name=name, source_platform=platform, score=score,
                    status=LeadStatus.QUALIFIED if score > 70 else LeadStatus.NEW,
                    interest="AI automation", last_contact_at=sent_at,
                ))

        await db.commit()
        log.info("seed_complete", organization=org.name)
        print(f"\nSeeded workspace 'Demo Co'.\n  owner@demo.co / {DEMO_PASSWORD}\n"
              f"  agent@demo.co / {DEMO_PASSWORD}\n")


def main() -> None:
    configure_logging()
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command == "seed":
        asyncio.run(seed())
    else:
        print("Commands: seed")


if __name__ == "__main__":
    main()
