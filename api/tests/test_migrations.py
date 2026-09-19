"""The migration chain must work on a database that has never seen it.

This test exists because it would have caught a real bug. Revision 0001 called
`Base.metadata.create_all()` with no argument, which creates whatever the models
look like *today* rather than a snapshot of that revision. Adding UserGroup to
models.py silently made 0001 create `user_group`, so 0002 -- whose whole job is
to create it -- failed with "relation already exists".

On an existing database nothing broke, because 0001 had run back when the model
did not exist. It only surfaced on a fresh deploy, which is the worst possible
moment to find out.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from tests.conftest import TEST_DB_NAME

API_DIR = Path(__file__).resolve().parents[1]
ADMIN = {
    "user": "deskflow",
    "password": "deskflow",
    "host": "localhost",
    "port": 55432,
    "database": "postgres",
}


async def _admin():
    return await asyncpg.connect(**ADMIN)


@pytest.fixture
async def virgin_database():
    """A database created for this test and dropped afterwards."""
    name = f"deskflow_migrate_{uuid.uuid4().hex[:8]}"
    conn = await _admin()
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()

    yield name

    conn = await _admin()
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", name
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await conn.close()


def _alembic(args: list[str], database: str) -> subprocess.CompletedProcess:
    url = f"postgresql+asyncpg://deskflow:deskflow@localhost:55432/{database}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR,
        env={**os.environ, "DESKFLOW_ENVIRONMENT": "dev", "DESKFLOW_DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


async def test_the_whole_chain_applies_to_an_empty_database(virgin_database):
    result = _alembic(["upgrade", "head"], virgin_database)
    assert result.returncode == 0, result.stderr[-1500:]

    conn = await asyncpg.connect(**{**ADMIN, "database": virgin_database})
    try:
        tables = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        }
        # A table from each revision: 0001, 0002.
        assert {"booking", "user_group", "group_member"} <= tables

        # 0003's column exists exactly once and is not duplicated by 0002.
        anchor = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='user_group' AND column_name='anchor_days'"
        )
        assert anchor == 1

        # The constraint the whole design rests on survived the chain.
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='booking_no_double_allocation'"
        )
        assert definition is not None, "the exclusion constraint did not survive migration"
        assert "gist" in definition.lower()
    finally:
        await conn.close()


async def test_each_revision_applies_one_at_a_time(virgin_database):
    """Stepping through catches a revision that only works when squashed with
    its neighbours.

    The count is derived rather than hardcoded, so adding a migration extends
    this test instead of breaking it."""
    revisions = sorted(
        f.stem for f in (API_DIR / "alembic" / "versions").glob("*.py") if not f.stem.startswith("_")
    )
    assert len(revisions) >= 3, revisions

    applied = 0
    for _ in revisions:
        result = _alembic(["upgrade", "+1"], virgin_database)
        assert result.returncode == 0, result.stderr[-1000:] or result.stdout[-500:]
        applied += 1

    assert applied == len(revisions)

    conn = await asyncpg.connect(**{**ADMIN, "database": virgin_database})
    try:
        head = await conn.fetchval("SELECT version_num FROM alembic_version")
        assert head == revisions[-1].split("_")[0]
    finally:
        await conn.close()


def test_the_test_database_is_not_the_one_under_test(virgin_database):
    """Guards against this suite dropping the database the other tests use."""
    assert virgin_database != TEST_DB_NAME
