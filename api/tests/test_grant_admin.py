"""The founding-grant CLI. FR-1.8.

This exists because there is no endpoint that creates the first org admin, so
it is the only way a new tenant gets one -- which makes it the one piece of
operator tooling whose failure modes are a security question rather than an
inconvenience. It runs against production by design, so what it refuses
matters as much as what it writes.
"""

import pytest
from sqlalchemy import select

from app.grant_admin import parse, resolve_scope, run
from app.models import RoleGrant
from tests.conftest import add_person, make_org


def argv(*args) -> list[str]:
    return list(args)


async def grants(db, org_id) -> list[tuple[str, str]]:
    rows = (
        await db.execute(select(RoleGrant).where(RoleGrant.organization_id == org_id))
    ).scalars()
    return sorted((g.role, g.scope_type) for g in rows)


# --------------------------------------------------------------------------
# Argument handling -- no database
# --------------------------------------------------------------------------


def test_a_role_outside_the_model_is_refused_before_anything_connects():
    """`ROLES` is the source, so a role added to authz.py is grantable here
    the same day and a typo never reaches the CHECK constraint."""
    with pytest.raises(SystemExit) as exit_info:
        parse(argv("someone@example.com", "superuser"))
    assert exit_info.value.code == 2


def test_a_grant_covers_a_site_or_a_team_but_not_both():
    with pytest.raises(SystemExit):
        parse(argv("a@b.c", "site_admin", "--site", "Tampa", "--team", "Design"))


def test_the_default_is_a_dry_run():
    """A tool whose default is to mutate a production database is one you
    find out about afterwards."""
    assert parse(argv("a@b.c", "org_admin")).apply is False
    assert parse(argv("a@b.c", "org_admin", "--apply")).apply is True


# --------------------------------------------------------------------------
# Scope resolution -- the part that could escalate
# --------------------------------------------------------------------------


async def test_a_site_admin_grant_with_no_resolvable_site_is_an_error_not_a_null(db):
    """THE ONE THAT MATTERS. A NULL scope on a site_admin row reads as "admin
    of every office". Revision 0004's CHECK refuses to store one; this
    refuses to build one, so the operator gets a sentence instead of an
    IntegrityError -- and never a silent escalation if that CHECK were ever
    relaxed."""
    fx = await make_org(db, "Acme")
    org_id = fx["org"].id

    scope, why = await resolve_scope(db, org_id, "site_admin", None)
    assert scope is None and "pass --site" in why

    scope, why = await resolve_scope(db, org_id, "site_admin", "Atlantis")
    assert scope is None and "no site named 'Atlantis'" in why


async def test_a_site_in_another_tenant_does_not_resolve(db):
    """The lookup is scoped by organization, so naming another tenant's office
    is "no such site" rather than a grant over it."""
    acme = await make_org(db, "Acme")
    globex = await make_org(db, "Globex")

    scope, why = await resolve_scope(
        db, acme["org"].id, "site_admin", globex["site"].name
    )
    assert scope is None
    assert "no site named" in why

    scope, why = await resolve_scope(db, acme["org"].id, "site_admin", acme["site"].name)
    assert scope == acme["site"].id and why is None


async def test_an_org_grant_takes_no_scope(db):
    fx = await make_org(db, "Acme")
    scope, why = await resolve_scope(db, fx["org"].id, "org_admin", None)
    assert scope is None and why is None

    scope, why = await resolve_scope(db, fx["org"].id, "org_admin", "Tampa")
    assert "takes no" in why


async def test_a_team_lead_grant_resolves_against_groups_not_sites(db):
    """`team_lead` is scoped to a group. Looking it up in `site` would make
    the flag silently useless."""
    fx = await make_org(db, "Acme")
    scope, why = await resolve_scope(db, fx["org"].id, "team_lead", fx["team"].name)
    assert scope == fx["team"].id and why is None

    scope, why = await resolve_scope(db, fx["org"].id, "team_lead", fx["site"].name)
    assert scope is None and "no user group named" in why


