"""Authentication request/response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import Role
from app.schemas.common import ORMModel

MIN_PASSWORD_LENGTH = 12


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)
    organization_name: str = Field(min_length=1, max_length=160)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        # Length is the dominant factor; require a little variety on top of it.
        if v.isalpha() or v.isdigit():
            raise ValueError("Use a mix of letters, numbers or symbols.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    organization_id: uuid.UUID | None = Field(
        default=None, description="Required only when the user belongs to several workspaces."
    )


class RefreshRequest(BaseModel):
    refresh_token: str


class OrganizationSummary(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    role: Role | None = None


class UserProfile(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    avatar_url: str | None = None
    last_login_at: datetime | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class AuthSession(BaseModel):
    tokens: TokenPair
    user: UserProfile
    organization: OrganizationSummary
    role: Role
    organizations: list[OrganizationSummary] = []


class MeResponse(BaseModel):
    user: UserProfile
    organization: OrganizationSummary
    role: Role
    organizations: list[OrganizationSummary] = []
