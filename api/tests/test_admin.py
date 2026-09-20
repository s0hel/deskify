"""The admin console's API. FR-8.1, 8.4, 8.6, 8.8, and FR-1.8 over all of it.

Two harnesses and a set of cases. The harnesses are the load-bearing part:

  - `test_every_admin_endpoint_refuses_an_employee` walks the live OpenAPI
    schema the way tests/test_cross_tenant.py does, so an admin endpoint added
    without a permission check fails on the day it is added rather than on the
    day someone notices.
  - the body-id cases cover what the path-driven cross-tenant harness cannot
    reach: `POST /floors`, `POST /zones` and `POST /bookings/admin` all take
    the id they act on in the request body.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range

from app.auth import mint_access_token
from app.db import get_session
from app.main import app
from app.models import AuditLog, Booking, Resource, Site
from app.timezone import local_today
from tests.conftest import add_person, book_for, grant_role, make_org

#: The fixture org is in Europe/Berlin, and a booking's day is the
#: calendar date in its SITE's timezone, never the server's (TDD §3.4).
TODAY = local_today("Europe/Berlin")

#: Every path the admin router owns, as the router spells them. Kept as a
#: prefix list rather than a tag lookup so that a path moving out of the admin
#: router does not silently drop out of the employee-refusal harness.
ADMIN_PREFIXES = ("/admin/", "/audit", "/sites", "/floors", "/zones", "/resources")

#: Admin paths that an ordinary employee is ALLOWED to reach, because the same
#: path serves the employee app. Each needs a reason.
EMPLOYEE_MAY = {
    ("GET", "/sites"),                  # the office list, FR-2.1
    ("GET", "/sites/{site_id}"),
    ("GET", "/sites/{site_id}/days"),
    ("GET", "/sites/{site_id}/floors"),
    ("GET", "/floors/{floor_id}"),
    ("GET", "/floors/{floor_id}/state"),
}


def admin_operations() -> list[tuple[str, str]]:
    schema = app.openapi()
    found = []
    for path, ops in schema["paths"].items():
        if not path.startswith(ADMIN_PREFIXES):
            continue
        for method in ops:
            pair = (method.upper(), path)
            if pair not in EMPLOYEE_MAY:
                found.append(pair)
    return sorted(found)


def test_the_employee_harness_actually_covers_something():
    assert len(admin_operations()) >= 15, admin_operations()


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
    """Read the ids BEFORE the request, not after.

    A refused admin call raises a DeskifyError, the session override rolls
    back, and the rollback expires every ORM object the fixture handed out.
    Touching `fx["site"].id` after that point triggers a lazy reload from a
    sync context and fails with MissingGreenlet rather than with whatever the
    test was actually asserting. Every test here snapshots the ids it needs
    into plain values first.
    """
    user = user or fx["user"]
    return {"Authorization": f"Bearer {mint_access_token(user.id, fx['org'].id)}"}


@pytest.mark.parametrize("method,path", admin_operations())
async def test_every_admin_endpoint_refuses_an_employee(method, path, db, client):
    """FR-1.8. The caller holds no grant, and the objects are genuinely theirs
    -- same org, real ids -- so the only thing that can refuse is the
    permission check.

    403, not 404: this is a fact about the CALLER, not about the object, and
    it discloses nothing they do not already know. The 404 rule belongs to the
    tenancy layer, where a 403 would confirm another tenant's object exists
    (app/authz.py explains the split).
    """
    fx = await make_org(db, "Acme")
    url = (
        path.replace("{site_id}", str(fx["site"].id))
        .replace("{floor_id}", str(fx["floor"].id))
        .replace("{zone_id}", str(fx["zone"].id))
        .replace("{resource_id}", str(fx["desk"].id))
        .replace("{group_id}", str(fx["team"].id))
        .replace("{user_id}", str(fx["user"].id))
    )
    assert "{" not in url, f"{path} has an unsubstituted parameter"

    required = {
        "/resources/{resource_id}/out-of-service": {"reason": "Monitor replaced"},
        "/admin/users/{user_id}/roles": {"roles": []},
        "/admin/groups/{group_id}/members": {"user_ids": []},
    }
    body = required.get(path, {} if method in ("POST", "PUT", "PATCH") else None)

    async with client as c:
        resp = await c.request(
            method, url, headers=auth(fx), json=body, params={"on": str(TODAY)}
        )

    assert resp.status_code == 403, (
        f"{method} {path} let an employee through: {resp.status_code} {resp.text[:200]}"
    )


# --------------------------------------------------------------------------
# Scope (FR-1.8)
# --------------------------------------------------------------------------


async def add_site(db, fx, name: str, tz: str = "America/New_York") -> Site:
    site = Site(
        organization_id=fx["org"].id, name=name, timezone=tz,
        opening_hours={"open": "08:00", "close": "18:00"},
    )
    db.add(site)
    await db.flush()
    await db.commit()
    return site


async def test_a_site_admin_is_confined_to_their_own_site(db, client):
    """The whole reason grants carry a scope. Same tenant, same admin, two
    offices -- and one of them is not theirs."""
    fx = await make_org(db, "Acme")
    other = await add_site(db, fx, "Acme Berlin", tz="Europe/Berlin")
    await grant_role(db, fx, fx["user"], "site_admin", scope_id=fx["site"].id)

    async with client as c:
        mine = await c.patch(
            f"/sites/{fx['site'].id}", headers=auth(fx), json={"name": "Acme Tampa"}
        )
        theirs = await c.patch(
            f"/sites/{other.id}", headers=auth(fx), json={"name": "Taken over"}
        )

    assert mine.status_code == 200, mine.text
    assert mine.json()["name"] == "Acme Tampa"
    assert theirs.status_code == 403, theirs.text
    assert theirs.json()["code"] == "FORBIDDEN"


async def test_a_site_admin_cannot_create_a_site_or_reach_people(db, client):
    """Site admins run an office. Minting offices, people and roles is
    org-wide, or the scope on their own grant means nothing."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "site_admin", scope_id=fx["site"].id)
    head = auth(fx)

    async with client as c:
        created = await c.post(
            "/sites", headers=head,
            json={"name": "Acme Berlin", "timezone": "Europe/Berlin"},
        )
        people = await c.get("/admin/users", headers=head)
        audit = await c.get("/audit", headers=head)

    assert created.status_code == 403
    assert people.status_code == 403
    assert audit.status_code == 403


