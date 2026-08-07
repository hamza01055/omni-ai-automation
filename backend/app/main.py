"""OmniAI Automation — FastAPI application entrypoint."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import (
    configure_logging,
    get_logger,
    organization_id_ctx,
    request_id_ctx,
    user_id_ctx,
)
from app.core.redis_client import close_redis, get_redis

configure_logging()
log = get_logger("app")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
    storage_uri=settings.redis_url,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", env=settings.app_env, version=app.version)

    if settings.is_production:
        problems = settings.assert_production_ready()
        if problems:
            # Fail loudly rather than serving production traffic insecurely.
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))

    try:
        await get_redis().ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("redis_unavailable_at_startup", error=str(exc))

    yield

    await close_redis()
    log.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    summary="Unified AI automation across WhatsApp, Instagram, Facebook and X.",
    description=(
        "n8n orchestrates the workflows; this API owns the data model, the AI "
        "layer and the dashboard. See /docs for the interactive reference."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Assign a request id, time the request, and log the outcome.

    The id is echoed back in ``X-Request-ID`` and embedded in every log line
    and error body, so a user can quote it and an operator can find the trace.
    """
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request_id_ctx.set(request_id)
    user_id_ctx.set(None)
    organization_id_ctx.set(None)

    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)

    response.headers["X-Request-ID"] = request_id
    # Defence in depth: nginx sets these too, but the API is reachable directly
    # in development.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    if not request.url.path.startswith("/health"):
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        429,
        {
            "error": {
                "code": "rate_limited",
                "message": "Too many requests. Slow down and try again shortly.",
                "request_id": request_id_ctx.get(),
            }
        },
        headers={"Retry-After": "60"},
    )


register_error_handlers(app)

app.include_router(health.router)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs", "health": "/health/ready"}
