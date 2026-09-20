"""The admin console's API. FR-8.1, 8.4, 8.6, 8.8.

Three things are true of every handler here and are not repeated in each one:

  1. **Objects are fetched through the repository first, authorized second.**
     `repo.get` answers 404 for another tenant's id before `assert_site` gets
     the chance to answer 403 about it. The order is the difference between
     "no such site" and "a site exists with that id and you may not have it".
  2. **The change and its audit row share a transaction.** `audit.record`
     writes into the session; the single `commit` at the end of the handler
     lands both or neither.
  3. **Scope is taken from the object, never from the request.** A floor's
     site is read off the floor, so a site admin cannot reach another office's
     floor by naming their own site in the body.

What is deliberately NOT here yet: the floor-plan editor's bulk placement
(FR-8.2, `POST /resources/bulk`), CSV import (FR-8.3), the policy editor
(FR-8.5) and QR label sheets (FR-8.7). See TDD §5.2 for the full surface.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.authz import administered_site_ids
from app.booking_service import RELEASED_STATUSES, create_booking, release_booking
from app.db import get_session
from app.deps import Admin, current_admin
from app.errors import DeskifyError, NotFound
from app.models import (
    AppUser,
    AuditLog,
    Booking,
    Floor,
    GroupMember,
    Resource,
    RoleGrant,
    Site,
    UserGroup,
    Zone,
)
from app.repository import TenantRepository
from app.timezone import local_today, parse_opening_hours, slot_bounds

router = APIRouter(tags=["admin"])

Actor = Annotated[Admin, Depends(current_admin)]
Db = Annotated[AsyncSession, Depends(get_session)]


def repo_for(admin: Admin, db: AsyncSession) -> TenantRepository:
    """The admin router builds its own repository rather than depending on
    `tenant_repo`, so that the admin gate runs before any query does."""
    return TenantRepository(db, admin.organization_id)


async def upcoming_bookings(
    repo: TenantRepository, *where, sites: dict[uuid.UUID, Site] | None = None
) -> list[Booking]:
    """Live bookings from today onwards, where "today" is the SITE's.

    `date.today()` is the server's date, and this product has exactly one
    day-boundary rule: a booking's day is its calendar date in the timezone of
    the office it is at (TDD §3.4, app/timezone.py). An org spanning Singapore
    and Denver has no single today, and a server in UTC would decide that a
    Singapore booking for "tomorrow" is in the past for thirteen hours a day
    -- so deactivating someone would quietly fail to release it.

    The SQL filter is deliberately loose: `local_date` is a bare date, so the
    query cannot join against each site's timezone. It takes everything from
    the earliest date any timezone could still call today, and the exact
    boundary is applied per row below, where the site is known.
    """
    earliest = min(
        local_today("Pacific/Kiritimati"), local_today("Etc/GMT+12")
    )
    rows = await repo.list(
        Booking,
        Booking.local_date >= earliest,
        Booking.status.notin_(RELEASED_STATUSES),
        *where,
    )
    if sites is None:
        sites = {s.id: s for s in await repo.list(Site)}
    return [
        b
        for b in rows
        if (site := sites.get(b.site_id)) is not None
        and b.local_date >= local_today(site.timezone)
    ]


class Conflict(DeskifyError):
    status, code, title = 409, "ADMIN_CONFLICT", "That change conflicts with existing data"


class InvalidChange(DeskifyError):
    status, code, title = 422, "INVALID_CHANGE", "That change is not allowed"


# --------------------------------------------------------------------------
# Sites, floors, zones (FR-8.1)
# --------------------------------------------------------------------------


class SiteAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    timezone: str
    opening_hours: dict
    capacity_cap: int | None
    check_in_enabled: bool
    geofence_lat: float | None
    geofence_lng: float | None
    geofence_radius_m: int


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str
    opening_hours: dict = Field(default_factory=lambda: {"open": "08:00", "close": "18:00"})
    capacity_cap: int | None = Field(default=None, ge=0)
    check_in_enabled: bool = True
    geofence_lat: float | None = None
    geofence_lng: float | None = None
    geofence_radius_m: int = Field(default=150, ge=10, le=5000)


class SitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    opening_hours: dict | None = None
    capacity_cap: int | None = Field(default=None, ge=0)
    check_in_enabled: bool | None = None
    geofence_lat: float | None = None
    geofence_lng: float | None = None
    geofence_radius_m: int | None = Field(default=None, ge=10, le=5000)


def _validate_site_shape(timezone: str, opening_hours: dict) -> None:
    """Reject a site that would break the day-boundary rule at read time.

    A bad timezone or an unparseable opening_hours does not fail here -- it
    fails later, inside `/sites/{id}/days` for every employee at that office,
    which is a long way from the admin who typed it.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidChange(f"{timezone!r} is not an IANA timezone name.") from exc
    try:
        opens, closes = parse_opening_hours(opening_hours)
    except (KeyError, ValueError) as exc:
        raise InvalidChange(
            "opening_hours needs an 'open' and a 'close' as HH:MM."
        ) from exc
    if opens >= closes:
        raise InvalidChange("An office has to close after it opens.")


