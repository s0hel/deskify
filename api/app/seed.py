"""Seed a demo tenant. `make seed`.

Six offices, because a default office (FR-1.9) is only meaningful when there is
something to default away from, and one floor plan tells you nothing about
whether the plan component handles a floor that is not a rectangle.

The geometry is NOT here. Every desk coordinate comes out of `app.floorplans`,
which is also what `app.plans` renders to SVG -- so the seeded desks and the
drawing behind them cannot disagree. This module only decides who works where.

Tampa keeps the 300-desk floor: that is the number PRD §9.1 sets as the
floor-plan performance budget (TDD §9.3, risk R8), so the app opens on the
hard case rather than on a toy.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range

from app.db import SessionLocal
from app.floorplans import OFFICES
from app.models import (
    AppUser,
    Booking,
    DayDeclaration,
    EmailDomain,
    Floor,
    GroupMember,
    Organization,
    Resource,
    Site,
    UserGroup,
    Zone,
)
from app.timezone import local_today

ANCHOR_DAYS = {"Engineering": [2, 4], "Design": [3], "Sales": [2]}

TABLES = (
    # Child rows first. group_member references app_user, so deleting users
    # before memberships trips a foreign key -- and the seed then half-fails in
    # a way that looks like the new code is broken.
    "booking", "site_day_capacity", "day_declaration", "group_member",
    "user_group", "resource", "zone", "floor", "app_user", "site",
    "email_domain", "policy", "audit_log", "idempotency_key", "job",
    "organization",
)

#: display, handle, presence visibility, teams, home office
PEOPLE = [
    ("Priya Raman", "priya", "everyone", ("Engineering",), "Tampa"),
    ("Marcus Hale", "marcus", "everyone", ("Engineering",), "Tampa"),
    ("Ana Torres", "ana", "everyone", ("Engineering", "Fire Wardens"), "Tampa"),
    ("Dana Okafor", "dana", "team", ("Design",), "Berlin Mitte"),
    ("Sam Whitfield", "sam", "team", ("Engineering",), "Tampa"),
    ("Jo Lindqvist", "jo", "nobody", ("Design",), "Berlin Mitte"),
    ("Ren Takahashi", "ren", "everyone", ("Sales",), "London Bridge"),
    ("Nadia Farouk", "nadia", "everyone", ("Sales", "Fire Wardens"), "Tampa"),
    ("Kofi Mensah", "kofi", "everyone", ("Sales",), "Singapore Raffles"),
    ("Elena Vasquez", "elena", "everyone", ("Engineering",), "Austin Domain"),
    ("Tomas Novak", "tomas", "everyone", ("Design",), "Denver Union"),
]

#: handle, weekday index, office, desk. Ren is homed at London and sits in
#: Tampa this week on purpose: a home site is a default, not a fence, and the
#: demo should show that rather than the README assert it.
BOOKINGS = [
    ("marcus", 0, "Tampa", "4F-A-23"),
    ("ana", 0, "Tampa", "4F-B-45"),
    ("ren", 0, "Tampa", "4F-C-12"),
    ("marcus", 1, "Tampa", "4F-A-23"),
    ("nadia", 1, "Tampa", "4F-D-08"),
    ("ana", 2, "Tampa", "4F-B-45"),
    ("sam", 2, "Tampa", "4F-A-07"),
    ("marcus", 3, "Tampa", "4F-A-23"),
    ("ana", 3, "Tampa", "4F-B-45"),
    ("sam", 4, "Tampa", "4F-A-07"),
    ("ren", 4, "Tampa", "4F-C-12"),
    ("dana", 1, "Berlin Mitte", "2F-N-14"),
    ("jo", 2, "Berlin Mitte", "2F-S-07"),
    ("kofi", 1, "Singapore Raffles", "12F-A-11"),
    ("kofi", 3, "Singapore Raffles", "12F-A-11"),
    ("elena", 2, "Austin Domain", "1F-A-05"),
    ("tomas", 2, "Denver Union", "3F-A-09"),
    # Upstairs. Tampa has two floors, so the plan has to be able to land on
    # the one a booking is actually on rather than on whichever comes first.
    ("nadia", 3, "Tampa", "5F-N-06"),
    ("dana", 3, "Berlin Mitte", "3F-A-02"),
]

DECLARATIONS = [
    ("dana", 0, "remote"),
    ("jo", 0, "leave"),
    ("nadia", 0, "leave"),
    ("marcus", 2, "remote"),
    ("ren", 1, "remote"),
    ("sam", 1, "remote"),
    ("nadia", 3, "leave"),
    ("elena", 0, "remote"),
    ("tomas", 1, "remote"),
]


def _at(day, hour: int, timezone: str) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo(timezone))


async def _desks(s, org_id):
    return (
        await s.execute(
            select(Resource).where(Resource.organization_id == org_id, Resource.kind == "desk")
        )
    ).scalars().all()


async def _fit_out(s, org_id, site: Site, layout) -> Floor:
    """Turn one `floorplans.FloorPlan` into rows: the floor, its zones, and a
    resource per desk and per bookable room."""
    floor = Floor(
        organization_id=org_id, site_id=site.id, name=layout.name, ordinal=layout.ordinal,
        plan_width=layout.width, plan_height=layout.height,
        # Names /plans/<key>.svg, which the client draws behind the desks.
        plan_asset_key=layout.key,
    )
    s.add(floor)
    await s.flush()

    zones: dict[str, Zone] = {}
    for spec in layout.zones:
        r = spec.rect
        zone = Zone(
            organization_id=org_id, floor_id=floor.id, name=spec.name,
            polygon=[[r.x, r.y], [r.right, r.y], [r.right, r.bottom], [r.x, r.bottom]],
        )
        s.add(zone)
        await s.flush()
        zones[spec.name] = zone

    for desk in layout.desks:
        s.add(Resource(
            organization_id=org_id, site_id=site.id, floor_id=floor.id,
            zone_id=zones[desk.zone].id if desk.zone in zones else None,
            kind="desk", name=desk.name,
            attributes={
                "sit_stand": desk.sit_stand,
                "monitors": desk.monitors,
                "window": desk.window,
                "accessible": desk.accessible,
            },
            plan_x=float(desk.x), plan_y=float(desk.y),
        ))

    for room in layout.rooms:
        if not room.bookable:
            continue
        s.add(Resource(
            organization_id=org_id, site_id=site.id, floor_id=floor.id,
            kind="room", name=room.name, capacity=room.capacity,
            attributes={"display": True, "vc": room.capacity >= 6, "whiteboard": True},
            plan_x=float(room.rect.cx), plan_y=float(room.rect.cy),
        ))

    await s.flush()
    return floor


async def seed() -> None:
    async with SessionLocal() as s:
        for t in TABLES:
            await s.execute(text(f"DELETE FROM {t}"))

        org = Organization(name="Northwind", region="eu")
        s.add(org)
        await s.flush()

        s.add(EmailDomain(domain="northwind.example", organization_id=org.id, idp_kind="entra"))

        sites: dict[str, Site] = {}
        for office in OFFICES:
            site = Site(
                organization_id=org.id, name=office.name, timezone=office.timezone,
                opening_hours={"open": "08:00", "close": "18:00"},
                geofence_lat=office.lat, geofence_lng=office.lng, geofence_radius_m=150,
            )
            s.add(site)
            await s.flush()
            sites[office.name] = site
            for layout in office.floors:
                await _fit_out(s, org.id, site, layout)

        groups: dict[str, UserGroup] = {}
        users: dict[str, AppUser] = {}
        for display, handle, visibility, group_names, home in PEOPLE:
            user = AppUser(
                organization_id=org.id,
                email=f"{handle}@northwind.example",
                display_name=display,
                home_site_id=sites[home].id,
                presence_visibility=visibility,
            )
            s.add(user)
            await s.flush()
            users[handle] = user

            for name in group_names:
                group = groups.get(name)
                if group is None:
                    group = UserGroup(
                        organization_id=org.id, name=name, kind="team",
                        # ISO weekdays. Engineering anchors Tue/Thu, Design Wed.
                        anchor_days=ANCHOR_DAYS.get(name, []),
                    )
                    s.add(group)
                    await s.flush()
                    groups[name] = group
                s.add(GroupMember(organization_id=org.id, group_id=group.id, user_id=user.id))

        await s.flush()

        # A week with something in it. Without this the team screen is a list
        # of empty days, which demos nothing. Dates come from Tampa's calendar
        # so every office shares one week; each booking's `during` still uses
        # its OWN site's timezone (TDD §3.4).
        today = local_today(sites["Tampa"].timezone)
        upcoming = [today + timedelta(days=i) for i in range(14)]
        # Index 0 is always TODAY, so the home screen has something in it even
        # at a weekend; the rest are weekdays, so the team grid does too.
        weekdays = [today] + [d for d in upcoming if d.weekday() < 5 and d != today][:6]

        # Keyed by (site, name): desk names repeat across offices by design.
        by_name = {(r.site_id, r.name): r for r in await _desks(s, org.id)}

        for handle, index, site_name, desk_name in BOOKINGS:
            day = weekdays[index]
            at = sites[site_name]
            desk = by_name[(at.id, desk_name)]
            s.add(Booking(
                organization_id=org.id, site_id=at.id, resource_id=desk.id,
                user_id=users[handle].id,
                during=Range(_at(day, 9, at.timezone), _at(day, 17, at.timezone), bounds="[)"),
                local_date=day, status="confirmed", created_by=users[handle].id,
            ))

        for handle, index, kind in DECLARATIONS:
            s.add(DayDeclaration(
                organization_id=org.id, user_id=users[handle].id,
                local_date=weekdays[index], kind=kind,
            ))

        await s.commit()

        print(f"seeded org={org.id}")
        for office in OFFICES:
            for i, layout in enumerate(office.floors):
                label = office.name if i == 0 else ""
                tz = office.timezone if i == 0 else ""
                print(f"       {label:<20} {tz:<18} "
                      f"{layout.name:>4} {layout.width}x{layout.height} "
                      f"{layout.desk_count:>3} desks  /plans/{layout.key}.svg")
        print(f"       {len(PEOPLE)} people in {len(groups)} teams, "
              f"{len(BOOKINGS)} bookings, {len(DECLARATIONS)} declarations")
        print("       sign in as priya@northwind.example -- home office Tampa")
        print("       dana@ is homed at Berlin Mitte and kofi@ at Singapore Raffles,")
        print("       so the app opens somewhere different for each of them")
        print("       (jo@northwind.example is set to 'nobody' -- she should not appear)")


if __name__ == "__main__":
    asyncio.run(seed())
