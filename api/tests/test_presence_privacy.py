"""FR-5.6 presence visibility. The privacy tests.

Presence data is data about where a named employee physically is. PRD §9.4 and
risk R3 both turn on this being right, and a leak here is not a bug report --
it is a works-council escalation.

Every case asserts ABSENCE from the result set, not merely a missing field: a
hidden colleague filtered out by the serializer still leaks through counts and
logs (TDD §5.2).
"""

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import mint_access_token
from app.db import get_session
from app.main import app
from app.models import Organization
from app.timezone import local_today
from tests.conftest import add_person, book_for, make_org

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


def auth_as(user):
    return {"Authorization": f"Bearer {mint_access_token(user.id, user.organization_id)}"}


async def names_in_office(c, viewer, on=TODAY) -> list[str]:
    r = await c.get("/people", params={"on": on.isoformat()}, headers=auth_as(viewer))
    assert r.status_code == 200, r.text
    return [p["display_name"] for p in r.json()["in_office"]]


# ---------------------------------------------------------------------------
# everyone
# ---------------------------------------------------------------------------


async def test_everyone_is_visible_to_a_stranger(db, client):
    fx = await make_org(db, "Acme", desks=5)
    open_book = await add_person(db, fx, "Open Book", visibility="everyone")
    stranger = await add_person(db, fx, "Some Stranger")
    await book_for(db, fx, open_book, TODAY, 0)

    async with client as c:
        assert "Open Book" in await names_in_office(c, stranger)


# ---------------------------------------------------------------------------
# team
# ---------------------------------------------------------------------------


async def test_team_only_is_visible_to_a_teammate(db, client):
    fx = await make_org(db, "Acme", desks=5)
    guarded = await add_person(db, fx, "Team Only", visibility="team", groups=("Engineering",))
    teammate = await add_person(db, fx, "A Teammate", groups=("Engineering",))
    await book_for(db, fx, guarded, TODAY, 0)

    async with client as c:
        assert "Team Only" in await names_in_office(c, teammate)


async def test_team_only_is_invisible_to_someone_outside_the_team(db, client):
    fx = await make_org(db, "Acme", desks=5)
    guarded = await add_person(db, fx, "Team Only", visibility="team", groups=("Engineering",))
    outsider = await add_person(db, fx, "An Outsider", groups=("Sales",))
    await book_for(db, fx, guarded, TODAY, 0)

    async with client as c:
        assert "Team Only" not in await names_in_office(c, outsider)


async def test_team_only_is_invisible_to_someone_in_no_team_at_all(db, client):
    fx = await make_org(db, "Acme", desks=5)
    guarded = await add_person(db, fx, "Team Only", visibility="team", groups=("Engineering",))
    loner = await add_person(db, fx, "No Groups")
    await book_for(db, fx, guarded, TODAY, 0)

    async with client as c:
        assert "Team Only" not in await names_in_office(c, loner)


async def test_sharing_any_one_group_is_enough(db, client):
    fx = await make_org(db, "Acme", desks=5)
    guarded = await add_person(
        db, fx, "Team Only", visibility="team", groups=("Engineering", "Fire Wardens")
    )
    warden = await add_person(db, fx, "Other Warden", groups=("Fire Wardens",))
    await book_for(db, fx, guarded, TODAY, 0)

    async with client as c:
        assert "Team Only" in await names_in_office(c, warden)


# ---------------------------------------------------------------------------
# nobody
# ---------------------------------------------------------------------------


async def test_nobody_is_invisible_even_to_a_teammate(db, client):
    fx = await make_org(db, "Acme", desks=5)
    hidden = await add_person(db, fx, "Hidden Person", visibility="nobody", groups=("Engineering",))
    teammate = await add_person(db, fx, "A Teammate", groups=("Engineering",))
    await book_for(db, fx, hidden, TODAY, 0)

    async with client as c:
        assert "Hidden Person" not in await names_in_office(c, teammate)


async def test_nobody_can_still_see_themselves(db, client):
    """The setting governs what OTHERS see. Hiding from colleagues must not hide
    your own desk from you."""
    fx = await make_org(db, "Acme", desks=5)
    hidden = await add_person(db, fx, "Hidden Person", visibility="nobody")
    await book_for(db, fx, hidden, TODAY, 0)

    async with client as c:
        assert "Hidden Person" in await names_in_office(c, hidden)


