"""Request dependencies.

`CurrentUser` is the object every protected route receives. It always carries a
concrete ``organization_id``, and repository helpers take it rather than a raw
id, which makes it hard to write a query that forgets tenant isolation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AuthenticationError, PermissionError_
from app.core.logging import organization_id_ctx, user_id_ctx
from app.core.security import constant_time_equals, decode_token
from app.models.enums import Role
from app.models.identity import OrganizationMember, User

bearer = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    full_name: str
    organization_id: uuid.UUID
    role: Role

    def require(self, minimum: Role) -> None:
        """Raise unless this user's role is at least ``minimum``."""
        if self.role.rank < minimum.rank:
            raise PermissionError_(
                f"This action requires the {minimum.value} role or higher."
            )

    @property
    def can_write(self) -> bool:
        return self.role.rank >= Role.AGENT.rank


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    if credentials is None:
        raise AuthenticationError("Sign in to continue.")

    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = uuid.UUID(payload["sub"])
    org_id = uuid.UUID(payload["org"])

    # Re-check membership on every request: a revoked seat must stop working
    # immediately rather than at token expiry.
    result = await db.execute(
        select(User, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            OrganizationMember.organization_id == org_id,
        )
    )
    row = result.first()
    if row is None:
        raise AuthenticationError("Your access to this workspace has been removed.")

    user, membership = row
    user_id_ctx.set(str(user.id))
    organization_id_ctx.set(str(org_id))

    return CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_id=org_id,
        role=membership.role,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def require_role(minimum: Role):
    """Route-level role gate: ``Depends(require_role(Role.ADMIN))``."""

    async def _guard(user: CurrentUserDep) -> CurrentUser:
        user.require(minimum)
        return user

    return _guard


async def require_internal_service(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Guard for ``/api/internal/*``, which only n8n may call.

    This is a shared bearer secret on a private Docker network — not a user
    session. It never grants access to user-facing routes.
    """
    if not settings.internal_service_token:
        raise PermissionError_("Internal API is disabled: INTERNAL_SERVICE_TOKEN is unset.")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not constant_time_equals(token, settings.internal_service_token):
        raise AuthenticationError("Invalid internal service token.")
    request.state.is_internal = True