@router.post("/sites", response_model=SiteAdminOut, status_code=201)
async def create_site(body: SiteIn, admin: Actor, db: Db) -> Site:
    """FR-8.1. Org admins only -- a site admin administers the office they
    were given, and minting new ones would make that scoping decorative."""
    admin.assert_org()
    _validate_site_shape(body.timezone, body.opening_hours)

    repo = repo_for(admin, db)
    site = repo.add(Site(**body.model_dump()))
    await db.flush()
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="site.create", target_type="site", target_id=site.id, name=site.name,
    )
    await db.commit()
    return site


@router.patch("/sites/{site_id}", response_model=SiteAdminOut)
async def update_site(site_id: uuid.UUID, body: SitePatch, admin: Actor, db: Db) -> Site:
    """FR-8.1.

    The timezone is the one field that cannot always change. TDD §3.5: a site's
    timezone is the day-boundary rule for every booking already written against
    it, so moving it silently re-dates history -- a booking made for Tuesday
    becomes a booking for Monday, and the utilization numbers reported last
    month stop reconciling. A genuine office move is a new site, and this says
    so rather than quietly succeeding.
    """
    repo = repo_for(admin, db)
    site = await repo.get(Site, site_id)
    if site is None:
        raise NotFound("site")
    admin.assert_site(site.id)

    changes = body.model_dump(exclude_unset=True)
    if "timezone" in changes and changes["timezone"] != site.timezone:
        booked = (
            await db.execute(
                select(func.count())
                .select_from(Booking)
                .where(
                    Booking.organization_id == admin.organization_id,
                    Booking.site_id == site.id,
                )
            )
        ).scalar_one()
        if booked:
            raise Conflict(
                f"{site.name} has {booked} booking(s) recorded against "
                f"{site.timezone}. Changing the timezone would re-date all of "
                f"them. Create a new site for a genuine move.",
                bookings=booked,
            )

    _validate_site_shape(
        changes.get("timezone", site.timezone),
        changes.get("opening_hours", site.opening_hours),
    )

    before = {k: getattr(site, k) for k in changes}
    for field, value in changes.items():
        setattr(site, field, value)

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="site.update", target_type="site", target_id=site.id,
        before=before, after=changes,
    )
    await db.commit()
    return site


class FloorAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    ordinal: int
    plan_asset_key: str | None
    plan_width: int | None
    plan_height: int | None
    desk_count: int = 0


class FloorIn(BaseModel):
    site_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80)
    ordinal: int = 0
    plan_asset_key: str | None = None
    plan_width: int | None = Field(default=None, gt=0)
    plan_height: int | None = Field(default=None, gt=0)


class FloorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    ordinal: int | None = None
    plan_asset_key: str | None = None


@router.get("/admin/floors", response_model=list[FloorAdminOut])
async def list_floors_for_admin(admin: Actor, db: Db, site_id: uuid.UUID | None = None):
    """Every floor the caller administers, with its desk count.

    The count is the number an admin actually wants: a floor row with no desks
    on it is an unfinished import, and it should be visible as one.
    """
    repo = repo_for(admin, db)
    scope = administered_site_ids(admin.grants)
    floors = await repo.list(Floor)
    resources = await repo.list(Resource, Resource.kind == "desk")
    counts: dict[uuid.UUID, int] = {}
    for r in resources:
        if r.floor_id:
            counts[r.floor_id] = counts.get(r.floor_id, 0) + 1

    return [
        FloorAdminOut(
            **{k: getattr(f, k) for k in
               ("id", "site_id", "name", "ordinal", "plan_asset_key",
                "plan_width", "plan_height")},
            desk_count=counts.get(f.id, 0),
        )
        for f in sorted(floors, key=lambda f: (f.ordinal, f.name))
        if (scope is None or f.site_id in scope)
        and (site_id is None or f.site_id == site_id)
    ]


@router.post("/floors", response_model=FloorAdminOut, status_code=201)
async def create_floor(body: FloorIn, admin: Actor, db: Db) -> FloorAdminOut:
    """FR-8.1. The site id is in the BODY, so the path-driven cross-tenant
    harness cannot reach it -- covered by hand in tests/test_admin.py."""
    repo = repo_for(admin, db)
    site = await repo.get(Site, body.site_id)
    if site is None:
        raise NotFound("site")
    admin.assert_site(site.id)

    floor = repo.add(Floor(**body.model_dump()))
    await db.flush()
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="floor.create", target_type="floor", target_id=floor.id,
        site_id=site.id, name=floor.name,
    )
    await db.commit()
    return FloorAdminOut.model_validate(floor, from_attributes=True)


