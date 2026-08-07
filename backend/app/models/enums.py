"""Domain enumerations shared by models, schemas, and the AI layer.

These are the vocabulary of the product. The frontend mirrors them in
`frontend/src/types/domain.ts`; keep both sides in step.
"""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    X = "x"


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    AGENT = "agent"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]


_ROLE_RANK = {
    Role.VIEWER: 0,
    Role.AGENT: 1,
    Role.MANAGER: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    STICKER = "sticker"
    REACTION = "reaction"
    SYSTEM = "system"
    UNSUPPORTED = "unsupported"


class MessageStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class SenderType(StrEnum):
    CONTACT = "contact"
    AI = "ai"
    HUMAN = "human"
    SYSTEM = "system"


class ConversationStatus(StrEnum):
    OPEN = "open"
    PENDING_HUMAN = "pending_human"
    SNOOZED = "snoozed"
    CLOSED = "closed"


class Intent(StrEnum):
    SUPPORT = "support"
    PRICING = "pricing"
    PRODUCT_QUESTION = "product_question"
    PURCHASE_INTENT = "purchase_intent"
    LEAD_GENERATION = "lead_generation"
    COMPLAINT = "complaint"
    REFUND = "refund"
    BOOKING = "booking"
    GENERAL = "general"
    SPAM = "spam"
    UNKNOWN = "unknown"


# Intents that always go to a person regardless of model confidence (spec §16).
ALWAYS_ESCALATE: frozenset[Intent] = frozenset(
    {Intent.REFUND, Intent.COMPLAINT, Intent.UNKNOWN}
)


class RouterAction(StrEnum):
    ANSWER = "answer"
    QUALIFY = "qualify"
    ESCALATE = "escalate"
    IGNORE = "ignore"


class LeadStatus(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    MEETING = "meeting"
    WON = "won"
    LOST = "lost"


class ApprovalStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
