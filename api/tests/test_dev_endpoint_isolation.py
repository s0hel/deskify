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

async def main():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        dev = await c.post("/auth/dev-sign-in", json={"email": "nobody@example.com"})
        disc = await c.post("/auth/discover", json={"email": "nobody@example.com"})
    print(json.dumps({
        "environment": settings.environment,
        "dev_sign_in": dev.status_code,
        "discover": disc.status_code,
    }))

asyncio.run(main())
"""

REAL_SECRET = "x" * 48


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
def test_dev_sign_in_does_not_exist_outside_dev(env):
    result = probe({"DESKFLOW_ENVIRONMENT": env, "DESKFLOW_JWT_SECRET": REAL_SECRET})
    assert result.returncode == 0, result.stderr[-800:]
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert body["environment"] == env
    assert body["dev_sign_in"] == 404, f"auth bypass reachable in {env}: {body}"
    # The real auth surface is untouched.
    assert body["discover"] == 200, body


def test_app_refuses_to_import_with_the_default_secret_outside_dev():
    """The config guard, exercised through a real process start."""
    result = probe({"DESKFLOW_ENVIRONMENT": "prod"})
    assert result.returncode != 0, "the app booted in prod with the source default secret"
    assert "development default" in result.stderr
