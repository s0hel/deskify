"""Who may cancel a booking. FR-2.12 for its owner, FR-8.6 for an admin.

The repository scopes by ORGANIZATION, which is not the same as by user.
Before this check existed, `DELETE /bookings/{id}` fetched the row through the
repository and cancelled it, so any employee could cancel any colleague's desk
by id -- and the schema-driven cross-tenant harness could not see it, because
it is a same-tenant case.
"""

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import mint_access_token
from app.db import get_session
from app.main import app
from app.timezone import local_today
from tests.conftest import add_person, book_for, grant_role, make_org

#: The fixture org is in Europe/Berlin, and a booking's day is the
#: calendar date in its SITE's timezone, never the server's (TDD §3.4).
TODAY = local_today("Europe/Berlin")


@pytest.fixture
def client(db):
    async def override():
        try:
            yield db
        except Exception:
            await db.rollback()
            raise

    app.dependency_overrides[get_session] = override
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def auth(fx, user=None) -> dict:
    user = user or fx["user"]
    return {"Authorization": f"Bearer {mint_access_token(user.id, fx['org'].id)}"}


async def test_you_can_cancel_your_own_booking(db, client):
    fx = await make_org(db, "Acme")
    booking = await book_for(db, fx, fx["user"], TODAY + timedelta(days=1))
    booking_id = booking.id

    async with client as c:
        resp = await c.delete(f"/bookings/{booking_id}", headers=auth(fx))

    assert resp.status_code == 204
    await db.refresh(booking)
    assert booking.status == "cancelled"
    assert booking.released_at is not None


async def test_a_colleague_cannot_cancel_your_booking(db, client):
    """404, not 403.

    A 403 would confirm that the id names a real booking, and "does this id
    exist" is exactly what an employee must not be able to ask about a
    colleague who has hidden their presence from them (FR-5.6). Same reasoning
    as the tenancy layer's, for the same reason.
    """
    fx = await make_org(db, "Acme")
    colleague = await add_person(db, fx, "Ren")
    booking = await book_for(db, fx, fx["user"], TODAY + timedelta(days=1))
    booking_id = booking.id

    async with client as c:
        resp = await c.delete(
            f"/bookings/{booking_id}", headers=auth(fx, colleague)
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"
    await db.refresh(booking)
    assert booking.status == "confirmed"


async def test_an_administrator_can_cancel_anyones_booking_at_their_site(db, client):
    """FR-8.6 -- override any booking. The desk has to be releasable by
    somebody when the person holding it is on a plane."""
    fx = await make_org(db, "Acme")
    colleague = await add_person(db, fx, "Ren")
    await grant_role(db, fx, fx["user"], "site_admin", scope_id=fx["site"].id)
    booking = await book_for(db, fx, colleague, TODAY + timedelta(days=1))
    booking_id = booking.id

    async with client as c:
        resp = await c.delete(f"/bookings/{booking_id}", headers=auth(fx))

    assert resp.status_code == 204
    await db.refresh(booking)
    assert booking.status == "cancelled"


async def test_an_admin_of_another_site_cannot(db, client):
    """The grant is scoped, and the booking knows which site it is at."""
    from app.models import Site

    fx = await make_org(db, "Acme")
    other = Site(
        organization_id=fx["org"].id, name="Acme Berlin", timezone="Europe/Berlin",
        opening_hours={"open": "08:00", "close": "18:00"},
    )
    db.add(other)
    await db.flush()
    await db.commit()

    colleague = await add_person(db, fx, "Ren")
    await grant_role(db, fx, fx["user"], "site_admin", scope_id=other.id)
    booking = await book_for(db, fx, colleague, TODAY + timedelta(days=1))
    booking_id = booking.id

    async with client as c:
        resp = await c.delete(f"/bookings/{booking_id}", headers=auth(fx))

    assert resp.status_code == 404
    await db.refresh(booking)
    assert booking.status == "confirmed"


async def test_cancelling_twice_is_harmless(db, client):
    """The offline outbox drains blindly (TDD §11.3), so a repeated cancel is
    an ordinary event rather than an error -- and it must not decrement the
    day's capacity a second time."""
    fx = await make_org(db, "Acme")
    booking = await book_for(db, fx, fx["user"], TODAY + timedelta(days=1))
    booking_id = booking.id

    async with client as c:
        first = await c.delete(f"/bookings/{booking_id}", headers=auth(fx))
        second = await c.delete(f"/bookings/{booking_id}", headers=auth(fx))

    assert (first.status_code, second.status_code) == (204, 204)
