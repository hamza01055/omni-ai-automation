"""Thin OpenAI wrapper with structured output and run accounting.

Two things this layer guarantees for everything above it:

1. **You always get valid, schema-shaped JSON or an explicit failure.** Callers
   never parse free text and never see a raw model string.
2. **Every call is recorded in ``ai_runs``** — model, latency, tokens, output,
   and whether it escalated. That table is the audit trail for "why did the AI
   say that", and it's what the analytics page aggregates.

With no ``OPENAI_API_KEY`` set, the client runs in stub mode: deterministic
keyword-based responses so the whole pipeline is exercisable offline. Stub
responses are labelled ``model="stub"`` in ``ai_runs`` so nobody mistakes a
development run for a real one.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import AIRun
from app.models.enums import Intent, RunStatus

log = get_logger("ai.client")


class AIUnavailableError(RuntimeError):
    """The model could not be reached or returned unusable output."""


@dataclass(slots=True)
class Completion:
    data: dict[str, Any]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    stubbed: bool = False
    raw: str = field(default="", repr=False)


class AIClient:
    """Wraps chat completions with JSON-schema-constrained output."""

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.openai_chat_model
        self.enabled = bool(settings.openai_api_key)

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        temperature: float = 0.2,
        stub: dict[str, Any] | None = None,
    ) -> Completion:
        if not self.enabled:
            if stub is None:
                raise AIUnavailableError(
                    "OPENAI_API_KEY is not set and this call has no stub response."
                )
            return Completion(data=stub, model="stub", stubbed=True)

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=40.0)
        started = time.perf_counter()

        try:
            response = await client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001 - any provider failure is one failure
            log.error("ai_call_failed", model=self.model, error=str(exc))
            raise AIUnavailableError(str(exc)) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        content = response.choices[0].message.content or "{}"

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            # Strict schema mode makes this near-impossible, but a malformed
            # response must fail loudly rather than silently become {}.
            raise AIUnavailableError("Model returned output that was not valid JSON.") from exc

        usage = response.usage
        return Completion(
            data=data,
            model=self.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
            raw=content,
        )


async def record_run(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    agent_key: str,
    completion: Completion,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    input_summary: str | None = None,
    intent: Intent | None = None,
    confidence: float | None = None,
    needs_human: bool = False,
    status: RunStatus = RunStatus.SUCCESS,
    error: str | None = None,
) -> AIRun:
    """Persist one model invocation. Called on both success and failure paths."""
    run = AIRun(
        organization_id=organization_id,
        agent_key=agent_key,
        conversation_id=conversation_id,
        message_id=message_id,
        model=completion.model,
        intent=intent,
        confidence=confidence,
        needs_human=needs_human,
        # Truncated: ai_runs is high-volume and full message bodies already
        # live in the messages table.
        input_summary=(input_summary or "")[:500] or None,
        output=completion.data,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status=status,
        error=error,
    )
    db.add(run)
    await db.flush()
    return run
