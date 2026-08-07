"""Import every model so Alembic autogenerate and SQLAlchemy see them all."""

from app.models.base import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.business import (
    AIAgent,
    AIPrompt,
    AIRun,
    AnalyticsEvent,
    ApprovalRequest,
    AuditLog,
    Campaign,
    ContentPost,
    ContentVariant,
    KnowledgeChunk,
    KnowledgeDocument,
    Lead,
    LeadActivity,
    Notification,
    Workflow,
    WorkflowRun,
)
from app.models.enums import (
    ALWAYS_ESCALATE,
    ApprovalStatus,
    ContentStatus,
    ConversationStatus,
    DocumentStatus,
    Intent,
    LeadStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
    Platform,
    Role,
    RouterAction,
    RunStatus,
    SenderType,
)
from app.models.identity import Organization, OrganizationMember, RefreshSession, User
from app.models.messaging import (
    Channel,
    ChannelCredential,
    Contact,
    Conversation,
    Message,
    MessageAttachment,
)

__all__ = [
    "ALWAYS_ESCALATE", "AIAgent", "AIPrompt", "AIRun", "AnalyticsEvent",
    "ApprovalRequest", "ApprovalStatus", "AuditLog", "Campaign", "Channel",
    "ChannelCredential", "Contact", "ContentPost", "ContentStatus",
    "ContentVariant", "Conversation", "ConversationStatus", "DocumentStatus",
    "Intent", "KnowledgeChunk", "KnowledgeDocument", "Lead", "LeadActivity",
    "LeadStatus", "Message", "MessageAttachment", "MessageDirection",
    "MessageStatus", "MessageType", "Notification", "Organization",
    "OrganizationMember", "OrgScopedMixin", "Platform", "RefreshSession",
    "Role", "RouterAction", "RunStatus", "SenderType", "TimestampMixin",
    "User", "UUIDPrimaryKeyMixin", "Workflow", "WorkflowRun",
]
