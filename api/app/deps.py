"""Request-scoped principal and tenant repository.

The tenant is derived from the access token, never from a request parameter.
An endpoint that accepts an organization_id from the client is a bug (TDD §5.1).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decode_access_token
from app.db import get_session
from app.errors import DeskflowError
from app.repository import TenantRepository


class Unauthenticated(DeskflowError):
    status, code, title = 401, "UNAUTHENTICATED", "Sign in required"


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    organization_id: uuid.UUID


async def current_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthenticated()
    try:
        user_id, org_id = decode_access_token(authorization.split(" ", 1)[1])
    except ValueError as exc:
        raise Unauthenticated() from exc
    return Principal(user_id=user_id, organization_id=org_id)


async def tenant_repo(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantRepository:
    return TenantRepository(session, principal.organization_id)