async def test_a_site_admin_sees_only_their_own_sites_floors(db, client):
    fx = await make_org(db, "Acme")
    other = await add_site(db, fx, "Acme Berlin", tz="Europe/Berlin")
    await grant_role(db, fx, fx["user"], "site_admin", scope_id=other.id)

    async with client as c:
        resp = await c.get("/admin/floors", headers=auth(fx))

    assert resp.status_code == 200
    # Acme HQ's 4F belongs to the site they do NOT administer.
    assert resp.json() == []


async def test_me_reports_whether_to_offer_the_console(db, client):
    """The client needs to know whether the entry point exists. It is not the
    permission -- every endpoint re-checks -- but a console nobody can open
    should not have a door."""
    fx = await make_org(db, "Acme")

    async with client as c:
        before = await c.get("/me", headers=auth(fx))
        await grant_role(db, fx, fx["user"], "site_admin", scope_id=fx["site"].id)
        after = await c.get("/me", headers=auth(fx))

    assert before.json()["is_admin"] is False
    assert before.json()["administered_site_ids"] == []
    assert after.json()["is_admin"] is True
    assert after.json()["administered_site_ids"] == [str(fx["site"].id)]


async def test_an_org_admin_reports_every_site_as_null_not_a_list(db, client):
    fx = await make_org(db, "Acme")
    await add_site(db, fx, "Acme Berlin", tz="Europe/Berlin")
    await grant_role(db, fx, fx["user"], "org_admin")

    async with client as c:
        me = await c.get("/me", headers=auth(fx))

    assert me.json()["is_admin"] is True
    assert me.json()["administered_site_ids"] is None


