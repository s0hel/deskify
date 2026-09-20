"""FR-1.9 -- the office you usually work from.

Two things are being held here. The first is that /me answers "which office
does this app open on?" itself, so the client never has to guess; the second is
that the id in the request body is checked against the caller's tenant exactly
like a path id would be. The cross-tenant harness is path-driven and cannot
reach a body parameter, so that case is asserted by hand below -- see the note
in tests/test_cross_tenant.py::NO_OBJECT_ID.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import mint_access_token
from app.db import get_session
from app.main import app
from app.models import Site
from tests.conftest import make_org


@pytest.fixture
def client(db):
    async def override():
        # mirrors app.db.get_session's rollback contract
        try:
            yield db
        except Exception:
            await db.rollback()
            raise

    app.dependency_overrides[get_session] = override
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def add_site(db, fx, name: str, tz: str = "America/New_York") -> Site:
    site = Site(
        organization_id=fx["org"].id,
        name=name,
        timezone=tz,
        opening_hours={"open": "08:00", "close": "18:00"},
    )
    db.add(site)
    await db.flush()
    await db.commit()
    return site


def auth_for(fx) -> dict:
    return {"Authorization": f"Bearer {mint_access_token(fx['user'].id, fx['org'].id)}"}


async def test_me_falls_back_to_a_real_site_before_anyone_has_chosen(db, client):
    """A user who has never been through onboarding still lands somewhere.

    The fallback is reported as a fallback: home_site_id stays null, so the UI
    can tell "Tampa, because you picked it" from "Tampa, because it was first".
    """
    fx = await make_org(db, "Northwind")

    async with client as c:
        body = (await c.get("/me", headers=auth_for(fx))).json()

    assert body["home_site_id"] is None
    assert body["home_site"]["name"] == "Northwind HQ"


async def test_the_fallback_is_the_first_site_by_name_not_by_insertion(db, client):
    """Deliberately deterministic. `repo.list` has no inherent order, so
    without the sort the app would open on a different office run to run."""
    fx = await make_org(db, "Northwind")  # "Northwind HQ"
    await add_site(db, fx, "Amsterdam Zuid")

    async with client as c:
        body = (await c.get("/me", headers=auth_for(fx))).json()

    assert body["home_site"]["name"] == "Amsterdam Zuid"


async def test_choosing_an_office_sticks(db, client):
    fx = await make_org(db, "Northwind")
    tampa = await add_site(db, fx, "Tampa")

    async with client as c:
        auth = auth_for(fx)
        put = await c.put("/me/home-site", json={"site_id": str(tampa.id)}, headers=auth)
        assert put.status_code == 200, put.text
        assert put.json()["home_site"]["name"] == "Tampa"
        # The response is a whole MeOut, so the client can cache it without a
        # second round trip -- and this asserts the two agree.
        assert (await c.get("/me", headers=auth)).json() == put.json()


async def test_the_chosen_office_wins_over_the_alphabetical_fallback(db, client):
    fx = await make_org(db, "Northwind")
    await add_site(db, fx, "Amsterdam Zuid")
    tampa = await add_site(db, fx, "Tampa")

    async with client as c:
        auth = auth_for(fx)
        await c.put("/me/home-site", json={"site_id": str(tampa.id)}, headers=auth)
        body = (await c.get("/me", headers=auth)).json()

    assert body["home_site_id"] == str(tampa.id)
    assert body["home_site"]["name"] == "Tampa"


async def test_a_site_that_does_not_exist_is_404(db, client):
    fx = await make_org(db, "Northwind")

    async with client as c:
        resp = await c.put(
            "/me/home-site", json={"site_id": str(uuid.uuid4())}, headers=auth_for(fx)
        )

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_another_tenants_site_cannot_become_your_home(db, client):
    """The body-parameter case the path-driven harness cannot reach.

    404 rather than 403: a 403 would confirm Globex's site id names a real
    site (TDD §15.1). And the refused write must not have landed.
    """
    acme = await make_org(db, "Acme")
    globex = await make_org(db, "Globex")

    async with client as c:
        auth = auth_for(acme)
        resp = await c.put(
            "/me/home-site", json={"site_id": str(globex["site"].id)}, headers=auth
        )
        assert resp.status_code == 404, resp.text

        after = (await c.get("/me", headers=auth)).json()

    assert after["home_site_id"] is None
    assert after["home_site"]["name"] == "Acme HQ"


async def test_a_home_site_that_has_since_gone_falls_back(db, client):
    """A stale pointer opens the app on a real office rather than on nothing."""
    fx = await make_org(db, "Northwind")
    tampa = await add_site(db, fx, "Tampa")

    async with client as c:
        auth = auth_for(fx)
        await c.put("/me/home-site", json={"site_id": str(tampa.id)}, headers=auth)

        await db.delete(tampa)
        await db.commit()

        body = (await c.get("/me", headers=auth)).json()

    assert body["home_site_id"] == str(tampa.id)  # still what the row says
    assert body["home_site"]["name"] == "Northwind HQ"  # but not what we show
