"""FR-5.4 -- the team week grid.

Two things carry weight here beyond "does it render":

  1. The grid is per-person presence, so it inherits every rule in
     test_presence_privacy.py. A teammate who has hidden themselves must have no
     row, and must not be counted.
  2. It is forward-only. A grid that scrolls backwards stops being a
     coordination tool and becomes the per-person attendance record that FR-9.5
     and TDD §13.3 rule out as a product position.
"""

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import mint_access_token
from app.db import get_session
from app.main import app
from app.models import GroupMember, UserGroup
from app.timezone import local_today
from tests.conftest import add_person, book_for, make_org

TODAY = local_today("Europe/Berlin")
MONDAY = TODAY - timedelta(days=TODAY.weekday())


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


async def team_named(db, fx, name: str) -> UserGroup:
    return (
        await db.execute(
            select(UserGroup).where(
                UserGroup.organization_id == fx["org"].id, UserGroup.name == name
            )
        )
    ).scalar_one()


async def join(db, fx, user, team) -> None:
    db.add(GroupMember(organization_id=fx["org"].id, group_id=team.id, user_id=user.id))
    await db.commit()


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


async def test_grid_covers_seven_days_from_monday(db, client):
    fx = await make_org(db, "Acme", desks=5)
    async with client as c:
        r = await c.get(f"/teams/{fx['team'].id}/week", headers=auth_as(fx["user"]))

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["days"]) == 7
    assert body["days"][0] == MONDAY.isoformat()
    assert body["anchor_days"] == [2, 4]


async def test_your_own_row_comes_first(db, client):
    fx = await make_org(db, "Acme", desks=5)
    team = fx["team"]
    for name in ("Aaron Early", "Zoe Last"):
        person = await add_person(db, fx, name)
        await join(db, fx, person, team)

    async with client as c:
        body = (await c.get(f"/teams/{team.id}/week", headers=auth_as(fx["user"]))).json()

    assert body["rows"][0]["is_you"] is True
    assert [r["display_name"] for r in body["rows"][1:]] == ["Aaron Early", "Zoe Last"]


async def test_bookings_and_declarations_both_fill_cells(db, client):
    fx = await make_org(db, "Acme", desks=5)
    team = fx["team"]
    colleague = await add_person(db, fx, "Some Colleague")
    await join(db, fx, colleague, team)
    await book_for(db, fx, colleague, MONDAY, 0)

    tuesday = MONDAY + timedelta(days=1)
    async with client as c:
        await c.put(
            f"/me/declarations/{tuesday.isoformat()}",
            json={"kind": "remote"},
            headers=auth_as(colleague),
        )
        body = (await c.get(f"/teams/{team.id}/week", headers=auth_as(fx["user"]))).json()

    row = next(r for r in body["rows"] if r["display_name"] == "Some Colleague")
    assert row["cells"][0]["kind"] == "office"
    assert row["cells"][0]["resource_name"] == fx["desks"][0].name
    assert row["cells"][1]["kind"] == "remote"
    assert row["office_days"] == 1


async def test_in_per_day_counts_the_column(db, client):
    fx = await make_org(db, "Acme", desks=5)
    team = fx["team"]
    for i, name in enumerate(("One Person", "Two Person")):
        person = await add_person(db, fx, name)
        await join(db, fx, person, team)
        await book_for(db, fx, person, MONDAY, i)

    async with client as c:
        body = (await c.get(f"/teams/{team.id}/week", headers=auth_as(fx["user"]))).json()

    assert body["in_per_day"][0] == 2
    assert body["in_per_day"][1] == 0


# ---------------------------------------------------------------------------
# privacy -- the grid inherits every rule from presence.py
# ---------------------------------------------------------------------------


async def test_a_hidden_teammate_has_no_row(db, client):
    fx = await make_org(db, "Acme", desks=5)
    team = fx["team"]
    hidden = await add_person(db, fx, "Hidden Person", visibility="nobody")
    await join(db, fx, hidden, team)
    await book_for(db, fx, hidden, MONDAY, 0)

    async with client as c:
        body = (await c.get(f"/teams/{team.id}/week", headers=auth_as(fx["user"]))).json()

    assert all(r["display_name"] != "Hidden Person" for r in body["rows"])


