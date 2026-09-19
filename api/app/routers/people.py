"""Colleagues, teams, declarations and privacy. FR-5.x.

Everything here can disclose where a named employee physically is, so every
query is constrained by `app.presence.visible_user_ids`. There is no endpoint in
this module that reads a person without that filter.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import Principal, current_principal, tenant_repo
from app.errors import NotFound
from app.models import (
    AppUser,
    Booking,
    DayDeclaration,
    Floor,
    GroupMember,
    Organization,
    Resource,
    Site,
    UserGroup,
)
from app.presence import presence_enabled, visible_user_ids
from app.repository import TenantRepository
from app.timezone import local_today

router = APIRouter(tags=["people"])

Repo = Annotated[TenantRepository, Depends(tenant_repo)]
Me = Annotated[Principal, Depends(current_principal)]
Db = Annotated[AsyncSession, Depends(get_session)]

SCHEDULE_DAYS = 14


async def _org(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    org = (
        await session.execute(select(Organization).where(Organization.id == organization_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFound("organization")
    return org


async def _visible_ids(session: AsyncSession, principal: Principal) -> set[uuid.UUID]:
    org = await _org(session, principal.organization_id)
    rows = await session.execute(
        visible_user_ids(
            principal.organization_id,
            principal.user_id,
            org_presence_enabled=presence_enabled(org),
        )
    )
    return set(rows.scalars())


async def _my_group_names(repo: TenantRepository, user_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """group_id -> name, for the groups the viewer belongs to."""
    memberships = await repo.list(GroupMember, GroupMember.user_id == user_id)
    if not memberships:
        return {}
    groups = await repo.list(UserGroup)
    mine = {m.group_id for m in memberships}
    return {g.id: g.name for g in groups if g.id in mine}


class PersonOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    is_you: bool
    shared_teams: list[str]
    resource_name: str | None = None
    floor_name: str | None = None
    declaration: str | None = None


class WhosInOut(BaseModel):
    date: date
    in_office: list[PersonOut]
    away: list[PersonOut]


@router.get("/people", response_model=WhosInOut)
async def whos_in(on: date, repo: Repo, principal: Me, db: Db) -> WhosInOut:
    """FR-5.1 -- who is booked at a site on a given day.

    The visibility filter is applied to the booking query itself, so a hidden
    colleague is absent from the result rather than removed from it.
    """
    visible = await _visible_ids(db, principal)
    my_groups = await _my_group_names(repo, principal.user_id)

    bookings = await repo.list(
        Booking,
        Booking.local_date == on,
        Booking.status.notin_(("cancelled", "released_no_show")),
        Booking.user_id.in_(visible),
    )
    declarations = await repo.list(
        DayDeclaration,
        DayDeclaration.local_date == on,
        DayDeclaration.user_id.in_(visible),
    )

    users = {u.id: u for u in await repo.list(AppUser)}
    resources = {r.id: r for r in await repo.list(Resource)}
    floors = {f.id: f.name for f in await repo.list(Floor)}

    memberships = await repo.list(GroupMember)
    shared_by_user: dict[uuid.UUID, list[str]] = {}
    for m in memberships:
        if m.group_id in my_groups:
            shared_by_user.setdefault(m.user_id, []).append(my_groups[m.group_id])

    def person(user_id: uuid.UUID, **extra) -> PersonOut | None:
        user = users.get(user_id)
        if user is None:
            return None
        return PersonOut(
            user_id=user.id,
            display_name=user.display_name,
            is_you=user.id == principal.user_id,
            shared_teams=sorted(shared_by_user.get(user.id, [])),
            **extra,
        )

    in_office: list[PersonOut] = []
    booked_users = set()
    for b in bookings:
        resource = resources.get(b.resource_id)
        entry = person(
            b.user_id,
            resource_name=resource.name if resource else None,
            floor_name=floors.get(resource.floor_id) if resource and resource.floor_id else None,
        )
        if entry:
            in_office.append(entry)
            booked_users.add(b.user_id)

    away: list[PersonOut] = []
    for d in declarations:
        if d.kind == "office" or d.user_id in booked_users:
            continue
        entry = person(d.user_id, declaration=d.kind)
        if entry:
            away.append(entry)

    # Your own row first, then teammates, then everyone else.
    def order(p: PersonOut) -> tuple:
        return (not p.is_you, not p.shared_teams, p.display_name.lower())

    return WhosInOut(date=on, in_office=sorted(in_office, key=order), away=sorted(away, key=order))


class ScheduleDay(BaseModel):
    date: date
    kind: Literal["office", "remote", "leave", "none"]
    resource_id: uuid.UUID | None = None
    resource_name: str | None = None
    floor_id: uuid.UUID | None = None
    floor_name: str | None = None


class PersonDetailOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    is_you: bool
    shared_teams: list[str]
    in_office_days: int
    horizon_days: int
    schedule: list[ScheduleDay]


@router.get("/people/{user_id}", response_model=PersonDetailOut)
async def person_detail(user_id: uuid.UUID, repo: Repo, principal: Me, db: Db) -> PersonDetailOut:
    """FR-5.2 -- one colleague's upcoming office days.

    A colleague whose presence is hidden from you returns 404, not 403. A 403
    would confirm that the person exists and has hidden themselves, which is
    itself a disclosure (same reasoning as TDD §15.1).
    """
    visible = await _visible_ids(db, principal)
    if user_id not in visible:
        raise NotFound("person")

    user = await repo.get(AppUser, user_id)
    if user is None:
        raise NotFound("person")

    sites = await repo.list(Site)
    timezone = sites[0].timezone if sites else "UTC"
    start = local_today(timezone)
    window = [start + timedelta(days=i) for i in range(SCHEDULE_DAYS)]

    bookings = {
        b.local_date: b
        for b in await repo.list(
            Booking,
            Booking.user_id == user_id,
            Booking.local_date >= window[0],
            Booking.local_date <= window[-1],
            Booking.status.notin_(("cancelled", "released_no_show")),
        )
    }
    declarations = {
        d.local_date: d.kind
        for d in await repo.list(
            DayDeclaration,
            DayDeclaration.user_id == user_id,
            DayDeclaration.local_date >= window[0],
            DayDeclaration.local_date <= window[-1],
        )
    }
    resources = {r.id: r for r in await repo.list(Resource)}
    floors = {f.id: f.name for f in await repo.list(Floor)}

    schedule: list[ScheduleDay] = []
    for d in window:
        booking = bookings.get(d)
        if booking:
            resource = resources.get(booking.resource_id)
            schedule.append(
                ScheduleDay(
                    date=d,
                    kind="office",
                    resource_id=resource.id if resource else None,
                    resource_name=resource.name if resource else None,
                    floor_id=resource.floor_id if resource else None,
                    floor_name=floors.get(resource.floor_id) if resource else None,
                )
            )
        else:
            declared = declarations.get(d)
            schedule.append(
                ScheduleDay(date=d, kind=declared if declared in ("remote", "leave") else "none")
            )

    my_groups = await _my_group_names(repo, principal.user_id)
    their_memberships = await repo.list(GroupMember, GroupMember.user_id == user_id)
    shared = sorted(my_groups[m.group_id] for m in their_memberships if m.group_id in my_groups)

    return PersonDetailOut(
        user_id=user.id,
        display_name=user.display_name,
        is_you=user.id == principal.user_id,
        shared_teams=shared,
        in_office_days=sum(1 for s in schedule if s.kind == "office"),
        horizon_days=SCHEDULE_DAYS,
        schedule=schedule,
    )


class PrivacyIn(BaseModel):
    presence_visibility: Literal["everyone", "team", "nobody"]


class PrivacyOut(BaseModel):
    presence_visibility: str


@router.put("/me/privacy", response_model=PrivacyOut)
async def set_privacy(body: PrivacyIn, repo: Repo, principal: Me, db: Db) -> PrivacyOut:
    """FR-5.6."""
    user = await repo.get(AppUser, principal.user_id)
    if user is None:
        raise NotFound("user")
    user.presence_visibility = body.presence_visibility
    await db.commit()
    return PrivacyOut(presence_visibility=user.presence_visibility)


class DeclarationIn(BaseModel):
    kind: Literal["office", "remote", "leave"]


class DeclarationOut(BaseModel):
    date: date
    kind: str


@router.put("/me/declarations/{on}", response_model=DeclarationOut)
async def set_declaration(
    on: date, body: DeclarationIn, repo: Repo, principal: Me, db: Db
) -> DeclarationOut:
    """FR-5.5 -- declare a day without booking a desk, so the team grid is
    complete rather than merely silent about you."""
    existing = await repo.list(
        DayDeclaration,
        DayDeclaration.user_id == principal.user_id,
        DayDeclaration.local_date == on,
    )
    if existing:
        existing[0].kind = body.kind
    else:
        repo.add(DayDeclaration(user_id=principal.user_id, local_date=on, kind=body.kind))
    await db.commit()
    return DeclarationOut(date=on, kind=body.kind)


@router.delete("/me/declarations/{on}", status_code=204)
async def clear_declaration(on: date, repo: Repo, principal: Me, db: Db) -> None:
    for d in await repo.list(
        DayDeclaration,
        DayDeclaration.user_id == principal.user_id,
        DayDeclaration.local_date == on,
    ):
        await db.delete(d)
    await db.commit()