@router.patch("/floors/{floor_id}", response_model=FloorAdminOut)
async def update_floor(
    floor_id: uuid.UUID, body: FloorPatch, admin: Actor, db: Db
) -> FloorAdminOut:
    """FR-8.1.

    `plan_width` and `plan_height` are absent from FloorPatch on purpose. Plan
    space is frozen on first upload (TDD §9.1) because every desk's plan_x and
    plan_y is expressed in it; resizing it moves 300 desks at once, invisibly.
    A new plan is a new upload, which is FR-8.2's job.
    """
    repo = repo_for(admin, db)
    floor = await repo.get(Floor, floor_id)
    if floor is None:
        raise NotFound("floor")
    admin.assert_site(floor.site_id)

    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(floor, k) for k in changes}
    for field, value in changes.items():
        setattr(floor, field, value)

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="floor.update", target_type="floor", target_id=floor.id,
        before=before, after=changes,
    )
    await db.commit()
    return FloorAdminOut.model_validate(floor, from_attributes=True)


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    floor_id: uuid.UUID
    name: str
    polygon: list
    restricted_to_group_id: uuid.UUID | None
    resource_count: int = 0


class ZoneIn(BaseModel):
    floor_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80)
    polygon: list = Field(default_factory=list)
    restricted_to_group_id: uuid.UUID | None = None


class ZonePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    polygon: list | None = None
    #: FR-6.4. Absent leaves the restriction alone; explicit null removes it.
    restricted_to_group_id: uuid.UUID | None = None


async def _floor_of_zone(repo: TenantRepository, zone: Zone) -> Floor:
    floor = await repo.get(Floor, zone.floor_id)
    if floor is None:
        raise NotFound("floor")
    return floor


@router.get("/admin/zones", response_model=list[ZoneOut])
async def list_zones(admin: Actor, db: Db, floor_id: uuid.UUID | None = None):
    repo = repo_for(admin, db)
    scope = administered_site_ids(admin.grants)
    floors = {f.id: f for f in await repo.list(Floor)}
    resources = await repo.list(Resource)
    counts: dict[uuid.UUID, int] = {}
    for r in resources:
        if r.zone_id:
            counts[r.zone_id] = counts.get(r.zone_id, 0) + 1

    out = []
    for z in await repo.list(Zone):
        floor = floors.get(z.floor_id)
        if floor is None:
            continue
        if scope is not None and floor.site_id not in scope:
            continue
        if floor_id is not None and z.floor_id != floor_id:
            continue
        out.append(
            ZoneOut(
                id=z.id, floor_id=z.floor_id, name=z.name, polygon=z.polygon,
                restricted_to_group_id=z.restricted_to_group_id,
                resource_count=counts.get(z.id, 0),
            )
        )
    return sorted(out, key=lambda z: z.name)


@router.post("/zones", response_model=ZoneOut, status_code=201)
async def create_zone(body: ZoneIn, admin: Actor, db: Db) -> ZoneOut:
    repo = repo_for(admin, db)
    floor = await repo.get(Floor, body.floor_id)
    if floor is None:
        raise NotFound("floor")
    admin.assert_site(floor.site_id)
    if body.restricted_to_group_id is not None:
        await _require_group(repo, body.restricted_to_group_id)

    zone = repo.add(Zone(**body.model_dump()))
    await db.flush()
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="zone.create", target_type="zone", target_id=zone.id,
        floor_id=floor.id, name=zone.name,
    )
    await db.commit()
    return ZoneOut.model_validate(zone, from_attributes=True)


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
async def update_zone(
    zone_id: uuid.UUID, body: ZonePatch, admin: Actor, db: Db
) -> ZoneOut:
    repo = repo_for(admin, db)
    zone = await repo.get(Zone, zone_id)
    if zone is None:
        raise NotFound("zone")
    floor = await _floor_of_zone(repo, zone)
    admin.assert_site(floor.site_id)

    changes = body.model_dump(exclude_unset=True)
    if changes.get("restricted_to_group_id") is not None:
        await _require_group(repo, changes["restricted_to_group_id"])

    before = {k: getattr(zone, k) for k in changes}
    for field, value in changes.items():
        setattr(zone, field, value)

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="zone.update", target_type="zone", target_id=zone.id,
        before=before, after=changes,
    )
    await db.commit()
    return ZoneOut.model_validate(zone, from_attributes=True)


