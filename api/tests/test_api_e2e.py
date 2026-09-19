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

        # 9. booking the same desk again is refused by the constraint
        r = await c.post("/bookings", json=payload, headers=auth)
        assert r.status_code == 409
        assert r.json()["code"] == "RESOURCE_TAKEN"
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
