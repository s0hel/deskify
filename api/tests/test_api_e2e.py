"""The Phase 0 exit criterion, as a test.

"A developer can sign in and read a seeded site from the real API."
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app
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


async def test_sign_in_then_read_a_site_then_book_a_desk(db, client):
    fx = await make_org(db, "Northwind")

    async with client as c:
        # 1. discover -- answers for a domain
        r = await c.post("/auth/discover", json={"email": fx["user"].email})
        assert r.status_code == 200 and "idp_kind" in r.json()

        # 2. the IdP leg stands in here; it returns a one-time code, as the
        #    real /auth/callback will.
        r = await c.post("/auth/dev-sign-in", json={"email": fx["user"].email})
        code = r.json()["code"]

        # 3. redeem the code over HTTPS -- tokens never travel in a URL
        r = await c.post("/auth/token", json={"code": code})
        assert r.status_code == 200
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # 3b. the code is single use
        assert (await c.post("/auth/token", json={"code": code})).status_code == 400

        # 4. read the seeded site
        r = await c.get("/sites", headers=auth)
        assert r.status_code == 200 and r.json()[0]["name"] == "Northwind HQ"

        # 5. read the floor (heavy, cacheable half)
        r = await c.get(f"/floors/{fx['floor'].id}", headers=auth)
        assert r.status_code == 200
        assert r.json()["plan_width"] == 1000
        assert len(r.json()["resources"]) == 1

        # 6. dry-run the booking before committing to it
        payload = {"resource_id": str(fx["desk"].id), "on": "2026-10-02", "slot": "day"}
        r = await c.post("/bookings/validate", json=payload, headers=auth)
        assert r.status_code == 200 and r.json()["allowed"] is True

        # 7. book it
        r = await c.post("/bookings", json=payload, headers=auth)
        assert r.status_code == 201, r.text
        booking_id = r.json()["id"]

        # 8. the floor state now reflects it
        r = await c.get(f"/floors/{fx['floor'].id}/state",
                        params={"on": "2026-10-02"}, headers=auth)
        assert r.json()["states"][str(fx["desk"].id)] == "mine"

        # 9. booking the same desk again is refused -- and explained as YOUR
        #    booking, not as someone else having taken it
        r = await c.post("/bookings", json=payload, headers=auth)
        assert r.status_code == 409
        assert r.json()["code"] == "POLICY_DENIED"
        assert r.json()["denials"][0]["code"] == "ALREADY_HAVE_DESK"
        assert r.headers["content-type"].startswith("application/problem+json")

        # 10. cancel, and the slot reopens
        assert (await c.delete(f"/bookings/{booking_id}", headers=auth)).status_code == 204
        r = await c.post("/bookings", json=payload, headers=auth)
        assert r.status_code == 201


async def test_policy_refusal_is_explainable(db, client):
    """FR-6.9 -- the refusal names the rule that refused it."""
    fx = await make_org(db, "Acme")
    async with client as c:
        code = (await c.post("/auth/dev-sign-in",
                             json={"email": fx["user"].email})).json()["code"]
        token = (await c.post("/auth/token", json={"code": code})).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        fx["desk"].status = "out_of_service"
        fx["desk"].out_of_service_reason = "Broken monitor arm"
        await db.commit()

        r = await c.post("/bookings", json={
            "resource_id": str(fx["desk"].id), "on": "2026-10-02", "slot": "day",
        }, headers=auth)

        assert r.status_code == 409
        body = r.json()
        assert body["code"] == "POLICY_DENIED"
        assert body["denials"][0]["code"] == "RESOURCE_UNAVAILABLE"
        assert body["denials"][0]["rule_key"] == "resource_status"


async def test_a_second_desk_the_same_day_is_refused_over_http(db, client):
    """The reported bug, as any client sees it: 5F-N-03 then 5F-N-04 for one
    day. The web UI hides the second tap; the Teams bot does not, so the API
    has to say no -- in the dry run as well as on the write."""
    fx = await make_org(db, "Northwind", desks=2)
    first_desk = fx["desks"][0].name
    async with client as c:
        code = (await c.post("/auth/dev-sign-in",
                             json={"email": fx["user"].email})).json()["code"]
        token = (await c.post("/auth/token", json={"code": code})).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        first, second = (
            {"resource_id": str(d.id), "on": "2026-10-02", "slot": "day"} for d in fx["desks"]
        )
        assert (await c.post("/bookings", json=first, headers=auth)).status_code == 201

        r = await c.post("/bookings/validate", json=second, headers=auth)
        assert r.json()["allowed"] is False
        assert r.json()["denials"][0]["code"] == "ALREADY_HAVE_DESK"

        r = await c.post("/bookings", json=second, headers=auth)
        assert r.status_code == 409
        denial = r.json()["denials"][0]
        assert denial["code"] == "ALREADY_HAVE_DESK"
        assert denial["params"] == {"desk": first_desk}

        # A whole day overlaps both halves, so the afternoon is refused too.
        r = await c.post("/bookings", json={**second, "slot": "pm"}, headers=auth)
        assert r.status_code == 409

        # Cancel the whole day, take a morning, and the afternoon elsewhere is fine.
        mine = (await c.get("/bookings", headers=auth)).json()
        assert (await c.delete(f"/bookings/{mine[0]['id']}", headers=auth)).status_code == 204
        assert (await c.post("/bookings", json={**first, "slot": "am"},
                             headers=auth)).status_code == 201
        assert (await c.post("/bookings", json={**second, "slot": "pm"},
                             headers=auth)).status_code == 201
