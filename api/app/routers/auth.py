from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth as auth_svc
from app.config import settings
from app.db import get_session
from app.errors import DeskflowError
from app.models import AppUser, EmailDomain

router = APIRouter(prefix="/auth", tags=["auth"])


class DiscoverRequest(BaseModel):
    email: EmailStr


class DiscoverResponse(BaseModel):
    region: str
    idp_kind: str
    start_url: str


@router.post("/discover", response_model=DiscoverResponse)
async def discover(
    body: DiscoverRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> DiscoverResponse:
    """FR-1.3. Answers for a DOMAIN, never for a user.

    The response is identical whether or not the address belongs to a real
    account, so this cannot be used to enumerate employees (TDD §15.3).
    """
    domain = body.email.split("@")[-1].lower()
    row = (
        await session.execute(select(EmailDomain).where(EmailDomain.domain == domain))
    ).scalar_one_or_none()
    if row is None:
        return DiscoverResponse(region="us", idp_kind="magic_link", start_url="/auth/start")
    return DiscoverResponse(
        region="us", idp_kind=row.idp_kind, start_url=f"/auth/start?domain={domain}"
    )


class DevSignInRequest(BaseModel):
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/dev-sign-in", include_in_schema=False)
async def dev_sign_in(
    body: DevSignInRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """Stands in for the IdP leg until Phase 0 obtains client credentials.

    Returns a one-time code exactly as /auth/callback will, so the client's
    redemption path is the real one and does not change when the real IdP
    arrives.
    """
    if settings.environment != "dev":
        raise DeskflowError("dev sign-in is disabled outside dev")
    user = (
        await session.execute(select(AppUser).where(AppUser.email == body.email))
    ).scalar_one_or_none()
    if user is None:
        raise DeskflowError("unknown user")
    return {"code": auth_svc.issue_one_time_code(user.id, user.organization_id)}


class TokenRequest(BaseModel):
    code: str


@router.post("/token", response_model=TokenResponse)
async def exchange_code(body: TokenRequest) -> TokenResponse:
    redeemed = auth_svc.redeem_one_time_code(body.code)
    if redeemed is None:
        raise DeskflowError("invalid or expired code")
    user_id, org_id = redeemed
    return TokenResponse(
        access_token=auth_svc.mint_access_token(user_id, org_id),
        expires_in=settings.access_token_ttl_seconds,
    )