@router.delete("/zones/{zone_id}", status_code=204)
async def delete_zone(zone_id: uuid.UUID, admin: Actor, db: Db) -> None:
    """A zone with desks in it is not deleted, because the desks would keep a
    dangling zone_id and quietly lose whatever restriction the zone carried
    (FR-6.4). Move the desks first; the refusal says how many."""
    repo = repo_for(admin, db)
    zone = await repo.get(Zone, zone_id)
    if zone is None:
        raise NotFound("zone")
    floor = await _floor_of_zone(repo, zone)
    admin.assert_site(floor.site_id)

    held = await repo.list(Resource, Resource.zone_id == zone.id)
    if held:
        raise Conflict(
            f"{zone.name} still has {len(held)} desk(s) in it. Move them to "
            f"another zone first.",
            resources=len(held),
        )

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="zone.delete", target_type="zone", target_id=zone.id, name=zone.name,
    )
    await db.delete(zone)
    await db.commit()


# --------------------------------------------------------------------------
# People, groups and roles (FR-8.4, FR-1.8)
# --------------------------------------------------------------------------


async def _require_group(repo: TenantRepository, group_id: uuid.UUID) -> UserGroup:
    group = await repo.get(UserGroup, group_id)
    if group is None:
        raise NotFound("group")
    return group


class RoleOut(BaseModel):
    role: str
    scope_type: str
    scope_id: uuid.UUID | None
    scope_name: str | None = None


class UserAdminOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    status: str
    home_site_id: uuid.UUID | None
    presence_visibility: str
    teams: list[str]
    roles: list[RoleOut]
    future_bookings: int


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    home_site_id: uuid.UUID | None = None
    locale: str = "en"


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    home_site_id: uuid.UUID | None = None


class RoleIn(BaseModel):
    role: Literal["team_lead", "site_admin", "org_admin"]
    #: NULL for an org-wide grant. A site_admin without one would read as
    #: admin of every site, which the CHECK in revision 0004 refuses.
    scope_id: uuid.UUID | None = None


class RolesIn(BaseModel):
    roles: list[RoleIn]


async def _users_out(
    repo: TenantRepository, db: AsyncSession, users: list[AppUser]
) -> list[UserAdminOut]:
    """One pass over the org rather than a query per user. The people screen
    lists everyone, so an N+1 here is the whole page."""
    ids = {u.id for u in users}
    groups = {g.id: g.name for g in await repo.list(UserGroup)}
    sites = {s.id: s.name for s in await repo.list(Site)}

    teams: dict[uuid.UUID, list[str]] = {}
    for m in await repo.list(GroupMember, GroupMember.user_id.in_(ids)):
        if m.group_id in groups:
            teams.setdefault(m.user_id, []).append(groups[m.group_id])

    roles: dict[uuid.UUID, list[RoleOut]] = {}
    for g in await repo.list(RoleGrant, RoleGrant.user_id.in_(ids)):
        roles.setdefault(g.user_id, []).append(
            RoleOut(
                role=g.role, scope_type=g.scope_type, scope_id=g.scope_id,
                scope_name=(
                    sites.get(g.scope_id) if g.scope_type == "site"
                    else groups.get(g.scope_id) if g.scope_type == "group"
                    else None
                ),
            )
        )

    counts: dict[uuid.UUID, int] = {}
    for b in await upcoming_bookings(repo, Booking.user_id.in_(ids)):
        counts[b.user_id] = counts.get(b.user_id, 0) + 1

    return [
        UserAdminOut(
            id=u.id, email=u.email, display_name=u.display_name, status=u.status,
            home_site_id=u.home_site_id, presence_visibility=u.presence_visibility,
            teams=sorted(teams.get(u.id, [])),
            roles=sorted(roles.get(u.id, []), key=lambda r: (r.role, r.scope_name or "")),
            future_bookings=counts.get(u.id, 0),
        )
        for u in users
    ]


@router.get("/admin/users", response_model=list[UserAdminOut])
async def list_users(admin: Actor, db: Db, q: str | None = None):
    """FR-8.4. The whole directory, unfiltered by presence privacy.

    That is the one deliberate exception to `app/presence.py`: privacy hides a
    colleague's WHEREABOUTS from other employees, and it was never a claim
    that the employer does not know who works there. What this endpoint does
    not return is where anyone is sitting -- there is no booking detail in
    UserAdminOut, only a count, so a hidden colleague's office days stay
    hidden from an admin reading this screen too.
    """
    admin.assert_org()
    repo = repo_for(admin, db)
    users = await repo.list(AppUser)
    if q:
        needle = q.strip().lower()
        users = [
            u for u in users
            if needle in u.display_name.lower() or needle in u.email.lower()
        ]
    users.sort(key=lambda u: (u.status != "active", u.display_name.lower()))
    return await _users_out(repo, db, users)


@router.post("/admin/users", response_model=UserAdminOut, status_code=201)
async def create_user(body: UserIn, admin: Actor, db: Db) -> UserAdminOut:
    admin.assert_org()
    repo = repo_for(admin, db)
    email = body.email.strip().lower()

    existing = await repo.list(AppUser, AppUser.email == email)
    if existing:
        raise Conflict(f"{email} is already in this organization.")
    if body.home_site_id is not None and await repo.get(Site, body.home_site_id) is None:
        raise NotFound("site")

    user = repo.add(
        AppUser(
            email=email, display_name=body.display_name.strip(),
            home_site_id=body.home_site_id, locale=body.locale,
        )
    )
    await db.flush()
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="user.create", target_type="user", target_id=user.id, email=email,
    )
    await db.commit()
    return (await _users_out(repo, db, [user]))[0]


