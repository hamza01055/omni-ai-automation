"""Authentication and workspace bootstrap.

Refresh tokens rotate on every use: the old jti is denylisted in Redis the
moment a new pair is issued. If a stolen token is replayed after the legitimate
client has already refreshed, the replay fails — and because the jti is also
recorded in Postgres, the attempt is visible in the session list.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models.enums import Role
from app.models.identity import Organization, OrganizationMember, RefreshSession, User
from app.schemas.auth import (
    AuthSession,
    LoginRequest,
    OrganizationSummary,
    RegisterRequest,
    TokenPair,
    UserProfile,
)

log = get_logger("auth")

_DENY_PREFIX = "auth:denylist:"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or uuid.uuid4().hex[:8]


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Registration ─────────────────────────────────────────────────────

    async def register(self, data: RegisterRequest) -> AuthSession:
        existing = await self.db.scalar(select(User).where(User.email == data.email.lower()))
        if existing:
            raise ConflictError("An account with that email already exists.")

        org = Organization(name=data.organization_name, slug=await self._unique_slug(
            slugify(data.organization_name)))
        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
        )
        self.db.add_all([org, user])
        await self.db.flush()

        # First person into a new workspace owns it.
        membership = OrganizationMember(
            organization_id=org.id, user_id=user.id, role=Role.OWNER, is_default=True
        )
        self.db.add(membership)
        await self.db.flush()

        log.info("user_registered", user_id=str(user.id), organization_id=str(org.id))
        return await self._issue(user, org, Role.OWNER)

    async def _unique_slug(self, base: str) -> str:
        slug, n = base, 1
        while await self.db.scalar(select(func.count()).select_from(Organization)
                                   .where(Organization.slug == slug)):
            n += 1
            slug = f"{base}-{n}"
        return slug

    # ── Login ────────────────────────────────────────────────────────────

    async def login(self, data: LoginRequest) -> AuthSession:
        user = await self.db.scalar(select(User).where(User.email == data.email.lower()))

        # Always run a verification so a missing account and a wrong password
        # take the same amount of time.
        stored = user.hashed_password if user else hash_password("placeholder")
        password_ok = verify_password(data.password, stored)

        if not user or not password_ok or not user.is_active:
            raise AuthenticationError("Email or password is incorrect.")

        if password_needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(data.password)

        memberships = await self._memberships(user.id)
        if not memberships:
            raise AuthenticationError("This account is not a member of any workspace.")

        if data.organization_id:
            chosen = next(
                (m for m in memberships if m[0].organization_id == data.organization_id), None
            )
            if chosen is None:
                raise AuthenticationError("You do not have access to that workspace.")
        else:
            chosen = next((m for m in memberships if m[0].is_default), memberships[0])

        membership, org = chosen
        user.last_login_at = datetime.now(UTC)
        return await self._issue(user, org, membership.role, memberships)

    async def _memberships(
        self, user_id: uuid.UUID
    ) -> list[tuple[OrganizationMember, Organization]]:
        result = await self.db.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == user_id, Organization.is_active.is_(True))
            .order_by(OrganizationMember.is_default.desc(), Organization.name)
        )
        return list(result.all())

    # ── Token lifecycle ──────────────────────────────────────────────────

    async def _issue(
        self,
        user: User,
        org: Organization,
        role: Role,
        memberships: list[tuple[OrganizationMember, Organization]] | None = None,
    ) -> AuthSession:
        access, expires_at = create_access_token(
            user_id=str(user.id), organization_id=str(org.id),
            role=role.value, email=user.email,
        )
        refresh, jti, refresh_expiry = create_refresh_token(
            user_id=str(user.id), organization_id=str(org.id)
        )
        self.db.add(RefreshSession(
            user_id=user.id, organization_id=org.id, jti=jti, expires_at=refresh_expiry
        ))

        all_orgs = memberships if memberships is not None else await self._memberships(user.id)
        return AuthSession(
            tokens=TokenPair(access_token=access, refresh_token=refresh, expires_at=expires_at),
            user=UserProfile.model_validate(user),
            organization=OrganizationSummary(
                id=org.id, name=org.name, slug=org.slug, role=role
            ),
            role=role,
            organizations=[
                OrganizationSummary(id=o.id, name=o.name, slug=o.slug, role=m.role)
                for m, o in all_orgs
            ],
        )

    async def refresh(self, token: str) -> AuthSession:
        payload = decode_token(token, expected_type="refresh")
        jti = payload["jti"]

        redis = get_redis()
        if await redis.exists(f"{_DENY_PREFIX}{jti}"):
            # A denylisted token being replayed usually means it leaked.
            log.warning("refresh_token_replayed", jti=jti, user_id=payload.get("sub"))
            raise AuthenticationError("Session is no longer valid. Sign in again.")

        session = await self.db.scalar(select(RefreshSession).where(RefreshSession.jti == jti))
        if session is None or session.revoked_at is not None:
            raise AuthenticationError("Session is no longer valid. Sign in again.")

        user = await self.db.get(User, uuid.UUID(payload["sub"]))
        org = await self.db.get(Organization, uuid.UUID(payload["org"]))
        if user is None or org is None or not user.is_active:
            raise AuthenticationError("Session is no longer valid. Sign in again.")

        membership = await self.db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == org.id,
            )
        )
        if membership is None:
            raise AuthenticationError("Your access to this workspace has been removed.")

        await self._revoke(session, reason="rotated")
        return await self._issue(user, org, membership.role)

    async def logout(self, token: str) -> None:
        try:
            payload = decode_token(token, expected_type="refresh")
        except AuthenticationError:
            return  # Already unusable — nothing to do, and no information to leak.
        session = await self.db.scalar(
            select(RefreshSession).where(RefreshSession.jti == payload["jti"])
        )
        if session and session.revoked_at is None:
            await self._revoke(session, reason="logout")

    async def _revoke(self, session: RefreshSession, *, reason: str) -> None:
        session.revoked_at = datetime.now(UTC)
        ttl = max(int((session.expires_at - datetime.now(UTC)).total_seconds()), 1)
        await get_redis().setex(f"{_DENY_PREFIX}{session.jti}", ttl, reason)

    # ── Workspace switching ──────────────────────────────────────────────

    async def switch_organization(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> AuthSession:
        membership = await self.db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        )
        if membership is None:
            raise NotFoundError("Workspace not found.")
        user = await self.db.get(User, user_id)
        org = await self.db.get(Organization, organization_id)
        if user is None or org is None:
            raise NotFoundError("Workspace not found.")
        return await self._issue(user, org, membership.role)


__all__ = ["AuthService", "slugify"]
