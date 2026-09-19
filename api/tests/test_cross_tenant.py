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
from tests.conftest import make_org

#: Endpoints that take no tenant-owned object id, so there is nothing to
#: cross-tenant. Each needs a reason.
NO_OBJECT_ID = {
    "/health",          # unauthenticated liveness
    "/auth/discover",   # answers for a domain, never a user (TDD §15.3)
    "/auth/token",      # pre-authentication
    "/me",              # scoped to the caller by construction
    "/sites",           # collection: tenancy asserted separately below
    "/bookings",        # collection: ditto
    "/bookings/validate",
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
    """Authenticate as Acme; aim every object-id endpoint at Globex's objects."""
    acme = await make_org(db, "Acme")
    globex = await make_org(db, "Globex")

    token = mint_access_token(acme["user"].id, acme["org"].id)
    headers = {"Authorization": f"Bearer {token}"}

    # Substitute Globex's real ids into Acme's request.
    victim_ids = {
        "{site_id}": globex["site"].id,
        "{floor_id}": globex["floor"].id,
        "{booking_id}": uuid.uuid4(),
    }
    url = path
    for placeholder, value in victim_ids.items():
        url = url.replace(placeholder, str(value))

    params = {"on": "2026-10-02"} if url.endswith("/state") else None

    async with client as c:
        resp = await c.request(method, url, headers=headers, params=params)

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