async def test_a_hidden_teammate_is_not_counted_either(db, client):
    """Counting them would let you infer that someone is hidden, which is the
    disclosure the setting exists to prevent."""
    fx = await make_org(db, "Acme", desks=5)
    team = fx["team"]
    hidden = await add_person(db, fx, "Hidden Person", visibility="nobody")
    await join(db, fx, hidden, team)
    await book_for(db, fx, hidden, MONDAY, 0)

    async with client as c:
        body = (await c.get(f"/teams/{team.id}/week", headers=auth_as(fx["user"]))).json()
        teams = (await c.get("/teams", headers=auth_as(fx["user"]))).json()

    assert body["team"]["member_count"] == 1, "only the viewer should be counted"
    assert body["in_per_day"][0] == 0, "a hidden person's booking must not show in totals"
    assert next(t for t in teams if t["id"] == str(team.id))["member_count"] == 1


async def test_a_team_only_teammate_is_visible_in_the_grid(db, client):
    """`team` means visible to people sharing a group -- which, in a team grid,
    is everyone looking at it."""
    fx = await make_org(db, "Acme", desks=5)
    team = fx["team"]
    guarded = await add_person(db, fx, "Team Only", visibility="team")
    await join(db, fx, guarded, team)
    await book_for(db, fx, guarded, MONDAY, 0)

    async with client as c:
        body = (await c.get(f"/teams/{team.id}/week", headers=auth_as(fx["user"]))).json()

    assert any(r["display_name"] == "Team Only" for r in body["rows"])


async def test_a_team_you_are_not_in_is_404(db, client):
    fx = await make_org(db, "Acme", desks=5)
    outsider = await add_person(db, fx, "An Outsider")

    async with client as c:
        r = await c.get(f"/teams/{fx['team'].id}/week", headers=auth_as(outsider))
    assert r.status_code == 404


async def test_teams_lists_only_your_own(db, client):
    fx = await make_org(db, "Acme", desks=5)
    await add_person(db, fx, "Other Person", groups=("Design",))

    async with client as c:
        teams = (await c.get("/teams", headers=auth_as(fx["user"]))).json()

    assert [t["name"] for t in teams] == ["Core"]


# ---------------------------------------------------------------------------
# forward-only (FR-9.5 / TDD §13.3)
# ---------------------------------------------------------------------------


async def test_the_current_week_is_allowed_even_though_it_contains_past_days(db, client):
    fx = await make_org(db, "Acme", desks=5)
    async with client as c:
        r = await c.get(
            f"/teams/{fx['team'].id}/week",
            params={"start": MONDAY.isoformat()},
            headers=auth_as(fx["user"]),
        )
    assert r.status_code == 200


async def test_a_finished_week_is_refused(db, client):
    """This is a product position, not an oversight: a backwards-scrolling grid
    is a per-person attendance report."""
    fx = await make_org(db, "Acme", desks=5)
    async with client as c:
        r = await c.get(
            f"/teams/{fx['team'].id}/week",
            params={"start": (MONDAY - timedelta(days=7)).isoformat()},
            headers=auth_as(fx["user"]),
        )

    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "PAST_WEEK"
    assert body["earliest"] == MONDAY.isoformat()


async def test_future_weeks_are_allowed(db, client):
    fx = await make_org(db, "Acme", desks=5)
    async with client as c:
        r = await c.get(
            f"/teams/{fx['team'].id}/week",
            params={"start": (MONDAY + timedelta(days=21)).isoformat()},
            headers=auth_as(fx["user"]),
        )
    assert r.status_code == 200
    assert r.json()["days"][0] == (MONDAY + timedelta(days=21)).isoformat()


async def test_a_mid_week_start_snaps_to_its_monday(db, client):
    fx = await make_org(db, "Acme", desks=5)
    wednesday = MONDAY + timedelta(days=9)  # next week's Wednesday
    async with client as c:
        body = (
            await c.get(
                f"/teams/{fx['team'].id}/week",
                params={"start": wednesday.isoformat()},
                headers=auth_as(fx["user"]),
            )
        ).json()

    assert body["days"][0] == (MONDAY + timedelta(days=7)).isoformat()