# --------------------------------------------------------------------------
# Sites, floors, zones (FR-8.1)
# --------------------------------------------------------------------------


async def test_creating_a_site_and_a_floor_end_to_end(db, client):
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")

    async with client as c:
        site = await c.post(
            "/sites", headers=auth(fx),
            json={
                "name": "Acme Lisbon", "timezone": "Europe/Lisbon",
                "opening_hours": {"open": "09:00", "close": "19:00"},
                "capacity_cap": 40,
            },
        )
        assert site.status_code == 201, site.text
        site_id = site.json()["id"]

        floor = await c.post(
            "/floors", headers=auth(fx),
            json={"site_id": site_id, "name": "2F", "ordinal": 2},
        )
        assert floor.status_code == 201, floor.text

        listed = await c.get("/admin/floors", headers=auth(fx), params={"site_id": site_id})

    assert [f["name"] for f in listed.json()] == ["2F"]
    # An empty floor is visible as empty -- an unfinished import should look
    # unfinished rather than look like a floor.
    assert listed.json()[0]["desk_count"] == 0


async def test_a_sites_timezone_cannot_change_once_bookings_exist(db, client):
    """TDD §3.5. The timezone IS the day-boundary rule for every booking
    already written against the site; moving it re-dates history, and last
    month's utilization stops reconciling."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    await book_for(db, fx, fx["user"], TODAY + timedelta(days=1))
    head, site_id = auth(fx), fx["site"].id

    async with client as c:
        moved = await c.patch(
            f"/sites/{site_id}", headers=head, json={"timezone": "America/New_York"}
        )
        renamed = await c.patch(
            f"/sites/{site_id}", headers=head, json={"name": "Acme Berlin HQ"}
        )

    assert moved.status_code == 409, moved.text
    assert moved.json()["code"] == "ADMIN_CONFLICT"
    assert moved.json()["bookings"] == 1
    # Everything else about the site still changes. The refusal is narrow.
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Acme Berlin HQ"
    assert renamed.json()["timezone"] == "Europe/Berlin"


async def test_a_site_that_would_break_the_day_boundary_is_refused_at_the_door(db, client):
    """A bad timezone does not fail here -- it fails inside /sites/{id}/days
    for every employee at that office, a long way from the admin who typed
    it."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    head = auth(fx)

    async with client as c:
        bad_tz = await c.post(
            "/sites", headers=head, json={"name": "Nowhere", "timezone": "Mars/Olympus"}
        )
        backwards = await c.post(
            "/sites", headers=head,
            json={
                "name": "Upside Down", "timezone": "Europe/Berlin",
                "opening_hours": {"open": "18:00", "close": "08:00"},
            },
        )

    assert bad_tz.status_code == 422
    assert bad_tz.json()["code"] == "INVALID_CHANGE"
    assert backwards.status_code == 422


async def test_a_zone_with_desks_in_it_is_not_deleted(db, client):
    """The desks would keep a dangling zone_id and quietly lose whatever
    restriction the zone carried (FR-6.4)."""
    fx = await make_org(db, "Acme", desks=3)
    await grant_role(db, fx, fx["user"], "org_admin")
    zone_id = fx["zone"].id

    async with client as c:
        blocked = await c.delete(f"/zones/{zone_id}", headers=auth(fx))

    assert blocked.status_code == 409
    assert blocked.json()["resources"] == 3
    assert (await db.execute(select(Resource.zone_id).limit(1))).scalar() == zone_id


# --------------------------------------------------------------------------
# People (FR-8.4)
# --------------------------------------------------------------------------