@router.patch("/admin/users/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: uuid.UUID, body: UserPatch, admin: Actor, db: Db
) -> UserAdminOut:
    admin.assert_org()
    repo = repo_for(admin, db)
    user = await repo.get(AppUser, user_id)
    if user is None:
        raise NotFound("user")

    changes = body.model_dump(exclude_unset=True)
    if changes.get("home_site_id") is not None and (
        await repo.get(Site, changes["home_site_id"]) is None
    ):
        raise NotFound("site")

    before = {k: getattr(user, k) for k in changes}
    for field, value in changes.items():
        setattr(user, field, value)

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="user.update", target_type="user", target_id=user.id,
        before=before, after=changes,
    )
    await db.commit()
    return (await _users_out(repo, db, [user]))[0]


@router.put("/admin/users/{user_id}/roles", response_model=UserAdminOut)
async def set_roles(
    user_id: uuid.UUID, body: RolesIn, admin: Actor, db: Db
) -> UserAdminOut:
    """FR-1.8. Replaces the whole set, so the screen showing it and the rows
    behind it cannot drift.

    THE LAST ADMIN IS PROTECTED. An org with no org_admin is an org nobody can
    administer -- not a support ticket, a data-repair job -- so removing the
    final one is refused. Demoting yourself while a colleague still holds the
    role is allowed: locking an admin out of their own demotion is the kind of
    rule that gets worked around with a database console.
    """
    admin.assert_org()
    repo = repo_for(admin, db)
    user = await repo.get(AppUser, user_id)
    if user is None:
        raise NotFound("user")

    wanted: list[tuple[str, str, uuid.UUID | None]] = []
    for r in body.roles:
        if r.role == "org_admin":
            if r.scope_id is not None:
                raise InvalidChange("An org_admin grant is org-wide and takes no scope.")
            wanted.append((r.role, "org", None))
        elif r.role == "site_admin":
            if r.scope_id is None:
                raise InvalidChange(
                    "A site_admin grant names the site it covers. Grant org_admin "
                    "for every site."
                )
            if await repo.get(Site, r.scope_id) is None:
                raise NotFound("site")
            wanted.append((r.role, "site", r.scope_id))
        else:  # team_lead
            if r.scope_id is None:
                raise InvalidChange("A team_lead grant names the team it covers.")
            await _require_group(repo, r.scope_id)
            wanted.append((r.role, "group", r.scope_id))

    current = await repo.list(RoleGrant, RoleGrant.user_id == user.id)
    was_org_admin = any(g.role == "org_admin" for g in current)
    will_be_org_admin = any(role == "org_admin" for role, _, _ in wanted)

    if was_org_admin and not will_be_org_admin:
        others = (
            await db.execute(
                select(func.count())
                .select_from(RoleGrant)
                .where(
                    RoleGrant.organization_id == admin.organization_id,
                    RoleGrant.role == "org_admin",
                    RoleGrant.user_id != user.id,
                )
            )
        ).scalar_one()
        if not others:
            raise Conflict(
                f"{user.display_name} is the only organization administrator. "
                f"Grant the role to someone else before removing it here."
            )

    for grant in current:
        await db.delete(grant)
    await db.flush()
    for role, scope_type, scope_id in dict.fromkeys(wanted):
        repo.add(
            RoleGrant(
                user_id=user.id, role=role, scope_type=scope_type,
                scope_id=scope_id, granted_by=admin.user_id,
            )
        )

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="user.roles", target_type="user", target_id=user.id,
        before=[[g.role, g.scope_type, g.scope_id] for g in current],
        after=[list(w) for w in wanted],
    )
    await db.commit()
    return (await _users_out(repo, db, [user]))[0]


class DeactivationOut(BaseModel):
    user: UserAdminOut
    released: int


