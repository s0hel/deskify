"""Sites, floors, bookings, me. The Phase 0 read path plus the booking write."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking_service import create_booking
from app.db import get_session
from app.deps import Principal, current_principal, tenant_repo
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
    resources: list[ResourceOut]


class MeOut(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    display_name: str
    locale: str
    presence_visibility: str
    teams: list[str]


@router.get("/me", response_model=MeOut)
async def me(principal: Me, repo: Repo) -> MeOut:
    user = await repo.get(AppUser, principal.user_id)
    if user is None:
        raise NotFound("user")

    memberships = await repo.list(GroupMember, GroupMember.user_id == user.id)
    mine = {m.group_id for m in memberships}
    teams = sorted(g.name for g in await repo.list(UserGroup) if g.id in mine)

    return MeOut(
        user_id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        presence_visibility=user.presence_visibility,
        teams=teams,
    )


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


@router.get("/sites/{site_id}/floors", response_model=list[FloorSummaryOut])
async def list_floors(site_id: uuid.UUID, repo: Repo) -> list[Floor]:
    site = await repo.get(Site, site_id)
    if site is None:
        raise NotFound("site")
    floors = await repo.list(Floor, Floor.site_id == site.id)
    return sorted(floors, key=lambda f: f.ordinal)


@router.get("/floors/{floor_id}", response_model=FloorOut)
async def get_floor(floor_id: uuid.UUID, repo: Repo) -> FloorOut:
    floor = await repo.get(Floor, floor_id)
    if floor is None:
        raise NotFound("floor")
    resources = await repo.list(Resource, Resource.floor_id == floor.id)
    return FloorOut(
        id=floor.id, name=floor.name, ordinal=floor.ordinal,
        plan_width=floor.plan_width, plan_height=floor.plan_height,
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
async def cancel_booking(booking_id: uuid.UUID, repo: Repo, db: Db) -> None:
    booking = await repo.get(Booking, booking_id)
    if booking is None:
        raise NotFound("booking")
    booking.status = "cancelled"
    await db.commit()
