"""Test fixtures.

Note the split: the policy tests (§16.1) touch no database at all, because the
rules are pure. Only tests that request `db` get a connection.
"""

# Settings fail closed: environment defaults to "prod", which refuses the
# development signing key (app/config.py). Opt into dev BEFORE anything imports
# app.config -- this must stay above the app imports below.
import os

os.environ.setdefault("DESKFLOW_ENVIRONMENT", "dev")

# The suite TRUNCATES every table between tests, so it must never point at the
# database you are developing against. Running `make test` should not silently
# empty the seeded demo tenant out from under a running app.
TEST_DB_NAME = "deskflow_test"
os.environ["DESKFLOW_DATABASE_URL"] = os.environ.get(
    "DESKFLOW_TEST_DATABASE_URL",
    f"postgresql+asyncpg://deskflow:deskflow@localhost:55432/{TEST_DB_NAME}",
)

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import (
    AppUser,
    Floor,
    GroupMember,
    Organization,
    Resource,
    Site,
    UserGroup,
    Zone,
)

TABLES = (
    "booking", "site_day_capacity", "resource", "zone", "floor",
    "day_declaration", "group_member", "user_group", "app_user", "site",
    "email_domain", "policy", "audit_log", "idempotency_key", "job",
    "organization",
)


def new_engine():
    # NullPool: each test owns its connections, so nothing is shared across
    # event loops.
    return create_async_engine(settings.database_url, poolclass=NullPool)


def pytest_configure(config):
    """Session setup: ensure deskflow_test exists and is migrated."""
    import asyncio
    import subprocess
    import sys

    async def ensure() -> None:
        import asyncpg

        admin = await asyncpg.connect(
            user="deskflow", password="deskflow", host="localhost",
            port=55432, database="postgres",
        )
        try:
            exists = await admin.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
            )
            if not exists:
                # CREATE DATABASE cannot run inside a transaction block.
                await admin.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        finally:
            await admin.close()

    asyncio.run(ensure())

    # ALWAYS migrate, not only on creation. A test database created before a
    # later migration would otherwise sit silently behind head, and the failure
    # surfaces as "relation does not exist" in an unrelated test.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env={**os.environ},
        check=True,
        capture_output=True,
    )


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

    # Every fixture org has one team containing its default user, so tests that
    # need a team id (and the cross-tenant harness) have one to aim at.
    team = UserGroup(
        organization_id=org.id, name="Core", kind="team", anchor_days=[2, 4]
    )
    s.add(team)
    await s.flush()
    s.add(GroupMember(organization_id=org.id, group_id=team.id, user_id=user.id))
    await s.flush()
    await s.commit()
    return {"org": org, "site": site, "floor": floor, "zone": zone,
            "desks": made, "desk": made[0], "user": user, "team": team}


async def add_person(
    s, fx, name: str, *, visibility: str = "everyone", groups: tuple[str, ...] = ()
):
    """A colleague in the same org, optionally in named groups."""
    from app.models import GroupMember, UserGroup

    org_id = fx["org"].id
    user = AppUser(
        organization_id=org_id,
        email=f"{name.lower().replace(' ', '.')}@{fx['org'].name.lower()}.example",
        display_name=name,
        presence_visibility=visibility,
    )
    s.add(user)
    await s.flush()

    existing = {g.name: g for g in (await s.execute(
        __import__("sqlalchemy").select(UserGroup).where(UserGroup.organization_id == org_id)
    )).scalars()}
    for group_name in groups:
        group = existing.get(group_name)
        if group is None:
            group = UserGroup(organization_id=org_id, name=group_name, kind="team")
            s.add(group)
            await s.flush()
            existing[group_name] = group
        s.add(GroupMember(organization_id=org_id, group_id=group.id, user_id=user.id))

    await s.flush()
    await s.commit()
    return user


async def book_for(s, fx, user, on, desk_index: int = 0):
    """Give someone a confirmed desk on a day, without going through policy."""
    from sqlalchemy.dialects.postgresql import Range

    from app.models import Booking

    desk = fx["desks"][desk_index]
    start = berlin(on.year, on.month, on.day, 9)
    end = berlin(on.year, on.month, on.day, 17)
    booking = Booking(
        organization_id=fx["org"].id,
        site_id=fx["site"].id,
        resource_id=desk.id,
        user_id=user.id,
        during=Range(start, end, bounds="[)"),
        local_date=on,
        status="confirmed",
        created_by=user.id,
    )
    s.add(booking)
    await s.flush()
    await s.commit()
    return booking


def berlin(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Europe/Berlin"))


NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
