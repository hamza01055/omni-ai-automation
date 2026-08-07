"""Application settings.

Everything configurable lives here and is read from the environment exactly
once at import time. No module reads ``os.environ`` directly — that keeps
secrets out of scattered call sites and makes tests trivial to override.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────
    app_name: str = "OmniAI Automation"
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # ── Datastores ───────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://omni:omni@postgres:5432/omni"
    database_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = "redis://redis:6379/0"

    # ── Auth ─────────────────────────────────────────────────────
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # Fernet key used to encrypt channel_credentials at rest.
    credential_encryption_key: str = ""

    # Bearer token n8n presents on /api/internal/*.
    internal_service_token: str = ""

    # ── Networking ───────────────────────────────────────────────
    public_base_url: str = "http://localhost:8080"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )
    rate_limit_per_minute: int = 120

    # ── AI ───────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    ai_auto_reply_threshold: float = 0.90
    ai_review_threshold: float = 0.70
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 120
    rag_top_k: int = 5

    # ── n8n ──────────────────────────────────────────────────────
    n8n_webhook_url: str = "http://n8n:5678/"

    # ── Channel credentials ──────────────────────────────────────
    # Blank values are the signal to fall back to that channel's mock
    # adapter, so local development works with zero Meta/X setup.
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    meta_graph_api_version: str = "v21.0"

    instagram_access_token: str = ""
    instagram_business_account_id: str = ""

    facebook_access_token: str = ""
    facebook_page_id: str = ""

    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""
    x_bearer_token: str = ""
    x_webhook_secret: str = ""

    # ── Uploads ──────────────────────────────────────────────────
    upload_dir: str = "/app/uploads"
    max_upload_bytes: int = 25 * 1024 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def assert_production_ready(self) -> list[str]:
        """Return a list of misconfigurations that must not reach production."""
        problems: list[str] = []
        if self.jwt_secret.startswith("dev-only"):
            problems.append("JWT_SECRET is still the development default.")
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be at least 32 characters.")
        if not self.credential_encryption_key:
            problems.append("CREDENTIAL_ENCRYPTION_KEY is not set.")
        if not self.internal_service_token:
            problems.append("INTERNAL_SERVICE_TOKEN is not set.")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS may not be a wildcard in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
