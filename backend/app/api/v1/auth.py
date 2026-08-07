"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUserDep, DbDep
from app.core.errors import NotFoundError
from app.models.identity import Organization, OrganizationMember
from app.schemas.auth import (
    AuthSession, LoginRequest, MeResponse, OrganizationSummary,
    RefreshRequest, RegisterRequest, UserProfile,
)
from app.schemas.common import Ack
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthSession, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DbDep) -> AuthSession:
    """Create an account and its first workspace. The creator becomes owner."""
    return await AuthService(db).register(body)


@router.post("/login", response_model=AuthSession)
async def login(body: LoginRequest, db: DbDep) -> AuthSession:
    return await AuthService(db).login(body)


@router.post("/refresh", response_model=AuthSession)
async def refresh(body: RefreshRequest, db: DbDep) -> AuthSession:
    """Exchange a refresh token for a new pair. The old token stops working."""
    return await AuthService(db).refresh(body.refresh_token)


@router.post("/logout", response_model=Ack)
async def logout(body: RefreshRequest, db: DbDep) -> Ack:
    await AuthService(db).logout(body.refresh_token)
    return Ack(message="Signed out.")


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep, db: DbDep) -> MeResponse:
    from app.models.identity import User

    db_user = await db.get(User, user.id)
    org = await db.get(Organization, user.organization_id)
    if db_user is None or org is None:
        raise NotFoundError("Account not found.")

    rows = await db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
    )
    return MeResponse(
        user=UserProfile.model_validate(db_user),
        organization=OrganizationSummary(id=org.id, name=org.name, slug=org.slug,
                                         role=user.role),
        role=user.role,
        organizations=[
            OrganizationSummary(id=o.id, name=o.name, slug=o.slug, role=m.role)
            for m, o in rows.all()
        ],
    )


@router.post("/switch/{organization_id}", response_model=AuthSession)
async def switch_workspace(organization_id: str, user: CurrentUserDep,
                           db: DbDep, request: Request) -> AuthSession:
    """Issue tokens scoped to a different workspace the user belongs to."""
    import uuid as _uuid

    return await AuthService(db).switch_organization(user.id, _uuid.UUID(organization_id))