async def test_deactivating_a_user_releases_their_future_desks(db, client):
    """TDD §6.6. A leaver whose desks stay booked is the most visible way for
    this product to be wrong: a row of permanently occupied desks nobody ever
    sits at."""
    fx = await make_org(db, "Acme", desks=3)
    await grant_role(db, fx, fx["user"], "org_admin")
    leaver = await add_person(db, fx, "Ren")
    yesterday = TODAY - timedelta(days=1)
    await book_for(db, fx, leaver, TODAY + timedelta(days=1), desk_index=0)
    await book_for(db, fx, leaver, TODAY + timedelta(days=2), desk_index=1)
    past = await book_for(db, fx, leaver, yesterday, desk_index=2)

    async with client as c:
        resp = await c.post(f"/admin/users/{leaver.id}/deactivate", headers=auth(fx))

    assert resp.status_code == 200, resp.text
    assert resp.json()["released"] == 2
    assert resp.json()["user"]["status"] == "deactivated"
    assert resp.json()["user"]["future_bookings"] == 0

    # Past bookings are retained: deleting them would falsify utilization
    # already reported to a customer (TDD §6.6).
    await db.refresh(past)
    assert past.status == "confirmed"


async def test_deactivation_gives_the_days_capacity_back(db, client):
    """FR-6.3's counter is the thing that actually stops the next booking, so
    releasing a desk without decrementing it releases nothing."""
    fx = await make_org(db, "Acme", capacity_cap=1, desks=2)
    await grant_role(db, fx, fx["user"], "org_admin")
    leaver = await add_person(db, fx, "Ren")
    on = TODAY + timedelta(days=1)

    await db.execute(
        text(
            "INSERT INTO site_day_capacity "
            "(organization_id, site_id, local_date, booked_count, cap) "
            "VALUES (:org, :site, :d, 1, 1)"
        ),
        {"org": fx["org"].id, "site": fx["site"].id, "d": on},
    )
    await book_for(db, fx, leaver, on)
    await db.commit()

    async with client as c:
        await c.post(f"/admin/users/{leaver.id}/deactivate", headers=auth(fx))

    count = (
        await db.execute(
            text(
                "SELECT booked_count FROM site_day_capacity "
                "WHERE site_id = :site AND local_date = :d"
            ),
            {"site": fx["site"].id, "d": on},
        )
    ).scalar()
    assert count == 0


async def test_an_admin_cannot_deactivate_themselves(db, client):
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")

    async with client as c:
        resp = await c.post(f"/admin/users/{fx['user'].id}/deactivate", headers=auth(fx))

    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_CHANGE"


async def test_the_last_org_admin_cannot_be_demoted(db, client):
    """An org with no org_admin is not a support ticket, it is a data-repair
    job. Demoting yourself while somebody else holds the role is fine."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    colleague = await add_person(db, fx, "Ren")
    head, me, them = auth(fx), fx["user"].id, colleague.id

    async with client as c:
        alone = await c.put(f"/admin/users/{me}/roles", headers=head, json={"roles": []})
        assert alone.status_code == 409, alone.text
        assert alone.json()["code"] == "ADMIN_CONFLICT"

        await c.put(
            f"/admin/users/{them}/roles", headers=head,
            json={"roles": [{"role": "org_admin"}]},
        )
        now_safe = await c.put(
            f"/admin/users/{me}/roles", headers=head, json={"roles": []}
        )

    assert now_safe.status_code == 200, now_safe.text
    assert now_safe.json()["roles"] == []


async def test_a_site_admin_grant_must_name_its_site(db, client):
    """A site_admin row with no scope would read as admin of every site. The
    CHECK in revision 0004 refuses to store one; this refuses to build one,
    with a message that says what to do instead."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    colleague = await add_person(db, fx, "Ren")
    head, them, site_id = auth(fx), colleague.id, fx["site"].id

    async with client as c:
        unscoped = await c.put(
            f"/admin/users/{them}/roles", headers=head,
            json={"roles": [{"role": "site_admin"}]},
        )
        scoped = await c.put(
            f"/admin/users/{them}/roles", headers=head,
            json={"roles": [{"role": "site_admin", "scope_id": str(site_id)}]},
        )

    assert unscoped.status_code == 422
    assert "names the site" in unscoped.json()["detail"]
    assert scoped.status_code == 200
    assert scoped.json()["roles"] == [
        {
            "role": "site_admin", "scope_type": "site",
            "scope_id": str(site_id), "scope_name": "Acme HQ",
        }
    ]


