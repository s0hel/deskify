"""Sites, floors, bookings, me. The Phase 0 read path plus the booking write."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Grant, administers_site, is_admin
from app.authz import administered_site_ids as _administered_sites
from app.booking_service import create_booking, release_booking
from app.db import get_session
from app.deps import Principal, current_principal, principal_grants, tenant_repo
from app.errors import NotFound
from app.models import (
    AppUser,
    Booking,
    DayDeclaration,
    Floor,
    GroupMember,
    Resource,
    Site,
    UserGroup,
)
from app.policy import evaluate
from app.repository import TenantRepository
from app.timezone import local_today, parse_opening_hours, slot_bounds

router = APIRouter(tags=["core"])

Repo = Annotated[TenantRepository, Depends(tenant_repo)]
Me = Annotated[Principal, Depends(current_principal)]
Db = Annotated[AsyncSession, Depends(get_session)]
Grants = Annotated[frozenset[Grant], Depends(principal_grants)]


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    timezone: str
    capacity_cap: int | None
    check_in_enabled: bool


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    name: str
    capacity: int
    attributes: dict
    status: str
    plan_x: float | None
    plan_y: float | None


class FloorOut(BaseModel):
    """The heavy, stable, cacheable half of the floor-plan read (TDD §5.2).
    Availability comes from /floors/{id}/state so this stays ETag-able and
    storable offline."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    ordinal: int
    plan_width: int | None
    plan_height: int | None
    #: Names the drawing behind the desks. The client resolves it to
    #: /plans/<key>.svg; the API deliberately does not return a URL, because
    #: where the asset is served from is the client's business (native builds
    #: ship it in the bundle, the web build serves it from the origin).
    plan_asset_key: str | None
    resources: list[ResourceOut]


