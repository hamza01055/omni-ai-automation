"""Structured JSON logging with request-scoped context.

Every log line carries request_id / organization_id / user_id when they are
known, so a single automation run can be traced end to end across FastAPI and
n8n. Secrets are scrubbed by `_redact` before anything is emitted.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
organization_id_ctx: ContextVar[str | None] = ContextVar("organization_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

# Any key containing one of these substrings is never written to logs.
_SENSITIVE = (
    "password", "secret", "token", "api_key", "apikey", "authorization",
    "credential", "encryption_key", "access_token", "refresh_token",
)


def _redact(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    for key in list(event):
        if any(marker in key.lower() for marker in _SENSITIVE):
            event[key] = "[redacted]"
    return event


def _bind_context(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    for key, var in (
        ("request_id", request_id_ctx),
        ("organization_id", organization_id_ctx),
        ("user_id", user_id_ctx),
    ):
        value = var.get()
        if value and key not in event:
            event[key] = value
    return event


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            _bind_context,
            _redact,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "omni") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