@router.post("/admin/users/{user_id}/deactivate", response_model=DeactivationOut)
async def deactivate_user(user_id: uuid.UUID, admin: Actor, db: Db) -> DeactivationOut:
    """FR-8.4, TDD §6.6. Deactivating releases what the person left behind.

    One transaction: status flips, every future booking is cancelled, the
    day's capacity counter is decremented for each, and an audit row records
    the count. A leaver whose desks stay booked is the most visible way for
    this product to be wrong -- a row of permanently occupied desks nobody
    ever sits at.

    PAST BOOKINGS ARE LEFT ALONE. Deleting them would falsify utilization that
    has already been reported to a customer (TDD §6.6); they age out through
    the retention purge (FR-9.7) instead.

    NOT YET DONE HERE: revoking the refresh-token families. There is no
    refresh token to revoke -- FR-1.4 is unbuilt -- and a `pass` with a
    comment would read as if there were.
    """
    admin.assert_org()
    repo = repo_for(admin, db)
    user = await repo.get(AppUser, user_id)
    if user is None:
        raise NotFound("user")
    if user.id == admin.user_id:
        raise InvalidChange(
            "You cannot deactivate your own account. Ask another administrator."
        )

    future = await upcoming_bookings(repo, Booking.user_id == user.id)
    released = 0
    for booking in future:
        if await release_booking(
            db, booking, reason=f"Account deactivated by {admin.user_id}"
        ):
            released += 1

    user.status = "deactivated"
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="user.deactivate", target_type="user", target_id=user.id,
        email=user.email, bookings_released=released,
    )
    await db.commit()
    return DeactivationOut(
        user=(await _users_out(repo, db, [user]))[0], released=released
    )


@router.post("/admin/users/{user_id}/reactivate", response_model=UserAdminOut)
async def reactivate_user(user_id: uuid.UUID, admin: Actor, db: Db) -> UserAdminOut:
    """Their bookings are not restored. The desks went back to the pool and
    someone else may be sitting at them."""
    admin.assert_org()
    repo = repo_for(admin, db)
    user = await repo.get(AppUser, user_id)
    if user is None:
        raise NotFound("user")

    user.status = "active"
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="user.reactivate", target_type="user", target_id=user.id, email=user.email,
    )
    await db.commit()
    return (await _users_out(repo, db, [user]))[0]


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    kind: str
    anchor_days: list
    member_count: int = 0


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["team", "department", "custom"] = "team"
    anchor_days: list[int] = Field(default_factory=list)


class GroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    anchor_days: list[int] | None = None


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID]


def _validate_anchor_days(days: list[int]) -> list[int]:
    """ISO weekdays, 1 = Monday. A 0 or an 8 here renders as a blank column on
    the team grid rather than as an error, which is why it is checked."""
    if any(d < 1 or d > 7 for d in days):
        raise InvalidChange("Anchor days are ISO weekdays: 1 (Monday) to 7 (Sunday).")
    return sorted(set(days))


@router.get("/admin/groups", response_model=list[GroupOut])
async def list_groups(admin: Actor, db: Db):
    admin.assert_org()
    repo = repo_for(admin, db)
    counts: dict[uuid.UUID, int] = {}
    for m in await repo.list(GroupMember):
        counts[m.group_id] = counts.get(m.group_id, 0) + 1
    return [
        GroupOut(
            id=g.id, name=g.name, kind=g.kind, anchor_days=g.anchor_days,
            member_count=counts.get(g.id, 0),
        )
        for g in sorted(await repo.list(UserGroup), key=lambda g: g.name.lower())
    ]


@router.post("/admin/groups", response_model=GroupOut, status_code=201)
async def create_group(body: GroupIn, admin: Actor, db: Db) -> GroupOut:
    admin.assert_org()
    repo = repo_for(admin, db)
    if await repo.list(UserGroup, UserGroup.name == body.name):
        raise Conflict(f"A group called {body.name!r} already exists.")

    group = repo.add(
        UserGroup(
            name=body.name, kind=body.kind,
            anchor_days=_validate_anchor_days(body.anchor_days),
        )
    )
    await db.flush()
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="group.create", target_type="group", target_id=group.id, name=group.name,
    )
    await db.commit()
    return GroupOut.model_validate(group, from_attributes=True)


@router.patch("/admin/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: uuid.UUID, body: GroupPatch, admin: Actor, db: Db
) -> GroupOut:
    """FR-5.8 reaches anchor_days from here as well as from a team lead."""
    admin.assert_org()
    repo = repo_for(admin, db)
    group = await _require_group(repo, group_id)

    changes = body.model_dump(exclude_unset=True)
    if "anchor_days" in changes:
        changes["anchor_days"] = _validate_anchor_days(changes["anchor_days"])

    before = {k: getattr(group, k) for k in changes}
    for field, value in changes.items():
        setattr(group, field, value)

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="group.update", target_type="group", target_id=group.id,
        before=before, after=changes,
    )
    await db.commit()
    return GroupOut.model_validate(group, from_attributes=True)


