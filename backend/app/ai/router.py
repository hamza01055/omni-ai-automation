"""The AI router — the first decision made about every inbound message.

Design stance
-------------
The model classifies. It does not decide policy. It returns an intent, a
confidence, and a lead score; **this module** then decides whether a human is
needed, using rules that live in code where they can be read, tested, and
changed without touching a prompt.

That separation matters because a model asked "should a human handle this?"
will answer inconsistently under paraphrase, and because the refund/complaint
escalation rule is a business commitment, not a preference to be negotiated
with a language model. If the model says a refund dispute needs no human, it
is overruled.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIClient, AIUnavailableError, Completion, record_run
from app.core.config import settings
from app.core.logging import get_logger
from app.models import Conversation, Message
from app.models.enums import (
    ALWAYS_ESCALATE,
    Intent,
    MessageDirection,
    Platform,
    RouterAction,
    RunStatus,
)

log = get_logger("ai.router")

AGENT_KEY = "router"
HISTORY_LIMIT = 8

ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "confidence", "action", "lead_score", "rationale"],
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in Intent]},
        "confidence": {
            "type": "number",
            "description": "How certain you are of the intent, 0 to 1.",
        },
        "action": {"type": "string", "enum": [a.value for a in RouterAction]},
        "lead_score": {
            "type": "integer",
            "description": "0-100 buying signal. 0 when there is no commercial intent.",
        },
        "rationale": {
            "type": "string",
            "description": "One short sentence explaining the classification.",
        },
    },
}

SYSTEM_PROMPT = """You classify inbound customer messages for a business.

Return the single intent that best fits the customer's most recent message, \
using the conversation history only for context.

Guidance on confidence: report how certain you actually are. A short, clear \
message like "how much is it?" is high confidence. An ambiguous message, a \
message in a language you are unsure of, or one that could fit several intents \
is low confidence. Do not inflate confidence to seem decisive — a low score is \
useful information, not a failure.

Guidance on lead_score (0-100): weigh explicit buying language, specificity \
about needs, urgency, and budget signals. A general question scores low even \
if the tone is warm. Score 0 when there is no commercial intent at all.

Guidance on action:
- answer: the question can be resolved from company knowledge
- qualify: there is buying intent worth pursuing
- escalate: this needs a person
- ignore: spam or an automated message

