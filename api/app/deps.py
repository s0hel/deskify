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
from app.authz import Forbidden, Grant, administers_org, administers_site, is_admin, load_grants
from app.db import get_session
from app.errors import DeskifyError
from app.repository import TenantRepository


class Unauthenticated(DeskifyError):
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


@dataclass(frozen=True)
class Admin:
    """A principal plus the grants they hold, resolved once per request.

    The handlers ask this object rather than re-querying, so a request cannot
    be authorized against one set of grants and then act on another.

    Nothing here is a guarantee on its own: `current_admin` proves only that
    the caller administers SOMETHING. The per-object check is `assert_site`,
    and an admin endpoint that reaches an object without calling it is a bug.
    """

    principal: Principal
    grants: frozenset[Grant]

    @property
    def user_id(self) -> uuid.UUID:
        return self.principal.user_id

    @property
    def organization_id(self) -> uuid.UUID:
        return self.principal.organization_id

    def assert_org(self) -> None:
        """For things that belong to the organization, not to one office:
        creating a site, managing people, granting roles."""
        if not administers_org(self.grants):
            raise Forbidden("This action requires an organization administrator.")

    def assert_site(self, site_id: uuid.UUID | None) -> None:
        """For anything inside one office. An org admin passes for every site.

        Call this AFTER the object has been fetched through the repository, so
        another tenant's id is already a 404 and this never gets the chance to
        answer 403 about an object the caller cannot see.
        """
        if not administers_site(self.grants, site_id):
            raise Forbidden("This action requires an administrator for that site.")


async def current_admin(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Admin:
    """Gate on the admin router. Refuses anyone holding no administrative
    grant at all, so an employee never reaches a handler."""
    grants = await load_grants(session, principal.organization_id, principal.user_id)
    if not is_admin(grants):
        raise Forbidden("This area is for workplace administrators.")
    return Admin(principal=principal, grants=grants)


async def principal_grants(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> frozenset[Grant]:
    """Grants without the gate, for endpoints that serve both audiences --
    /me reports whether to offer the console, and cancelling a booking allows
    either its owner or an admin."""
    return await load_grants(session, principal.organization_id, principal.user_id)