class MeOut(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    display_name: str
    locale: str
    presence_visibility: str
    teams: list[str]
    #: The office the user picked as their usual one (FR-1.9). NULL until they
    #: pick, which is how the client knows `home_site` below is a guess rather
    #: than their answer.
    home_site_id: uuid.UUID | None
    #: The site the app opens on: the chosen one, or the org's first by name
    #: when there is no choice yet. Resolved HERE, not in the client, so
    #: "which office am I looking at?" has exactly one answer (FR-2.1).
    #: NULL only for an org with no sites at all.
    home_site: SiteOut | None
    #: FR-1.8. Whether to offer the admin console at all. The client uses this
    #: to decide whether the entry point exists; it is NOT the permission --
    #: every admin endpoint re-checks the grants itself, because a client that
    #: shows a button is not a client that may press it.
    is_admin: bool = False
    #: The offices this user administers, or NULL meaning every office in the
    #: org. Lets the console open on a site admin's own site rather than on a
    #: picker they have one choice in.
    administered_site_ids: list[uuid.UUID] | None = None


async def _me_out(
    repo: TenantRepository, principal: Principal, grants: frozenset[Grant] = frozenset()
) -> MeOut:
    user = await repo.get(AppUser, principal.user_id)
    if user is None:
        raise NotFound("user")

    memberships = await repo.list(GroupMember, GroupMember.user_id == user.id)
    mine = {m.group_id for m in memberships}
    teams = sorted(g.name for g in await repo.list(UserGroup) if g.id in mine)

    # A home_site_id left over from a deleted site resolves to None and falls
    # back, rather than opening the app on nothing.
    chosen = await repo.get(Site, user.home_site_id) if user.home_site_id else None
    if chosen is None:
        sites = sorted(await repo.list(Site), key=lambda s: s.name)
        chosen = sites[0] if sites else None

    admin = is_admin(grants)
    scope = _administered_sites(grants) if admin else set()

    return MeOut(
        user_id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        presence_visibility=user.presence_visibility,
        teams=teams,
        home_site_id=user.home_site_id,
        home_site=SiteOut.model_validate(chosen) if chosen else None,
        is_admin=admin,
        administered_site_ids=None if scope is None else sorted(scope, key=str),
    )


@router.get("/me", response_model=MeOut)
async def me(principal: Me, repo: Repo, grants: Grants) -> MeOut:
    return await _me_out(repo, principal, grants)


class HomeSiteIn(BaseModel):
    site_id: uuid.UUID


@router.put("/me/home-site", response_model=MeOut)
async def set_home_site(
    body: HomeSiteIn, principal: Me, repo: Repo, db: Db, grants: Grants
) -> MeOut:
    """FR-1.9 -- choose the office you usually work from.

    Another tenant's site id is 404, not 403 (TDD §15.1). A 403 would confirm
    that the id names a real site somewhere, which is the disclosure the whole
    tenancy layer exists to prevent. The path-driven cross-tenant harness
    cannot reach this one -- the id is in the body -- so it is covered
    explicitly in tests/test_home_site.py.
    """
    user = await repo.get(AppUser, principal.user_id)
    if user is None:
        raise NotFound("user")

    site = await repo.get(Site, body.site_id)
    if site is None:
        raise NotFound("site")

    user.home_site_id = site.id
    await db.commit()
    return await _me_out(repo, principal, grants)


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(repo: Repo) -> list[Site]:
    return await repo.list(Site)


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(site_id: uuid.UUID, repo: Repo) -> Site:
    site = await repo.get(Site, site_id)
    if site is None:
        raise NotFound("site")
    return site


class DayOut(BaseModel):
    """One day in the 7-day strip (FR-2.1)."""

    date: date
    free: int
    total: int
    capacity_cap: int | None
    my_booking_id: uuid.UUID | None
    my_resource_name: str | None
    declaration: str | None


@router.get("/sites/{site_id}/days", response_model=list[DayOut])
async def site_days(site_id: uuid.UUID, repo: Repo, principal: Me, days: int = 7) -> list[DayOut]:
    """Per-day availability and the user's own booking, for the home strip.

    One query per concept rather than one per day: the client used to need N
    round trips to colour a week, which is the kind of thing that makes a home
    screen feel slow on a train.
    """
    site = await repo.get(Site, site_id)
    if site is None:
        raise NotFound("site")

    start = local_today(site.timezone)
    window = [start + timedelta(days=i) for i in range(max(1, min(days, 31)))]

    bookable = await repo.list(
        Resource,
        Resource.site_id == site.id,
        Resource.kind == "desk",
        Resource.status == "active",
    )
    total = len(bookable)

    bookings = await repo.list(
        Booking,
        Booking.site_id == site.id,
        Booking.local_date >= window[0],
        Booking.local_date <= window[-1],
        Booking.status.notin_(("cancelled", "released_no_show")),
    )
    names = {r.id: r.name for r in bookable}

    taken: dict[date, int] = {}
    mine: dict[date, Booking] = {}
    for b in bookings:
        taken[b.local_date] = taken.get(b.local_date, 0) + 1
        if b.user_id == principal.user_id:
            mine[b.local_date] = b

    declarations = await repo.list(
        DayDeclaration,
        DayDeclaration.user_id == principal.user_id,
        DayDeclaration.local_date >= window[0],
        DayDeclaration.local_date <= window[-1],
    )
    declared = {d.local_date: d.kind for d in declarations}

    out: list[DayOut] = []
    for d in window:
        used = taken.get(d, 0)
        free = max(0, total - used)
        if site.capacity_cap is not None:
            free = min(free, max(0, site.capacity_cap - used))
        booking = mine.get(d)
        out.append(
            DayOut(
                date=d,
                free=free,
                total=total,
                capacity_cap=site.capacity_cap,
                my_booking_id=booking.id if booking else None,
                my_resource_name=names.get(booking.resource_id) if booking else None,
                declaration=declared.get(d),
            )
        )
    return out


class FloorSummaryOut(BaseModel):
    """Floors without their resources -- the picker needs names, not 300 desks."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    ordinal: int
    #: Desks free on `on`, so the picker can answer the question people
    #: actually open it with: which floor has space? Without this the client
    #: would need a /state call per floor to colour a list of names.
    free: int
    total: int


@router.get("/sites/{site_id}/floors", response_model=list[FloorSummaryOut])
async def list_floors(
    site_id: uuid.UUID, repo: Repo, on: date | None = None
) -> list[FloorSummaryOut]:
    site = await repo.get(Site, site_id)
    if site is None:
        raise NotFound("site")

    day = on or local_today(site.timezone)
    floors = sorted(await repo.list(Floor, Floor.site_id == site.id), key=lambda f: f.ordinal)

    desks = await repo.list(
        Resource,
        Resource.site_id == site.id,
        Resource.kind == "desk",
        Resource.status == "active",
    )
    bookings = await repo.list(
        Booking,
        Booking.site_id == site.id,
        Booking.local_date == day,
        Booking.status.notin_(("cancelled", "released_no_show")),
    )
    floor_of = {d.id: d.floor_id for d in desks}

    total: dict[uuid.UUID, int] = {}
    for desk in desks:
        if desk.floor_id is not None:
            total[desk.floor_id] = total.get(desk.floor_id, 0) + 1

    taken: dict[uuid.UUID, int] = {}
    for booking in bookings:
        floor_id = floor_of.get(booking.resource_id)
        # A room booking has no desk to take, so it is not counted here.
        if floor_id is not None:
            taken[floor_id] = taken.get(floor_id, 0) + 1

    return [
        FloorSummaryOut(
            id=f.id,
            name=f.name,
            ordinal=f.ordinal,
            total=total.get(f.id, 0),
            free=max(0, total.get(f.id, 0) - taken.get(f.id, 0)),
        )
        for f in floors
    ]


@router.get("/floors/{floor_id}", response_model=FloorOut)
async def get_floor(floor_id: uuid.UUID, repo: Repo) -> FloorOut:
    floor = await repo.get(Floor, floor_id)
    if floor is None:
        raise NotFound("floor")
    resources = await repo.list(Resource, Resource.floor_id == floor.id)
    return FloorOut(
        id=floor.id, name=floor.name, ordinal=floor.ordinal,
        plan_width=floor.plan_width, plan_height=floor.plan_height,
        plan_asset_key=floor.plan_asset_key,
        resources=[ResourceOut.model_validate(r) for r in resources],
    )


class FloorStateOut(BaseModel):
    """The small, volatile half. Deliberately a separate endpoint."""
    date: date
    states: dict[uuid.UUID, str]


@router.get("/floors/{floor_id}/state", response_model=FloorStateOut)
async def floor_state(floor_id: uuid.UUID, on: date, repo: Repo, principal: Me) -> FloorStateOut:
    floor = await repo.get(Floor, floor_id)
    if floor is None:
        raise NotFound("floor")
    resources = await repo.list(Resource, Resource.floor_id == floor.id)
    bookings = await repo.list(
        Booking,
        Booking.local_date == on,
        Booking.status.notin_(("cancelled", "released_no_show")),
    )
    taken = {b.resource_id: b for b in bookings}
    states: dict[uuid.UUID, str] = {}
    for r in resources:
        if r.status != "active":
            states[r.id] = "unavailable"
        elif r.id in taken:
            states[r.id] = "mine" if taken[r.id].user_id == principal.user_id else "booked"
        elif r.assigned_user_id and r.assigned_user_id != principal.user_id:
            states[r.id] = "assigned"
        else:
            states[r.id] = "free"
    return FloorStateOut(date=on, states=states)


class CreateBookingRequest(BaseModel):
    resource_id: uuid.UUID
    on: date
    slot: Literal["day", "am", "pm"] = "day"


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_id: uuid.UUID
    user_id: uuid.UUID
    local_date: date
    status: str


async def _resolve_slot(repo: TenantRepository, resource_id: uuid.UUID, on: date, slot: str):
    resource = await repo.get(Resource, resource_id)
    if resource is None:
        raise NotFound("resource")
    site = await repo.get(Site, resource.site_id)
    if site is None:
        raise NotFound("site")
    opens, closes = parse_opening_hours(site.opening_hours)
    start, end = slot_bounds(on, site.timezone, opens, closes, slot)
    return resource, site, start, end


@router.post("/bookings", response_model=BookingOut, status_code=201)
async def post_booking(body: CreateBookingRequest, repo: Repo, principal: Me, db: Db) -> Booking:
    _, _, start, end = await _resolve_slot(repo, body.resource_id, body.on, body.slot)
    booking = await create_booking(
        db, repo, user_id=principal.user_id, resource_id=body.resource_id,
        start=start, end=end, now=datetime.now(tz=start.tzinfo),
    )
    await db.commit()
    return booking


@router.post("/bookings/validate")
async def validate_booking(body: CreateBookingRequest, repo: Repo, principal: Me, db: Db) -> dict:
    """The dry run (TDD §5.2). Identical PolicyContext and rule set as the write
    path, so the UI can explain a refusal BEFORE the user commits (FR-6.9)."""
    from app.booking_service import build_context

    resource, site, start, end = await _resolve_slot(repo, body.resource_id, body.on, body.slot)
    ctx = await build_context(
        db, repo, user_id=principal.user_id, resource=resource, site=site,
        start=start, end=end, now=datetime.now(tz=start.tzinfo),
    )
    denials = evaluate(ctx)
    return {"allowed": not denials, "denials": [d.as_dict() for d in denials]}


@router.get("/bookings", response_model=list[BookingOut])
async def list_bookings(repo: Repo, principal: Me) -> list[Booking]:
    return await repo.list(
        Booking,
        Booking.user_id == principal.user_id,
        Booking.status.notin_(("cancelled", "released_no_show")),
    )


@router.delete("/bookings/{booking_id}", status_code=204)
async def cancel_booking(
    booking_id: uuid.UUID, repo: Repo, db: Db, principal: Me, grants: Grants
) -> None:
    """FR-2.12 for the person who made it, FR-8.6 for an administrator.

    IT IS YOURS OR YOU ADMINISTER THE SITE. The repository scopes by
    organization, which is not the same as by user: before this check, any
    employee could cancel any colleague's desk by id.

    Somebody else's booking is 404 rather than 403, matching the tenancy layer
    -- a 403 would confirm that the id names a real booking, and "does
    <this id> exist" is exactly what an employee should not be able to ask
    about a colleague whose presence is hidden from them (FR-5.6).

    Releasing goes through `release_booking` so the day's capacity counter is
    decremented here exactly as it is for an admin override or a deactivation.
    """
    booking = await repo.get(Booking, booking_id)
    if booking is None:
        raise NotFound("booking")
    if booking.user_id != principal.user_id and not administers_site(grants, booking.site_id):
        raise NotFound("booking")

    await release_booking(db, booking)
    await db.commit()