You are not deciding whether a human reviews this. Classify honestly and let \
the system apply its own policy."""


@dataclass(slots=True)
class RouterDecision:
    intent: Intent
    confidence: float
    action: RouterAction
    lead_score: int
    needs_human: bool
    rationale: str
    escalation_reason: str | None
    ai_run_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": round(self.confidence, 3),
            "action": self.action.value,
            "lead_score": self.lead_score,
            "needs_human": self.needs_human,
            "rationale": self.rationale,
            "escalation_reason": self.escalation_reason,
            "ai_run_id": str(self.ai_run_id) if self.ai_run_id else None,
        }


def apply_escalation_policy(
    intent: Intent, confidence: float, action: RouterAction
) -> tuple[bool, str | None]:
    """Decide whether a person must see this. Returns ``(needs_human, reason)``.

    Pure function, no I/O — this is the rule set the product promises, and it
    should be readable and testable on its own.
    """
    if intent in ALWAYS_ESCALATE:
        return True, f"{intent.value.replace('_', ' ').capitalize()} always goes to a person."

    if action is RouterAction.ESCALATE:
        return True, "The classifier judged this beyond automated handling."

    if confidence < settings.ai_review_threshold:
        return True, (
            f"Confidence {confidence:.2f} is below the "
            f"{settings.ai_review_threshold:.2f} threshold for automated replies."
        )

    return False, None


class AIRouter:
    def __init__(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        self.db = db
        self.org_id = organization_id
        self.client = AIClient()

    async def route(
        self, *, conversation: Conversation, message: Message
    ) -> RouterDecision:
        history = await self._history(conversation.id, exclude=message.id)
        user_prompt = self._build_prompt(conversation.platform, history, message)

        try:
            completion = await self.client.structured(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                schema=ROUTER_SCHEMA,
                schema_name="router_decision",
                temperature=0.0,
                stub=_stub_decision(message.text or ""),
            )
        except AIUnavailableError as exc:
            # The model being down must never drop a customer message on the
            # floor. Fail closed: unknown intent, straight to a human.
            log.error("router_unavailable", error=str(exc),
                      conversation_id=str(conversation.id))
            run = await record_run(
                self.db, organization_id=self.org_id, agent_key=AGENT_KEY,
                completion=Completion(data={}, model=self.client.model),
                conversation_id=conversation.id, message_id=message.id,
                intent=Intent.UNKNOWN, confidence=0.0, needs_human=True,
                status=RunStatus.FAILED, error=str(exc),
            )
            return RouterDecision(
                intent=Intent.UNKNOWN, confidence=0.0, action=RouterAction.ESCALATE,
                lead_score=0, needs_human=True,
                rationale="Classification was unavailable.",
                escalation_reason="The AI service could not be reached.",
                ai_run_id=run.id,
            )

        decision = self._interpret(completion)

        run = await record_run(
            self.db, organization_id=self.org_id, agent_key=AGENT_KEY,
            completion=completion, conversation_id=conversation.id,
            message_id=message.id, input_summary=message.text,
            intent=decision.intent, confidence=decision.confidence,
            needs_human=decision.needs_human,
        )
        decision.ai_run_id = run.id

        conversation.last_intent = decision.intent
        conversation.last_confidence = decision.confidence

        log.info(
            "routed",
            intent=decision.intent.value,
            confidence=round(decision.confidence, 2),
            needs_human=decision.needs_human,
            stubbed=completion.stubbed,
        )
        return decision

    # ── Internals ────────────────────────────────────────────────────────

    def _interpret(self, completion: Completion) -> RouterDecision:
        data = completion.data
        try:
            intent = Intent(data.get("intent", "unknown"))
        except ValueError:
            intent = Intent.UNKNOWN

        try:
            action = RouterAction(data.get("action", "escalate"))
        except ValueError:
            action = RouterAction.ESCALATE

        # Clamp: a model can return 1.4 or -0.2 despite the schema.
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0)))
        lead_score = max(0, min(100, int(data.get("lead_score", 0) or 0)))

        needs_human, reason = apply_escalation_policy(intent, confidence, action)
        if needs_human:
            action = RouterAction.ESCALATE

        return RouterDecision(
            intent=intent,
            confidence=confidence,
            action=action,
            lead_score=lead_score,
            needs_human=needs_human,
            rationale=str(data.get("rationale", ""))[:300],
            escalation_reason=reason,
        )

    async def _history(
        self, conversation_id: uuid.UUID, *, exclude: uuid.UUID
    ) -> list[Message]:
        rows = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != exclude)
            .order_by(desc(Message.sent_at))
            .limit(HISTORY_LIMIT)
        )
        return list(reversed(rows.scalars().all()))

    @staticmethod
    def _build_prompt(
        platform: Platform, history: list[Message], message: Message
    ) -> str:
        lines = [f"Channel: {platform.value}", ""]
        if history:
            lines.append("Conversation so far:")
            for item in history:
                who = "Customer" if item.direction is MessageDirection.INBOUND else "Business"
                lines.append(f"  {who}: {(item.text or '[no text]')[:400]}")
            lines.append("")
        lines.append("Message to classify:")
        lines.append(f"  Customer: {(message.text or '[no text content]')[:1500]}")
        return "\n".join(lines)


# ── Offline stub ─────────────────────────────────────────────────────────

_KEYWORDS: list[tuple[tuple[str, ...], Intent, float, int]] = [
    (("refund", "money back", "chargeback"), Intent.REFUND, 0.88, 0),
    (("complaint", "terrible", "awful", "wrong", "angry", "unacceptable"),
     Intent.COMPLAINT, 0.82, 0),
    (("price", "pricing", "cost", "how much", "quote", "rate"), Intent.PRICING, 0.91, 55),
    (("buy", "purchase", "sign up", "get started", "onboard"),
     Intent.PURCHASE_INTENT, 0.90, 82),
    (("demo", "book", "meeting", "schedule", "appointment"), Intent.BOOKING, 0.87, 71),
    (("integrate", "support", "does it", "can it", "feature", "work with"),
     Intent.PRODUCT_QUESTION, 0.86, 35),
]


def _stub_decision(text: str) -> dict[str, Any]:
    """Deterministic classification used when no API key is configured.

    Keyword matching, openly so. It exists to make the pipeline runnable
    offline, not to approximate a model.
    """
    lowered = text.lower()
    for needles, intent, confidence, score in _KEYWORDS:
        if any(needle in lowered for needle in needles):
            action = (
                RouterAction.QUALIFY if score >= 60
                else RouterAction.ESCALATE if intent in ALWAYS_ESCALATE
                else RouterAction.ANSWER
            )
            return {
                "intent": intent.value,
                "confidence": confidence,
                "action": action.value,
                "lead_score": score,
                "rationale": f"Stub classifier matched a {intent.value} keyword.",
            }
    return {
        "intent": Intent.GENERAL.value,
        "confidence": 0.55,
        "action": RouterAction.ESCALATE.value,
        "lead_score": 0,
        "rationale": "Stub classifier found no confident match.",
    }