async def test_the_directory_does_not_disclose_where_a_hidden_colleague_sits(db, client):
    """The one deliberate exception to app/presence.py, and its limit.

    An employer knows who works there, so the directory lists everyone
    regardless of visibility. What it must not become is a way around FR-5.6:
    there is no booking detail in the payload, only a count, so a colleague
    who hid their presence is still not placed at a desk on a day.
    """
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    hidden = await add_person(db, fx, "Jo", visibility="nobody")
    await book_for(db, fx, hidden, TODAY + timedelta(days=1))

    async with client as c:
        resp = await c.get("/admin/users", headers=auth(fx))

    row = next(u for u in resp.json() if u["id"] == str(hidden.id))
    assert row["display_name"] == "Jo"
    assert row["future_bookings"] == 1
    assert "bookings" not in row and "resource_name" not in row
    assert set(row) == {
        "id", "email", "display_name", "status", "home_site_id",
        "presence_visibility", "teams", "roles", "future_bookings",
    }


# --------------------------------------------------------------------------
# Overrides (FR-8.6)
# --------------------------------------------------------------------------


async def test_taking_a_desk_out_of_service_leaves_todays_sitter_alone(db, client):
    """A desk taken out of service from next Monday should not silently evict
    whoever is at it today. The admin who does mean that asks for it."""
    fx = await make_org(db, "Acme", desks=2)
    await grant_role(db, fx, fx["user"], "org_admin")
    colleague = await add_person(db, fx, "Ren")
    booking = await book_for(db, fx, colleague, TODAY + timedelta(days=1))

    async with client as c:
        quiet = await c.post(
            f"/resources/{fx['desk'].id}/out-of-service", headers=auth(fx),
            json={"reason": "Monitor arm snapped"},
        )
        assert quiet.json()["released"] == 0
        await db.refresh(booking)
        assert booking.status == "confirmed"

        loud = await c.post(
            f"/resources/{fx['desk'].id}/out-of-service", headers=auth(fx),
            json={"reason": "Monitor arm snapped", "release_bookings": True},
        )

    assert loud.json()["released"] == 1
    await db.refresh(booking)
    assert booking.status == "cancelled"
    assert "Monitor arm snapped" in booking.cancellation_reason


async def test_booking_for_someone_records_both_identities(db, client):
    """TDD §6.6. `user_id` is who gets the desk, `created_by` is who did it.
    An admin-created booking that looked self-made would make the audit log a
    fiction."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    colleague = await add_person(db, fx, "Ren")

    async with client as c:
        resp = await c.post(
            "/bookings/admin", headers=auth(fx),
            json={
                "user_id": str(colleague.id), "resource_id": str(fx["desk"].id),
                "on": str(TODAY + timedelta(days=1)),
            },
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["user_id"] == str(colleague.id)
    assert resp.json()["created_by"] == str(fx["user"].id)

    row = await c_first(db, Booking)
    assert row.user_id == colleague.id and row.created_by == fx["user"].id


async def test_an_override_still_cannot_double_book_a_desk(db, client):
    """FR-8.6 relaxes policy, never the exclusion constraint (TDD §4.1).
    Overriding a rule and overriding physics are different requests."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    ren = await add_person(db, fx, "Ren")
    dana = await add_person(db, fx, "Dana")
    on = TODAY + timedelta(days=1)
    await book_for(db, fx, ren, on)

    async with client as c:
        resp = await c.post(
            "/bookings/admin", headers=auth(fx),
            json={
                "user_id": str(dana.id), "resource_id": str(fx["desk"].id),
                "on": str(on), "override_policy": True,
            },
        )

    assert resp.status_code == 409
    assert resp.json()["code"] == "RESOURCE_TAKEN"