@router.put("/admin/groups/{group_id}/members", response_model=GroupOut)
async def set_members(
    group_id: uuid.UUID, body: MembersIn, admin: Actor, db: Db
) -> GroupOut:
    """Replaces the membership. An id from another tenant is a 404 for the
    same reason a site id would be -- the repository never sees it."""
    admin.assert_org()
    repo = repo_for(admin, db)
    group = await _require_group(repo, group_id)

    wanted = list(dict.fromkeys(body.user_ids))
    found = {u.id for u in await repo.list(AppUser, AppUser.id.in_(wanted))} if wanted else set()
    missing = [u for u in wanted if u not in found]
    if missing:
        raise NotFound("user")

    existing = await repo.list(GroupMember, GroupMember.group_id == group.id)
    had = {m.user_id for m in existing}
    for member in existing:
        if member.user_id not in found:
            await db.delete(member)
    await db.flush()
    for user_id in wanted:
        if user_id not in had:
            repo.add(GroupMember(group_id=group.id, user_id=user_id))

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="group.members", target_type="group", target_id=group.id,
        added=sorted(str(u) for u in found - had),
        removed=sorted(str(u) for u in had - found),
    )
    await db.commit()
    return GroupOut(
        id=group.id, name=group.name, kind=group.kind,
        anchor_days=group.anchor_days, member_count=len(wanted),
    )


# --------------------------------------------------------------------------
# Overrides: desks and bookings (FR-8.6)
# --------------------------------------------------------------------------


class OutOfServiceIn(BaseModel):
    #: Required, and shown to employees. "Out of service" with no reason
    #: generates a support ticket per desk per day.
    reason: str = Field(min_length=3, max_length=200)
    #: Whether to cancel the bookings already on it. Defaulting to False keeps
    #: the destructive option a decision rather than a side effect.
    release_bookings: bool = False


class OutOfServiceOut(BaseModel):
    resource: dict
    released: int


@router.post("/resources/{resource_id}/out-of-service", response_model=OutOfServiceOut)
async def take_out_of_service(
    resource_id: uuid.UUID, body: OutOfServiceIn, admin: Actor, db: Db
) -> OutOfServiceOut:
    """FR-8.6. `rule_resource_available` in app/policy.py then refuses new
    bookings on it, and the plan renders it `unavailable`.

    Existing bookings are NOT cancelled unless asked: a desk taken out of
    service from next Monday should not silently evict whoever is sitting at
    it today, and the admin who does mean that gets a count back.
    """
    repo = repo_for(admin, db)
    resource = await repo.get(Resource, resource_id)
    if resource is None:
        raise NotFound("resource")
    admin.assert_site(resource.site_id)

    resource.status = "out_of_service"
    resource.out_of_service_reason = body.reason.strip()

    released = 0
    if body.release_bookings:
        for booking in await upcoming_bookings(
            repo, Booking.resource_id == resource.id
        ):
            if await release_booking(
                db, booking, reason=f"{resource.name} out of service: {body.reason}"
            ):
                released += 1

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="resource.out_of_service", target_type="resource", target_id=resource.id,
        name=resource.name, reason=resource.out_of_service_reason,
        bookings_released=released,
    )
    await db.commit()
    return OutOfServiceOut(
        resource={
            "id": str(resource.id), "name": resource.name, "status": resource.status,
            "out_of_service_reason": resource.out_of_service_reason,
        },
        released=released,
    )


@router.delete("/resources/{resource_id}/out-of-service", response_model=OutOfServiceOut)
async def return_to_service(
    resource_id: uuid.UUID, admin: Actor, db: Db
) -> OutOfServiceOut:
    repo = repo_for(admin, db)
    resource = await repo.get(Resource, resource_id)
    if resource is None:
        raise NotFound("resource")
    admin.assert_site(resource.site_id)

    was = resource.out_of_service_reason
    resource.status = "active"
    resource.out_of_service_reason = None

    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="resource.in_service", target_type="resource", target_id=resource.id,
        name=resource.name, was=was,
    )
    await db.commit()
    return OutOfServiceOut(
        resource={
            "id": str(resource.id), "name": resource.name, "status": resource.status,
            "out_of_service_reason": None,
        },
        released=0,
    )


class AdminBookingIn(BaseModel):
    user_id: uuid.UUID
    resource_id: uuid.UUID
    on: date
    slot: Literal["day", "am", "pm"] = "day"
    #: FR-8.6. Policy exists to shape employee behaviour, not to stop an admin
    #: fixing something -- but overriding it is recorded, and it never
    #: overrides the exclusion constraint, so a desk still cannot be
    #: double-booked.
    override_policy: bool = False


class AdminBookingOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    resource_id: uuid.UUID
    resource_name: str
    local_date: date
    status: str
    created_by: uuid.UUID


