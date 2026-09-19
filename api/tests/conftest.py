"""Test fixtures.

Note the split: the policy tests (§16.1) touch no database at all, because the
rules are pure. Only tests that request `db` get a connection.
"""

# Settings fail closed: environment defaults to "prod", which refuses the
# development signing key (app/config.py). Opt into dev BEFORE anything imports
# app.config -- this must stay above the app imports below.
import os

os.environ.setdefault("DESKFLOW_ENVIRONMENT", "dev")

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import AppUser, Floor, Organization, Resource, Site, Zone

TABLES = (
    "booking", "site_day_capacity", "resource", "zone", "floor",
    "day_declaration", "app_user", "site", "email_domain", "policy",
    "audit_log", "idempotency_key", "job", "organization",
)


def new_engine():
    # NullPool: each test owns its connections, so nothing is shared across
    # event loops.
    return create_async_engine(settings.database_url, poolclass=NullPool)


@pytest_asyncio.fixture
async def db():
    engine = new_engine()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        for t in TABLES:
            await s.execute(text(f"DELETE FROM {t}"))
        await s.commit()
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def sessionmaker_factory():
    """For the concurrency test, which needs genuinely independent sessions."""
    engine = new_engine()
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def make_org(s, name="Acme", *, capacity_cap=None, tz="Europe/Berlin", desks=1):
    """A complete tenant: org, site, floor, zone, desks, and a user."""
    org = Organization(name=name, region="eu")
    s.add(org)
    await s.flush()
    site = Site(
        organization_id=org.id, name=f"{name} HQ", timezone=tz,
        opening_hours={"open": "08:00", "close": "18:00"}, capacity_cap=capacity_cap,
    )
    s.add(site)
    await s.flush()
    floor = Floor(organization_id=org.id, site_id=site.id, name="4F", ordinal=4,
                  plan_width=1000, plan_height=700)
    s.add(floor)
    await s.flush()
    zone = Zone(organization_id=org.id, floor_id=floor.id, name="Engineering", polygon=[])
    s.add(zone)
    await s.flush()
    made = []
    for i in range(desks):
        made.append(Resource(
            organization_id=org.id, site_id=site.id, floor_id=floor.id, zone_id=zone.id,
            kind="desk", name=f"4F-A-{i + 1:02d}", attributes={"sit_stand": True},
            plan_x=100 + i * 40, plan_y=100,
        ))
    user = AppUser(organization_id=org.id, email=f"priya@{name.lower()}.example",
                   display_name="Priya")
    s.add_all([*made, user])
    await s.flush()
    await s.commit()
    return {"org": org, "site": site, "floor": floor, "zone": zone,
            "desks": made, "desk": made[0], "user": user}


def berlin(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Europe/Berlin"))


NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
