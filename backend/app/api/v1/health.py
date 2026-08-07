"""Liveness and readiness probes.

`/health/live` answers as long as the process is up. `/health/ready` actually
touches Postgres and Redis, because Compose and any orchestrator should not
route traffic here until dependencies respond.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.api.deps import DbDep
from app.core.config import settings
from app.core.redis_client import get_redis
from app.integrations.registry import channel_status

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "env": settings.app_env}


@router.get("/health/ready")
async def ready(db: DbDep, response: Response) -> dict[str, object]:
    checks: dict[str, object] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - probe reports, never raises
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if healthy else "degraded",
        "checks": checks,
        "channels": channel_status(),
        "warnings": settings.assert_production_ready() if settings.is_production else [],
    }