@router.post("/bookings/admin", response_model=AdminBookingOut, status_code=201)
async def book_for_user(body: AdminBookingIn, admin: Actor, db: Db) -> AdminBookingOut:
    """FR-8.6/FR-2.10 -- book on behalf of someone.

    Both identities are recorded, per TDD §6.6: `user_id` is who gets the
    desk, `created_by` is who did it. An admin-created booking that looked
    self-made would make the audit log a fiction.

    `override_policy` relaxes exactly the rules in `policy.OVERRIDABLE_RULES`
    -- the horizon, the concurrent-booking limit and zone permission. Opening
    hours, blackouts, a desk that is out of service, someone else's assigned
    desk and the site capacity cap all still refuse, because they describe the
    building rather than a preference. The exclusion constraint is untouched
    either way (TDD §4.1), so this cannot double-book a desk.
    """
    repo = repo_for(admin, db)
    beneficiary = await repo.get(AppUser, body.user_id)
    if beneficiary is None:
        raise NotFound("user")
    if beneficiary.status != "active":
        raise InvalidChange(
            f"{beneficiary.display_name}'s account is deactivated. Reactivate it first."
        )

    resource = await repo.get(Resource, body.resource_id)
    if resource is None:
        raise NotFound("resource")
    admin.assert_site(resource.site_id)
    site = await repo.get(Site, resource.site_id)
    if site is None:
        raise NotFound("site")

    opens, closes = parse_opening_hours(site.opening_hours)
    start, end = slot_bounds(body.on, site.timezone, opens, closes, body.slot)

    from datetime import datetime as _dt

    booking = await create_booking(
        db, repo,
        user_id=beneficiary.id,
        resource_id=resource.id,
        start=start,
        end=end,
        now=_dt.now(tz=start.tzinfo),
        created_by=admin.user_id,
        override=body.override_policy,
    )
    audit.record(
        db, organization_id=admin.organization_id, actor_id=admin.user_id,
        action="booking.create_for", target_type="booking", target_id=booking.id,
        for_user=beneficiary.id, resource=resource.name, on=body.on,
        slot=body.slot, override_policy=body.override_policy,
    )
    await db.commit()
    return AdminBookingOut(
        id=booking.id, user_id=booking.user_id, resource_id=booking.resource_id,
        resource_name=resource.name, local_date=booking.local_date,
        status=booking.status, created_by=booking.created_by,
    )


class AdminBookingRow(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    resource_id: uuid.UUID
    resource_name: str
    site_id: uuid.UUID
    local_date: date
    status: str
    #: Set only when someone other than the beneficiary made it, because that
    #: is the only time it tells the reader anything.
    booked_by: str | None = None


@router.get("/admin/bookings", response_model=list[AdminBookingRow])
async def list_bookings_for_admin(
    admin: Actor, db: Db, on: date, site_id: uuid.UUID | None = None
):
    """FR-8.6 -- view any booking at an administered site, for one day.

    Not privacy-filtered, and that is the line worth being explicit about:
    `app/presence.py` governs what EMPLOYEES may learn about each other, and
    an admin overriding a booking has to be able to see it. FR-9.5's rule
    still holds -- this is one day at one site, the shape of an operational
    view, not the per-person attendance record a date range would give.
    """
    repo = repo_for(admin, db)
    scope = administered_site_ids(admin.grants)

    rows = await repo.list(
        Booking, Booking.local_date == on, Booking.status.notin_(RELEASED_STATUSES)
    )
    users = {u.id: u for u in await repo.list(AppUser)}
    resources = {r.id: r for r in await repo.list(Resource)}

    out = []
    for b in rows:
        if scope is not None and b.site_id not in scope:
            continue
        if site_id is not None and b.site_id != site_id:
            continue
        user = users.get(b.user_id)
        resource = resources.get(b.resource_id)
        agent = users.get(b.created_by) if b.created_by != b.user_id else None
        out.append(
            AdminBookingRow(
                id=b.id, user_id=b.user_id,
                user_name=user.display_name if user else "—",
                resource_id=b.resource_id,
                resource_name=resource.name if resource else "—",
                site_id=b.site_id, local_date=b.local_date, status=b.status,
                booked_by=agent.display_name if agent else None,
            )
        )
    return sorted(out, key=lambda r: r.resource_name)


# --------------------------------------------------------------------------
# Audit (FR-8.8)
# --------------------------------------------------------------------------


class AuditRow(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_name: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    detail: dict
    at: str


@router.get("/audit", response_model=list[AuditRow])
async def list_audit(admin: Actor, db: Db, limit: int = 100, action: str | None = None):
    """FR-8.8. Read-only by construction: there is no endpoint that edits or
    deletes an audit row, and adding one would defeat the table.

    Org admins only. A site admin's actions are logged the same way, but the
    log spans the organization and cannot be usefully narrowed to one office
    -- a role grant belongs to no site.
    """
    admin.assert_org()
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == admin.organization_id)
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    entries = list((await db.execute(stmt)).scalars())

    repo = repo_for(admin, db)
    names = {u.id: u.display_name for u in await repo.list(AppUser)}
    return [
        AuditRow(
            id=e.id, actor_id=e.actor_id, actor_name=names.get(e.actor_id),
            action=e.action, target_type=e.target_type, target_id=e.target_id,
            detail=e.detail, at=e.at.isoformat(),
        )
        for e in entries
    ]
