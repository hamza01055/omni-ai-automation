"""Shared Redis connection pool.

Used for refresh-token revocation, rate limiting, idempotency keys on inbound
webhooks, and pub/sub fan-out to dashboard WebSocket clients.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import settings

_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
