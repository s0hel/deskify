"""Who may administer what. FR-1.8, TDD §6.6.

The decision is a pure function of the grants a user holds and the scope of
the object being touched, so it is tested without a database in the same way
`policy.py` is. Only `load_grants` goes near a session.

Two rules are the whole model:

  - **Grants are additive.** Holding none is being an employee. There is no
    "deny" row, so reading a user's permissions never means reconciling two
    kinds of row that can contradict each other.
  - **An org-scoped grant covers every site in the org; a site-scoped grant
    covers exactly one.** That is the scope chain TDD §6.6 describes, and it
    is short enough to resolve without a recursive query.

WHY 403 HERE AND 404 IN THE TENANCY LAYER. These look inconsistent and are
not. The tenancy layer answers "does this object exist for you", and 403 there
would confirm that an id names a real object in someone else's org -- the
disclosure the whole layer exists to prevent. This module answers "you are not
an administrator", which is a fact about the caller, not about any object.
Telling an employee they are not an admin discloses nothing they do not know,
and a 404 there would send them hunting for a page that is right in front of
them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import DeskifyError
from app.models import RoleGrant

#: Every role that can be granted. `employee` is not in here deliberately --
#: it is the absence of a grant, not a row (see the module docstring).
ROLES = ("team_lead", "site_admin", "org_admin")

#: Roles that can administer workplace configuration. A team lead leads a
#: team (FR-5.8) and administers nothing, so it is absent.
ADMIN_ROLES = frozenset({"site_admin", "org_admin"})


class Forbidden(DeskifyError):
    status, code, title = 403, "FORBIDDEN", "You do not have permission to do that"


@dataclass(frozen=True)
class Grant:
    role: str
    scope_type: str
    scope_id: uuid.UUID | None


def administers_org(grants: frozenset[Grant]) -> bool:
    """Org-wide administration: creating sites, managing people and roles.

    Only `org_admin`. A site admin manages the office they were given, and
    letting them mint users or new sites would make the scoping decorative.
    """
    return any(g.role == "org_admin" for g in grants)


def administers_site(grants: frozenset[Grant], site_id: uuid.UUID | None) -> bool:
    """Administration of one office: its floors, zones, desks and bookings.

    `site_id` of None means "an object not attached to a site", which only an
    org admin can reach.
    """
    for g in grants:
        if g.role == "org_admin":
            return True
        if g.role == "site_admin" and site_id is not None and g.scope_id == site_id:
            return True
    return False


def administered_site_ids(grants: frozenset[Grant]) -> set[uuid.UUID] | None:
    """The sites these grants cover, or None meaning "all of them".

    None rather than a set, because an org admin's answer is not a list that
    has to be recomputed when someone adds a site.
    """
    if administers_org(grants):
        return None
    return {g.scope_id for g in grants if g.role == "site_admin" and g.scope_id is not None}


def is_admin(grants: frozenset[Grant]) -> bool:
    """Whether to offer the console at all. Any administered site will do."""
    return any(g.role in ADMIN_ROLES for g in grants)


async def load_grants(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> frozenset[Grant]:
    """The one indexed lookup TDD §6.6 asks for, resolved once per request.

    Scoped by organization as well as user: a grant is meaningless outside the
    org that issued it, and matching on user_id alone would carry a role across
    a tenant boundary if an id were ever reused.
    """
    rows = await session.execute(
        select(RoleGrant.role, RoleGrant.scope_type, RoleGrant.scope_id).where(
            RoleGrant.organization_id == organization_id,
            RoleGrant.user_id == user_id,
        )
    )
    return frozenset(Grant(role=r, scope_type=st, scope_id=sid) for r, st, sid in rows)
