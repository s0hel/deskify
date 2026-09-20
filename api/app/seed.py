"""Seed a demo tenant. `make seed`.

Deliberately generates 300 desks on one floor: that is the number PRD §9.1
sets as the floor-plan performance budget, so the seeded data is the spike
fixture (TDD §9.3, risk R8) rather than a toy. That floor is at Tampa, the
office most of the cast calls home, so the app opens on the stress case.

Three sites, not one, because a default office (FR-1.9) is only meaningful
when there is something to default away from. Ren's home is London and his
desk this week is in Tampa: a home site is where you usually are, not a
fence.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import Range

from app.db import SessionLocal
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

ANCHOR_DAYS = {"Engineering": [2, 4], "Design": [3], "Sales": [2]}

PLAN_W, PLAN_H = 1600, 1000
DESKS = 300

#: name, timezone, floor, desks, plan size, desk columns, (lat, lng)
#: Tampa first and biggest: it carries the 300-desk performance fixture and it
#: is where most of the cast sits, so `make seed` still opens the app on the
#: hard case.
SITES = [
    ("Tampa", "America/New_York", "4F", DESKS, (PLAN_W, PLAN_H), 20, (27.9506, -82.4572)),
    ("Berlin Mitte", "Europe/Berlin", "2F", 96, (1000, 760), 12, (52.5200, 13.4050)),
    ("London Bridge", "Europe/London", "1F", 60, (900, 620), 10, (51.5045, -0.0865)),
]


from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.timezone import local_today


def _at(day, hour: int, timezone: str) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo(timezone))


async def _desks(s, org_id):
    return (
        await s.execute(
            select(Resource).where(Resource.organization_id == org_id, Resource.kind == "desk")
        )
    ).scalars().all()


async def _fit_out(s, org, site, floor_name, desk_count, w, h, cols) -> Floor:
    """One floor, its zones, its desks -- and, at the biggest site, its rooms.

    Desks are named per floor (`4F-A-001`), and `resource` is unique on
    (org, site, name), so two offices can both have a `2F-A-001` without
    colliding.
    """
    floor = Floor(
        organization_id=org.id, site_id=site.id, name=floor_name,
        ordinal=int(floor_name[0]), plan_width=w, plan_height=h,
    )
    s.add(floor)
    await s.flush()

    band = w / 4
    zones = []
    for i, name in enumerate(["Engineering", "Design", "Sales", "Quiet"]):
        z = Zone(organization_id=org.id, floor_id=floor.id, name=name,
                 polygon=[[i * band, 0], [(i + 1) * band, 0],
                          [(i + 1) * band, h], [i * band, h]])
        zones.append(z)
    s.add_all(zones)
    await s.flush()

    gap = 70
    for i in range(desk_count):
        row, col = divmod(i, cols)
        x = 60 + col * gap
        y = 70 + row * gap
        s.add(Resource(
            organization_id=org.id, site_id=site.id, floor_id=floor.id,
            zone_id=zones[min(int(x // band), 3)].id,
            kind="desk", name=f"{floor_name}-A-{i + 1:03d}",
            attributes={
                "sit_stand": i % 3 == 0,
                "monitors": 2 if i % 4 else 1,
                "window": col in (0, cols - 1),
                "accessible": i % 25 == 0,
            },
            plan_x=float(x), plan_y=float(y),
        ))

    if desk_count >= DESKS:
        for i, name in enumerate(["Kepler", "Curie", "Turing"]):
            s.add(Resource(
                organization_id=org.id, site_id=site.id, floor_id=floor.id,
                zone_id=zones[2].id, kind="room", name=name, capacity=(i + 2) * 3,
                attributes={"display": True, "vc": i != 2, "whiteboard": True},
                plan_x=float(w) - 200, plan_y=120.0 + i * 180,
            ))

    await s.flush()
    return floor


async def seed() -> None:
    async with SessionLocal() as s:
        # Child rows first. group_member references app_user, so deleting users
        # before memberships trips a foreign key -- and the seed then half-fails
        # in a way that looks like the new code is broken.
        for t in (
            "booking",
            "site_day_capacity",
            "day_declaration",
            "group_member",
            "user_group",
            "resource",
            "zone",
            "floor",
            "app_user",
            "site",
            "email_domain",
            "policy",
            "audit_log",
            "idempotency_key",
            "job",
            "organization",
        ):
            await s.execute(text(f"DELETE FROM {t}"))

        org = Organization(name="Northwind", region="eu")
        s.add(org)
        await s.flush()

        s.add(EmailDomain(domain="northwind.example", organization_id=org.id, idp_kind="entra"))

        sites: dict[str, Site] = {}
        for name, tz, floor_name, desk_count, (w, h), cols, (lat, lng) in SITES:
            site = Site(
                organization_id=org.id, name=name, timezone=tz,
                opening_hours={"open": "08:00", "close": "18:00"},
                geofence_lat=lat, geofence_lng=lng, geofence_radius_m=150,
            )
            s.add(site)
            await s.flush()
            sites[name] = site
            await _fit_out(s, org, site, floor_name, desk_count, w, h, cols)

        site = sites["Tampa"]

        # People, with a spread of visibility settings so the privacy rule is
        # visible in the demo rather than only in the tests -- and a spread of
        # home sites, so FR-1.9 is too. Sign in as dana and the app opens on
        # Berlin, not on Priya's Tampa.
        people = [
            ("Priya Raman", "priya", "everyone", ("Engineering",), "Tampa"),
            ("Marcus Hale", "marcus", "everyone", ("Engineering",), "Tampa"),
            ("Ana Torres", "ana", "everyone", ("Engineering", "Fire Wardens"), "Tampa"),
            ("Dana Okafor", "dana", "team", ("Design",), "Berlin Mitte"),
            ("Sam Whitfield", "sam", "team", ("Engineering",), "Tampa"),
            ("Jo Lindqvist", "jo", "nobody", ("Design",), "Berlin Mitte"),
            ("Ren Takahashi", "ren", "everyone", ("Sales",), "London Bridge"),
            ("Nadia Farouk", "nadia", "everyone", ("Sales", "Fire Wardens"), "Tampa"),
        ]

        groups: dict[str, UserGroup] = {}
        users: dict[str, AppUser] = {}
        for display, handle, visibility, group_names, home in people:
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
                        organization_id=org.id,
                        name=name,
                        kind="team",
                        # ISO weekdays. Engineering anchors Tue/Thu, Design Wed.
                        anchor_days=ANCHOR_DAYS.get(name, []),
                    )
                    s.add(group)
                    await s.flush()
                    groups[name] = group
                s.add(
                    GroupMember(
                        organization_id=org.id, group_id=group.id, user_id=user.id
                    )
                )

        await s.flush()

        # A week with something in it. Without this the team screen is a list of
        # empty days, which demos nothing.
        today = local_today(site.timezone)
        # Keyed by (site, name): desk names repeat across offices by design.
        desks_by_name = {(r.site_id, r.name): r for r in await _desks(s, org.id)}

        # Spread across WEEKDAYS, not raw day offsets. Seeding today+0..3 when
        # today is a Saturday puts most of the demo data on a weekend, and the
        # team week grid then looks broken rather than quiet.
        upcoming = [today + timedelta(days=i) for i in range(14)]
        # Index 0 is always TODAY, so the home screen has something in it even
        # at a weekend; the rest are weekdays, so the team grid does too.
        weekdays = [today] + [d for d in upcoming if d.weekday() < 5 and d != today][:6]

        # (handle, weekday index, site, desk). Ren's home is London and his
        # desks this week are in Tampa -- a home site is a default, not a
        # fence, and the demo should show that rather than assert it.
        plans = [
            ("marcus", 0, "Tampa", "4F-A-023"),
            ("ana", 0, "Tampa", "4F-A-045"),
            ("ren", 0, "Tampa", "4F-A-112"),
            ("marcus", 1, "Tampa", "4F-A-023"),
            ("nadia", 1, "Tampa", "4F-A-088"),
            ("ana", 2, "Tampa", "4F-A-045"),
            ("sam", 2, "Tampa", "4F-A-067"),
            ("marcus", 3, "Tampa", "4F-A-023"),
            ("ana", 3, "Tampa", "4F-A-045"),
            ("sam", 4, "Tampa", "4F-A-067"),
            ("ren", 4, "Tampa", "4F-A-112"),
            ("dana", 1, "Berlin Mitte", "2F-A-014"),
            ("jo", 2, "Berlin Mitte", "2F-A-007"),
        ]
        for handle, index, site_name, desk_name in plans:
            day = weekdays[index]
            at = sites[site_name]
            desk = desks_by_name[(at.id, desk_name)]
            s.add(
                Booking(
                    organization_id=org.id,
                    site_id=at.id,
                    resource_id=desk.id,
                    user_id=users[handle].id,
                    during=Range(
                        _at(day, 9, at.timezone), _at(day, 17, at.timezone), bounds="[)"
                    ),
                    local_date=day,
                    status="confirmed",
                    created_by=users[handle].id,
                )
            )

        declarations = [
            ("dana", 0, "remote"),
            ("jo", 0, "leave"),
            ("nadia", 0, "leave"),
            ("marcus", 2, "remote"),
            ("ren", 1, "remote"),
            ("sam", 1, "remote"),
            ("nadia", 3, "leave"),
        ]
        for handle, index, kind in declarations:
            s.add(
                DayDeclaration(
                    organization_id=org.id,
                    user_id=users[handle].id,
                    local_date=weekdays[index],
                    kind=kind,
                )
            )

        await s.commit()

        print(f"seeded org={org.id}")
        for name, tz, floor_name, desk_count, (w, h), _cols, _geo in SITES:
            print(f"       site={sites[name].id} ({name}, {tz}) "
                  f"{floor_name} {w}x{h} desks={desk_count}")
        print(f"       {len(people)} people in {len(groups)} teams, "
              f"{len(plans)} bookings, {len(declarations)} declarations")
        print("       sign in as priya@northwind.example -- home site Tampa")
        print("       dana@northwind.example is homed at Berlin Mitte, so the app "
              "opens there for her")
        print("       (jo@northwind.example is set to 'nobody' -- she should not appear)")


if __name__ == "__main__":
    asyncio.run(seed())