async def test_nobody_can_still_book(db, client):
    """"You can still book as normal" -- privacy must not degrade the product."""
    fx = await make_org(db, "Acme", desks=5)
    hidden = await add_person(db, fx, "Hidden Person", visibility="nobody")

    async with client as c:
        r = await c.post(
            "/bookings",
            json={"resource_id": str(fx["desks"][1].id), "on": TODAY.isoformat(), "slot": "day"},
            headers=auth_as(hidden),
        )
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# the org-level kill switch (PRD §5.3, Q6)
# ---------------------------------------------------------------------------


async def test_org_kill_switch_hides_everyone_from_everyone(db, client):
    fx = await make_org(db, "Acme", desks=5)
    a = await add_person(db, fx, "Open Book", visibility="everyone")
    b = await add_person(db, fx, "Also Open", visibility="everyone")
    await book_for(db, fx, a, TODAY, 0)
    await book_for(db, fx, b, TODAY, 1)

    org = await db.get(Organization, fx["org"].id)
    org.settings = {"presence_enabled": False}
    await db.commit()

    async with client as c:
        seen = await names_in_office(c, b)

    assert "Open Book" not in seen
    assert seen == ["Also Open"], "the switch must not hide you from yourself"


# ---------------------------------------------------------------------------
# the colleague detail endpoint
# ---------------------------------------------------------------------------


async def test_hidden_colleague_detail_is_404_not_403(db, client):
    """A 403 would confirm the person exists and has hidden themselves, which is
    itself a disclosure."""
    fx = await make_org(db, "Acme", desks=5)
    hidden = await add_person(db, fx, "Hidden Person", visibility="nobody")
    stranger = await add_person(db, fx, "Some Stranger")

    async with client as c:
        r = await c.get(f"/people/{hidden.id}", headers=auth_as(stranger))
    assert r.status_code == 404
    assert "Hidden" not in r.text


async def test_visible_colleague_detail_shows_their_schedule(db, client):
    fx = await make_org(db, "Acme", desks=5)
    open_book = await add_person(db, fx, "Open Book", groups=("Engineering",))
    viewer = await add_person(db, fx, "A Viewer", groups=("Engineering",))
    await book_for(db, fx, open_book, TODAY, 0)

    async with client as c:
        r = await c.get(f"/people/{open_book.id}", headers=auth_as(viewer))

    assert r.status_code == 200
    body = r.json()
    assert body["in_office_days"] == 1
    assert body["shared_teams"] == ["Engineering"]
    office = [d for d in body["schedule"] if d["kind"] == "office"]
    assert len(office) == 1
    assert office[0]["resource_name"] == fx["desks"][0].name


async def test_declarations_appear_in_a_colleagues_schedule(db, client):
    """FR-5.5 -- a declared remote day completes the picture rather than
    leaving a silent gap."""
    fx = await make_org(db, "Acme", desks=5)
    colleague = await add_person(db, fx, "Remote Worker", groups=("Engineering",))
    viewer = await add_person(db, fx, "A Viewer", groups=("Engineering",))
    tomorrow = TODAY + timedelta(days=1)

    async with client as c:
        assert (
            await c.put(
                f"/me/declarations/{tomorrow.isoformat()}",
                json={"kind": "remote"},
                headers=auth_as(colleague),
            )
        ).status_code == 200

        body = (await c.get(f"/people/{colleague.id}", headers=auth_as(viewer))).json()

    day = next(d for d in body["schedule"] if d["date"] == tomorrow.isoformat())
    assert day["kind"] == "remote"


async def test_changing_your_setting_takes_effect_immediately(db, client):
    fx = await make_org(db, "Acme", desks=5)
    person = await add_person(db, fx, "Changes Mind", visibility="everyone")
    stranger = await add_person(db, fx, "Some Stranger")
    await book_for(db, fx, person, TODAY, 0)

    async with client as c:
        assert "Changes Mind" in await names_in_office(c, stranger)

        r = await c.put(
            "/me/privacy", json={"presence_visibility": "nobody"}, headers=auth_as(person)
        )
        assert r.status_code == 200

        assert "Changes Mind" not in await names_in_office(c, stranger)


async def test_presence_never_crosses_a_tenant_boundary(db, client):
    """The privacy rule is per-org; it must not be the only thing standing
    between two customers."""
    acme = await make_org(db, "Acme", desks=5)
    globex = await make_org(db, "Globex", desks=5)
    theirs = await add_person(db, globex, "Globex Person", visibility="everyone")
    await book_for(db, globex, theirs, TODAY, 0)
    ours = await add_person(db, acme, "Acme Person")

    async with client as c:
        assert "Globex Person" not in await names_in_office(c, ours)
        r = await c.get(f"/people/{theirs.id}", headers=auth_as(ours))
    assert r.status_code == 404
