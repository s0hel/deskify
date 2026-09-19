"""Seed a demo tenant. `make seed`.

Deliberately generates 300 desks on one floor: that is the number PRD §9.1
sets as the floor-plan performance budget, so the seeded data is the spike
fixture (TDD §9.3, risk R8) rather than a toy.
"""

import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from app.models import AppUser, EmailDomain, Floor, Organization, Resource, Site, Zone

PLAN_W, PLAN_H = 1600, 1000
DESKS = 300


async def seed() -> None:
    async with SessionLocal() as s:
        for t in ("booking", "site_day_capacity", "resource", "zone", "floor",
                  "day_declaration", "app_user", "site", "email_domain", "policy",
                  "audit_log", "idempotency_key", "job", "organization"):
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

        s.add_all([
            AppUser(organization_id=org.id, email="priya@northwind.example",
                    display_name="Priya", home_site_id=site.id),
            AppUser(organization_id=org.id, email="marcus@northwind.example",
                    display_name="Marcus", home_site_id=site.id),
        ])
        await s.commit()

        print(f"seeded org={org.id}")
        print(f"       site={site.id} ({site.name}, {site.timezone})")
        print(f"       floor={floor.id} plan={PLAN_W}x{PLAN_H} desks={DESKS} rooms=3")
        print("       sign in as priya@northwind.example")


if __name__ == "__main__":
    asyncio.run(seed())