# --------------------------------------------------------------------------
# End to end, through main()
# --------------------------------------------------------------------------


@pytest.fixture
def invoke(db, monkeypatch):
    """Drive the command the way the shell does, minus the event loop.

    `main` is parse + `asyncio.run`, and asyncio.run cannot nest inside these
    async tests, so the tests call `run` -- everything below that shim --
    with the same parsed arguments. The session is redirected to the test's,
    which the fixture's transaction can actually see.
    """
    from contextlib import asynccontextmanager

    import app.grant_admin as mod

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(mod, "SessionLocal", session)

    async def call(*args) -> int:
        return await run(parse(argv(*args)))

    return call


async def test_a_dry_run_writes_nothing(invoke, db):
    fx = await make_org(db, "Acme")
    assert await invoke(fx["user"].email, "org_admin") == 0
    assert await grants(db, fx["org"].id) == []


async def test_applying_writes_exactly_one_grant(invoke, db):
    fx = await make_org(db, "Acme")
    assert await invoke(fx["user"].email, "org_admin", "--apply") == 0
    assert await grants(db, fx["org"].id) == [("org_admin", "org")]


async def test_applying_twice_is_a_no_op(invoke, db):
    """It is additive and idempotent, which is the trade for not having the
    seed's `--yes` guard against a remote host."""
    fx = await make_org(db, "Acme")
    await invoke(fx["user"].email, "org_admin", "--apply")
    assert await invoke(fx["user"].email, "org_admin", "--apply") == 0
    assert await grants(db, fx["org"].id) == [("org_admin", "org")]


async def test_a_site_grant_records_the_site_scope(invoke, db):
    fx = await make_org(db, "Acme")
    assert (
        await invoke(
            fx["user"].email, "site_admin", "--site", fx["site"].name, "--apply"
        )
        == 0
    )
    row = (await db.execute(select(RoleGrant))).scalar_one()
    assert (row.role, row.scope_type, row.scope_id) == (
        "site_admin",
        "site",
        fx["site"].id,
    )


async def test_an_unknown_person_is_an_error_and_writes_nothing(invoke, db):
    fx = await make_org(db, "Acme")
    assert await invoke("nobody@acme.example", "org_admin", "--apply") == 1
    assert await grants(db, fx["org"].id) == []


async def test_a_deactivated_account_is_refused(invoke, db):
    """Granting a role to a deactivated account is almost always a typo, and
    the silent version of it is a dormant admin."""
    fx = await make_org(db, "Acme")
    leaver = await add_person(db, fx, "Ren")
    leaver.status = "deactivated"
    await db.flush()
    await db.commit()

    assert await invoke(leaver.email, "org_admin", "--apply") == 1
    assert await grants(db, fx["org"].id) == []


async def test_it_cannot_revoke(invoke, db):
    """Deliberately absent. Removing the last org admin leaves an org nobody
    can administer, and the console refuses exactly that
    (test_the_last_org_admin_cannot_be_demoted). A CLI that could revoke would
    be a way around a rule the product enforces on purpose."""
    with pytest.raises(SystemExit):
        parse(argv("a@b.c", "org_admin", "--revoke"))


async def test_listing_never_writes(invoke, db):
    fx = await make_org(db, "Acme")
    assert await invoke("--list", "--apply") == 0
    assert await grants(db, fx["org"].id) == []


async def test_the_listing_names_the_scope_rather_than_its_id(invoke, db, capsys):
    """An operator reading this wants "Tampa", not a uuid -- and the join has
    to reach both sites and groups, because the two scoped roles live in
    different tables."""
    fx = await make_org(db, "Acme")
    other = await add_person(db, fx, "Ren")
    await invoke(fx["user"].email, "site_admin", "--site", fx["site"].name, "--apply")
    await invoke(other.email, "team_lead", "--team", fx["team"].name, "--apply")
    capsys.readouterr()

    await invoke("--list")
    out = capsys.readouterr().out
    assert "Acme HQ" in out
    assert "Core" in out
    assert str(fx["site"].id) not in out
