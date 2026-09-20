"""TDD §16.3 -- the cross-tenant harness.

Driven from the OpenAPI schema rather than a hand-written list, so a new
endpoint is covered the day it is added. That is the only way this stays true.

Asserts 404, never 403: a 403 confirms the object exists (TDD §15.1).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import mint_access_token
from app.db import get_session
from app.main import app
from tests.conftest import grant_role, make_org

#: Endpoints that take no tenant-owned object id, so there is nothing to
#: cross-tenant. Each needs a reason.
NO_OBJECT_ID = {
    "/health",          # unauthenticated liveness
    "/auth/discover",   # answers for a domain, never a user (TDD §15.3)
    "/auth/token",      # pre-authentication
    "/me",              # scoped to the caller by construction
    "/me/privacy",      # ditto
    # Takes a site id, but in the BODY, so this path-driven harness cannot
    # reach it. Covered explicitly by test_home_site.py::
    # test_another_tenants_site_cannot_become_your_home.
    "/me/home-site",
    # Collection GET and org-scoped POST share a path: both create in, or read
    # from, the caller's own tenant.
    "/sites",
    "/bookings",        # collection: ditto
    "/bookings/validate",
    "/people",          # collection, privacy-filtered; see test_presence_privacy.py
    # The path parameter is a DATE, and the row is always the caller's own.
    # There is no other tenant's object to aim at.
    "/me/declarations/{on}",
    # --- admin (FR-8.x). Collections and create endpoints: the tenant comes
    # from the token, and the id they take is in the BODY, which this
    # path-driven harness cannot substitute into. Each body-id case is
    # asserted by hand in tests/test_admin.py -- see
    # test_admin.py::test_an_admin_cannot_reach_another_tenant_through_a_body.
    "/floors",          # POST: site_id in the body
    "/zones",           # POST: floor_id in the body
    "/bookings/admin",  # POST: user_id and resource_id in the body
    "/admin/users",     # collection + create, scoped to the caller's org
    "/admin/groups",    # ditto
    "/admin/floors",    # collection, filtered to administered sites
    "/admin/zones",     # ditto
    "/admin/bookings",  # ditto
    "/audit",           # collection, scoped to the caller's org
}


def object_id_paths() -> list[tuple[str, str]]:
    """Every (method, path) in the live schema that takes a path parameter."""
    schema = app.openapi()
    found = []
    for path, ops in schema["paths"].items():
        if path in NO_OBJECT_ID:
            continue
        if "{" not in path:
            continue
        for method in ops:
            found.append((method.upper(), path))
    return sorted(found)


def test_the_harness_actually_covers_something():
    """Guards against the harness silently degrading to zero cases."""
    assert len(object_id_paths()) >= 4, object_id_paths()


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
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path", object_id_paths())
async def test_cannot_touch_another_orgs_objects(method, path, db, client):
    """Authenticate as Acme; aim every object-id endpoint at Globex's objects.

    ACME'S USER IS AN ORG ADMIN HERE, and that is the point rather than a
    convenience. Without the grant every admin endpoint would answer 403 --
    "you are not an administrator" -- and the test would pass without ever
    reaching the tenancy check it exists to exercise. Granting the strongest
    role in the org makes this the assertion worth having: being an
    administrator of YOUR organization confers nothing over anyone else's.

    The two answers are not interchangeable and both are deliberate. 403 is a
    fact about the caller and discloses nothing; 404 is the answer about an
    object, and must stay 404 so that it cannot confirm the object exists
    (TDD §15.1, app/authz.py).
    """
    acme = await make_org(db, "Acme")
    globex = await make_org(db, "Globex")
    await grant_role(db, acme, acme["user"], "org_admin")

    token = mint_access_token(acme["user"].id, acme["org"].id)
    headers = {"Authorization": f"Bearer {token}"}

    # Substitute Globex's real ids into Acme's request.
    victim_ids = {
        "{site_id}": globex["site"].id,
        "{floor_id}": globex["floor"].id,
        "{zone_id}": globex["zone"].id,
        "{resource_id}": globex["desk"].id,
        "{group_id}": globex["team"].id,
        "{user_id}": globex["user"].id,
        "{team_id}": globex["team"].id,
        "{booking_id}": uuid.uuid4(),
    }
    url = path
    for placeholder, value in victim_ids.items():
        url = url.replace(placeholder, str(value))

    # A placeholder we have no victim id for would send a literal "{id}", get a
    # 422, and never reach the tenancy check -- a test that passes by accident.
    assert "{" not in url, (
        f"{path} has a path parameter with no victim id. Add one to victim_ids, "
        f"or list the path in NO_OBJECT_ID with a reason."
    )

    params = (
        {"on": "2026-10-02"}
        if url.endswith(("/state", "/people"))
        else None
    )
    # Bodies that satisfy validation, so a 422 never stands in for the 404
    # this is actually asserting. Content, not shape, is what is being tested.
    required = {
        "/resources/{resource_id}/out-of-service": {"reason": "Monitor replaced"},
        "/admin/users/{user_id}/roles": {"roles": []},
        "/admin/groups/{group_id}/members": {"user_ids": []},
    }
    # Everything else that writes takes an all-optional body, so an empty
    # object is valid and the request reaches the handler.
    body = required.get(path, {} if method in ("POST", "PUT", "PATCH") else None)

    async with client as c:
        resp = await c.request(method, url, headers=headers, params=params, json=body)

    assert resp.status_code == 404, (
        f"{method} {path} leaked across tenants: got {resp.status_code} "
        f"{resp.text[:200]}"
    )


async def test_collections_only_return_the_callers_tenant(db, client):
    acme = await make_org(db, "Acme")
    await make_org(db, "Globex")
    token = mint_access_token(acme["user"].id, acme["org"].id)

    async with client as c:
        resp = await c.get("/sites", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == ["Acme HQ"], names


async def test_unauthenticated_is_401_not_404(db, client):
    async with client as c:
        resp = await c.get("/sites")
    assert resp.status_code == 401


async def test_repository_refuses_untracked_models():
    """The repository is the only way to reach tenant data, so it fails loudly
    on a model nobody remembered to scope."""
    from app.models import Organization
    from app.repository import TenantRepository

    repo = TenantRepository(None, uuid.uuid4())
    with pytest.raises(RuntimeError, match="not tenant-scoped"):
        await repo.get(Organization, uuid.uuid4())
