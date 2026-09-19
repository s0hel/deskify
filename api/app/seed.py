"""Seed a demo tenant. `make seed`.

Deliberately generates 300 desks on one floor: that is the number PRD §9.1
sets as the floor-plan performance budget, so the seeded data is the spike
fixture (TDD §9.3, risk R8) rather than a toy.
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

        site = Site(
            organization_id=org.id, name="Berlin Mitte", timezone="Europe/Berlin",
            opening_hours={"open": "08:00", "close": "18:00"},
            geofence_lat=52.5200, geofence_lng=13.4050, geofence_radius_m=150,
        )
        s.add(site)
        await s.flush()

        floor = Floor(organization_id=org.id, site_id=site.id, name="4F", ordinal=4,
                      plan_width=PLAN_W, plan_height=PLAN_H)
        s.add(floor)
        await s.flush()

        zones = []
        for i, name in enumerate(["Engineering", "Design", "Sales", "Quiet"]):
            z = Zone(organization_id=org.id, floor_id=floor.id, name=name,
                     polygon=[[i * 400, 0], [(i + 1) * 400, 0],
                              [(i + 1) * 400, PLAN_H], [i * 400, PLAN_H]])
            zones.append(z)
        s.add_all(zones)
        await s.flush()

        cols, gap = 20, 70
        for i in range(DESKS):
            row, col = divmod(i, cols)
            x = 60 + col * gap
            y = 70 + row * gap
            s.add(Resource(
                organization_id=org.id, site_id=site.id, floor_id=floor.id,
                zone_id=zones[min(int(x // 400), 3)].id,
                kind="desk", name=f"4F-A-{i + 1:03d}",
                attributes={
                    "sit_stand": i % 3 == 0,
                    "monitors": 2 if i % 4 else 1,
                    "window": col in (0, cols - 1),
                    "accessible": i % 25 == 0,
                },
                plan_x=float(x), plan_y=float(y),
            ))

        for i, name in enumerate(["Kepler", "Curie", "Turing"]):
            s.add(Resource(
                organization_id=org.id, site_id=site.id, floor_id=floor.id,
                zone_id=zones[2].id, kind="room", name=name, capacity=(i + 2) * 3,
                attributes={"display": True, "vc": i != 2, "whiteboard": True},
                plan_x=1400.0, plan_y=120.0 + i * 180,
            ))

        # People, with a spread of visibility settings so the privacy rule is
        # visible in the demo rather than only in the tests.
        people = [
            ("Priya Raman", "priya", "everyone", ("Engineering",)),
            ("Marcus Hale", "marcus", "everyone", ("Engineering",)),
            ("Ana Torres", "ana", "everyone", ("Engineering", "Fire Wardens")),
            ("Dana Okafor", "dana", "team", ("Design",)),
            ("Sam Whitfield", "sam", "team", ("Engineering",)),
            ("Jo Lindqvist", "jo", "nobody", ("Design",)),
            ("Ren Takahashi", "ren", "everyone", ("Sales",)),
            ("Nadia Farouk", "nadia", "everyone", ("Sales", "Fire Wardens")),
        ]

        groups: dict[str, UserGroup] = {}
        users: dict[str, AppUser] = {}
        for display, handle, visibility, group_names in people:
            user = AppUser(
                organization_id=org.id,
                email=f"{handle}@northwind.example",
                display_name=display,
                home_site_id=site.id,
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
        desks_by_name = {r.name: r for r in await _desks(s, org.id)}

        # Spread across WEEKDAYS, not raw day offsets. Seeding today+0..3 when
        # today is a Saturday puts most of the demo data on a weekend, and the
        # team week grid then looks broken rather than quiet.
        upcoming = [today + timedelta(days=i) for i in range(14)]
        # Index 0 is always TODAY, so the home screen has something in it even
        # at a weekend; the rest are weekdays, so the team grid does too.
        weekdays = [today] + [d for d in upcoming if d.weekday() < 5 and d != today][:6]

        plans = [
            ("marcus", 0, "4F-A-023"),
            ("ana", 0, "4F-A-045"),
            ("ren", 0, "4F-A-112"),
            ("marcus", 1, "4F-A-023"),
            ("nadia", 1, "4F-A-088"),
            ("ana", 2, "4F-A-045"),
            ("sam", 2, "4F-A-067"),
            ("marcus", 3, "4F-A-023"),
            ("ana", 3, "4F-A-045"),
            ("sam", 4, "4F-A-067"),
            ("ren", 4, "4F-A-112"),
        ]
        for handle, index, desk_name in plans:
            day = weekdays[index]
            desk = desks_by_name[desk_name]
            s.add(
                Booking(
                    organization_id=org.id,
                    site_id=site.id,
                    resource_id=desk.id,
                    user_id=users[handle].id,
                    during=Range(
                        _at(day, 9, site.timezone), _at(day, 17, site.timezone), bounds="[)"
                    ),
                    local_date=day,
                    status="confirmed",
                    created_by=users[handle].id,
                )
            )

        declarations = [
            ("dana", 0, "remote"),
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
        print(f"       site={site.id} ({site.name}, {site.timezone})")
        print(f"       floor={floor.id} plan={PLAN_W}x{PLAN_H} desks={DESKS} rooms=3")
        print(f"       {len(people)} people in {len(groups)} teams, "
              f"{len(plans)} bookings, {len(declarations)} declarations")
        print("       sign in as priya@northwind.example")
        print("       (jo@northwind.example is set to 'nobody' -- she should not appear)")


if __name__ == "__main__":
    asyncio.run(seed())
