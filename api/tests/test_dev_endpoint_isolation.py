"""/auth/dev-sign-in must not exist outside dev.

That endpoint mints a token for any user given nothing but an email address, so
"registered but refuses" is not good enough -- a future refactor could drop the
refusal and leave a live auth bypass. The route itself is mounted conditionally
(app/main.py), and this proves it.

Each case runs in a SUBPROCESS: the app's composition happens at import time, so
testing it in-process would mean reloading modules other tests already hold
references to.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]

PROBE = """
import asyncio, json
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.config import settings

async def status(client, path):
    # A handler that runs and then fails (no database reachable in this probe)
    # still proves the ROUTE EXISTS, which is the property under test. Only a
    # 404 means it was never mounted.
    try:
        r = await client.post(path, json={"email": "nobody@example.com"})
        return r.status_code
    except Exception:
        return "raised"

async def main():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        dev = await status(c, "/auth/dev-sign-in")
        disc = await status(c, "/auth/discover")
    print(json.dumps({
        "environment": settings.environment,
        "dev_sign_in": dev,
        "discover": disc,
    }))

asyncio.run(main())
"""

REAL_SECRET = "x" * 48
#: .invalid is reserved by RFC 6761 and never resolves, so the probe's database
#: connection fails INSTANTLY. A plausible-looking hostname can hit a slow
#: resolver or a wildcard search domain and make this suite flaky.
REAL_DB_URL = "postgresql+asyncpg://svc_deskflow:" + ("P" * 24) + "@db.invalid:5432/deskflow"

#: A fully-configured non-dev environment, so these tests exercise the ROUTE
#: mounting rather than tripping a credential guard on the way in.
PROD_ENV = {"DESKFLOW_JWT_SECRET": REAL_SECRET, "DESKFLOW_DATABASE_URL": REAL_DB_URL}


def probe(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=API_DIR,
        env={**os.environ, "PYTHONPATH": str(API_DIR), **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,  # a non-zero exit IS the expected result in one case
    )


def test_dev_sign_in_is_reachable_in_dev():
    result = probe({"DESKFLOW_ENVIRONMENT": "dev"})
    assert result.returncode == 0, result.stderr[-800:]
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert body["environment"] == "dev"
    # 400 "unknown user", not 404: the route exists and ran.
    assert body["dev_sign_in"] == 400, body


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_dev_sign_in_does_not_exist_outside_dev_by_default(env):
    """The default must stay off. It can be switched on (see below), but never
    by forgetting a variable."""
    result = probe({"DESKFLOW_ENVIRONMENT": env, **PROD_ENV})
    assert result.returncode == 0, result.stderr[-800:]
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert body["environment"] == env
    assert body["dev_sign_in"] == 404, f"auth bypass reachable in {env}: {body}"
    # The real auth surface is untouched: /auth/discover is still mounted.
    # Anything but 404 proves that -- this probe has no database, so the
    # handler is expected to run and then fail.
    assert body["discover"] != 404, body


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_the_explicit_switch_mounts_it_outside_dev(env):
    """DESKFLOW_ALLOW_DEV_SIGN_IN is the only way to get this outside dev.

    It exists because the alternative people reach for -- setting
    DESKFLOW_ENVIRONMENT=dev -- also disables TLS and re-enables asyncpg's
    statement cache, so it breaks a managed database while granting far more
    than was intended. One switch, one effect, one name that says what it does.
    """
    result = probe(
        {"DESKFLOW_ENVIRONMENT": env, "DESKFLOW_ALLOW_DEV_SIGN_IN": "true", **PROD_ENV}
    )
    assert result.returncode == 0, result.stderr[-800:]
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert body["environment"] == env
    # Anything but 404 proves the route is mounted. This probe has no reachable
    # database (PROD_ENV points at db.invalid), so the handler is expected to
    # run and then fail looking the user up -- which is still proof it ran.
    assert body["dev_sign_in"] != 404, f"the switch did not mount the route in {env}: {body}"


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_the_switch_does_not_relax_the_database_settings(env):
    """Turning on dev sign-in must not quietly drop TLS or re-enable the
    statement cache -- the failure mode of the blunt alternative."""
    from app.config import Settings

    s = Settings(
        environment=env,
        allow_dev_sign_in=True,
        jwt_secret=REAL_SECRET,
        database_url=REAL_DB_URL,
    )
    assert s.dev_sign_in_enabled is True
    assert s.dev_sign_in_is_exposed is True
    assert s.db_connect_args == {"statement_cache_size": 0, "ssl": "require"}


def test_the_switch_is_off_unless_asked_for():
    from app.config import Settings

    s = Settings(environment="prod", jwt_secret=REAL_SECRET, database_url=REAL_DB_URL)
    assert s.allow_dev_sign_in is False
    assert s.dev_sign_in_enabled is False
    assert s.dev_sign_in_is_exposed is False


def test_dev_is_not_reported_as_exposed():
    """In dev it is expected, so it must not trip the warning that is meant to
    mean 'someone did this to a deployment'."""
    from app.config import Settings

    assert Settings(environment="dev").dev_sign_in_enabled is True
    assert Settings(environment="dev").dev_sign_in_is_exposed is False


def test_app_refuses_to_import_with_the_default_secret_outside_dev():
    """The config guards, exercised through a real process start."""
    result = probe({"DESKFLOW_ENVIRONMENT": "prod"})
    assert result.returncode != 0, "the app booted in prod with the source default secret"
    assert "development default" in result.stderr


def test_app_refuses_to_import_with_the_default_database_url_outside_dev():
    """A real signing key is not enough if the database credentials are the
    published ones."""
    result = probe({"DESKFLOW_ENVIRONMENT": "prod", "DESKFLOW_JWT_SECRET": REAL_SECRET})
    assert result.returncode != 0, "the app booted in prod with the source default database URL"
    assert "DESKFLOW_DATABASE_URL" in result.stderr