async def test_a_deactivated_user_cannot_be_booked_for(db, client):
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    leaver = await add_person(db, fx, "Ren")

    async with client as c:
        await c.post(f"/admin/users/{leaver.id}/deactivate", headers=auth(fx))
        resp = await c.post(
            "/bookings/admin", headers=auth(fx),
            json={
                "user_id": str(leaver.id), "resource_id": str(fx["desk"].id),
                "on": str(TODAY + timedelta(days=1)),
            },
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_CHANGE"


# --------------------------------------------------------------------------
# The body-id cross-tenant cases the path-driven harness cannot reach
# --------------------------------------------------------------------------


async def test_an_admin_cannot_reach_another_tenant_through_a_body(db, client):
    """tests/test_cross_tenant.py substitutes victim ids into PATHS. These
    three endpoints take the id they act on in the BODY, so they are asserted
    here -- and they are exactly the endpoints where a miss would create a
    floor, a zone or a booking inside somebody else's organization.

    404, not 403: the caller IS an administrator, so a 403 would be the wrong
    answer as well as a disclosure.
    """
    acme = await make_org(db, "Acme")
    globex = await make_org(db, "Globex")
    await grant_role(db, acme, acme["user"], "org_admin")
    head, team_id = auth(acme), acme["team"].id
    theirs = {
        "site": globex["site"].id, "floor": globex["floor"].id,
        "user": globex["user"].id, "desk": globex["desk"].id,
    }

    async with client as c:
        floor = await c.post(
            "/floors", headers=head,
            json={"site_id": str(theirs["site"]), "name": "Ours now"},
        )
        zone = await c.post(
            "/zones", headers=head,
            json={"floor_id": str(theirs["floor"]), "name": "Ours now"},
        )
        booking = await c.post(
            "/bookings/admin", headers=head,
            json={
                "user_id": str(theirs["user"]), "resource_id": str(theirs["desk"]),
                "on": str(TODAY + timedelta(days=1)),
            },
        )
        members = await c.put(
            f"/admin/groups/{team_id}/members", headers=head,
            json={"user_ids": [str(theirs["user"])]},
        )

    assert floor.status_code == 404, floor.text
    assert zone.status_code == 404, zone.text
    assert booking.status_code == 404, booking.text
    # A group of ours, but a member who is not: still 404, and nothing written.
    assert members.status_code == 404, members.text


# --------------------------------------------------------------------------
# Audit (FR-8.8)
# --------------------------------------------------------------------------


async def test_every_change_leaves_an_audit_row_carrying_the_before_value(db, client):
    """An entry saying "site updated" is almost useless six months later. One
    saying the cap went from 120 to 60 is the answer to the question someone
    will actually be asking."""
    fx = await make_org(db, "Acme", capacity_cap=120)
    await grant_role(db, fx, fx["user"], "org_admin")

    async with client as c:
        await c.patch(
            f"/sites/{fx['site'].id}", headers=auth(fx), json={"capacity_cap": 60}
        )
        audit = await c.get("/audit", headers=auth(fx))

    rows = audit.json()
    assert [r["action"] for r in rows] == ["site.update"]
    assert rows[0]["actor_name"] == "Priya"
    assert rows[0]["target_id"] == str(fx["site"].id)
    assert rows[0]["detail"]["before"] == {"capacity_cap": 120}
    assert rows[0]["detail"]["after"] == {"capacity_cap": 60}


async def test_a_failed_change_leaves_no_audit_row(db, client):
    """The record and the change share a transaction. An audit log that can
    disagree with the data is worse than none, because it is believed."""
    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    await book_for(db, fx, fx["user"], TODAY + timedelta(days=1))

    async with client as c:
        refused = await c.patch(
            f"/sites/{fx['site'].id}", headers=auth(fx),
            json={"name": "Renamed too", "timezone": "America/New_York"},
        )

    assert refused.status_code == 409
    assert (await db.execute(select(AuditLog))).scalars().all() == []
    # And the name did not change either -- the whole request was refused.
    await db.refresh(fx["site"])
    assert fx["site"].name == "Acme HQ"


async def c_first(db, model):
    return (await db.execute(select(model))).scalars().first()



#: Two offices 26 hours apart. Their local dates can never both equal the
#: server's UTC date -- whatever the clock says, at least one of them is on a
#: different day -- which is what makes the test below bite at every hour
#: rather than for the half of the day when UTC happens to agree.
FAR_EAST = "Pacific/Kiritimati"   # UTC+14
FAR_WEST = "Etc/GMT+12"           # UTC-12


async def add_site_with_desk(db, fx, name: str, tz: str):
    site = Site(
        organization_id=fx["org"].id, name=name, timezone=tz,
        opening_hours={"open": "08:00", "close": "18:00"},
    )
    db.add(site)
    await db.flush()
    desk = Resource(
        organization_id=fx["org"].id, site_id=site.id, kind="desk", name=f"{name}-01"
    )
    db.add(desk)
    await db.flush()
    await db.commit()
    return site, desk


async def book_at(db, fx, site, desk, user, on):
    booking = Booking(
        organization_id=fx["org"].id, site_id=site.id, resource_id=desk.id,
        user_id=user.id,
        during=Range(
            datetime.combine(on, time(9), tzinfo=ZoneInfo(site.timezone)),
            datetime.combine(on, time(17), tzinfo=ZoneInfo(site.timezone)),
            bounds="[)",
        ),
        local_date=on, status="confirmed", created_by=user.id,
    )
    db.add(booking)
    await db.flush()
    await db.commit()
    return booking


async def test_upcoming_is_measured_in_each_offices_own_timezone(db, client):
    """TDD §3.4, applied to the release path.

    A booking's day is its calendar date in the timezone of the office it is
    at. `date.today()` is the SERVER's date, and an org spanning UTC+14 and
    UTC-12 has no single today -- so a server comparing against a UTC date is
    wrong about one of these two offices at every moment. Half the day it
    believes a still-future booking at the western office has happened and
    fails to release it; the other half it believes a finished booking at the
    eastern office is upcoming and releases one that is already over.

    Four bookings, two at each extreme: today and yesterday in that office's
    own reckoning. Exactly the two "today" ones are upcoming, always.
    """
    from app.timezone import local_today

    fx = await make_org(db, "Acme")
    await grant_role(db, fx, fx["user"], "org_admin")
    leaver = await add_person(db, fx, "Ren")

    made = {}
    for label, tz in (("East", FAR_EAST), ("West", FAR_WEST)):
        site, desk = await add_site_with_desk(db, fx, label, tz)
        there = local_today(tz)
        made[f"{label} today"] = await book_at(db, fx, site, desk, leaver, there)
        made[f"{label} yesterday"] = await book_at(
            db, fx, site, desk, leaver, there - timedelta(days=1)
        )

    leaver_id = leaver.id
    head = auth(fx)

    async with client as c:
        listed = await c.get("/admin/users", headers=head)
        released = await c.post(f"/admin/users/{leaver_id}/deactivate", headers=head)

    row = next(u for u in listed.json() if u["id"] == str(leaver_id))
    assert row["future_bookings"] == 2, (
        "exactly the two bookings on their own office's today are upcoming"
    )
    assert released.json()["released"] == 2

    for label, booking in made.items():
        await db.refresh(booking)
        expected = "cancelled" if label.endswith("today") else "confirmed"
        assert booking.status == expected, f"{label} should be {expected}"
