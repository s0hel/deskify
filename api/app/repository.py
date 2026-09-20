"""The tenancy layer. TDD §15.1.

Every query goes through here, and every method requires an organization_id
sourced from the access token. No handler constructs a query directly, and no
endpoint accepts a tenant identifier from the client.

A miss returns None so the caller raises 404 -- never 403, which would confirm
the object exists.
"""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppUser,
    Base,
    Booking,
    DayDeclaration,
    Floor,
    GroupMember,
    Resource,
    RoleGrant,
    Site,
    UserGroup,
    Zone,
)

T = TypeVar("T", bound=Base)

#: Tables that are tenant-scoped. Anything here MUST be fetched through this layer.
TENANT_SCOPED = (
    AppUser,
    Site,
    Floor,
    Zone,
    Resource,
    Booking,
    DayDeclaration,
    UserGroup,
    GroupMember,
    RoleGrant,
)


class TenantRepository:
    """Scoped to exactly one organization for its whole lifetime."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID):
        self.session = session
        self.organization_id = organization_id

    async def get(self, model: type[T], object_id: uuid.UUID) -> T | None:
        if model not in TENANT_SCOPED:
            raise RuntimeError(f"{model.__name__} is not tenant-scoped; add it to TENANT_SCOPED")
        stmt = select(model).where(
            model.id == object_id,
            model.organization_id == self.organization_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, model: type[T], *where) -> list[T]:
        if model not in TENANT_SCOPED:
            raise RuntimeError(f"{model.__name__} is not tenant-scoped; add it to TENANT_SCOPED")
        stmt = select(model).where(model.organization_id == self.organization_id, *where)
        return list((await self.session.execute(stmt)).scalars())

    def add(self, obj: T) -> T:
        """Stamps the tenant, so a handler cannot forget it."""
        obj.organization_id = self.organization_id
        self.session.add(obj)
        return obj
