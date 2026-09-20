"""The deployment guards in app/config.py.

Three things are gated on `environment`: the JWT signing key, the database
credentials, and /auth/dev-sign-in, which mints a token for any user given only
an email. All are safe in dev and catastrophic in production, so the default
must fail closed.

These tests exist to stop someone "simplifying" the default back to dev.
"""

import pytest
from pydantic import ValidationError

from app.config import (
    DEV_DATABASE_URL,
    DEV_JWT_SECRET,
    MIN_DB_PASSWORD_LENGTH,
    MIN_JWT_SECRET_LENGTH,
    WEAK_DB_PASSWORDS,
    Settings,
)

REAL_SECRET = "K" * MIN_JWT_SECRET_LENGTH
REAL_DB_PASSWORD = "P" * MIN_DB_PASSWORD_LENGTH
REAL_DB_URL = f"postgresql+asyncpg://svc_deskify:{REAL_DB_PASSWORD}@db.invalid:5432/deskify"


def prod(**over) -> dict:
    """A settings payload that is valid outside dev, so each test varies one thing."""
    return {
        "environment": "prod",
        "jwt_secret": REAL_SECRET,
        "database_url": REAL_DB_URL,
        **over,
    }


def test_environment_defaults_to_prod_not_dev():
    """The whole point. An operator who sets nothing gets locked-down
    behaviour, not a silent auth bypass."""
    assert Settings.model_fields["environment"].default == "prod"


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_refuses_to_boot_with_the_source_default_secret(env):
    with pytest.raises(ValidationError, match="development default"):
        Settings(**prod(environment=env, jwt_secret=DEV_JWT_SECRET))


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_refuses_a_short_secret(env):
    """A guard that only rejected the exact default would be defeated by
    someone typing 'changeme'."""
    with pytest.raises(ValidationError, match="characters"):
        Settings(**prod(environment=env, jwt_secret="changeme"))


def test_boundary_length_secret_is_accepted():
    assert Settings(**prod()).jwt_secret == REAL_SECRET


def test_one_character_below_the_secret_floor_is_refused():
    with pytest.raises(ValidationError):
        Settings(**prod(jwt_secret="K" * (MIN_JWT_SECRET_LENGTH - 1)))


def test_dev_may_use_the_default_secret():
    """Otherwise every contributor needs a secret to run the test suite."""
    assert Settings(environment="dev").jwt_secret == DEV_JWT_SECRET
    assert Settings(environment="dev").is_dev is True


def test_unknown_environment_is_refused():
    """A typo like 'production' must not silently behave as a third mode."""
    with pytest.raises(ValidationError):
        Settings(**prod(environment="production"))


def test_is_dev_is_false_outside_dev():
    """This property gates /auth/dev-sign-in."""
    assert Settings(**prod()).is_dev is False
    assert Settings(**prod(environment="staging")).is_dev is False


# --------------------------------------------------------------------------
# Database credentials. Same reasoning as the signing key: the values in this
# repository are published, and "technically changed" is not the same as safe.
# --------------------------------------------------------------------------


def test_a_fully_configured_prod_settings_boots():
    """Guards the guards: if this ever fails, the cases below prove nothing."""
    assert Settings(**prod()).environment == "prod"


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_refuses_the_source_default_database_url(env):
    with pytest.raises(ValidationError, match="development default"):
        Settings(**prod(environment=env, database_url=DEV_DATABASE_URL))


def test_refuses_a_url_with_no_password():
    with pytest.raises(ValidationError, match="no password"):
        Settings(**prod(database_url="postgresql+asyncpg://svc@db.invalid/deskify"))


def test_refuses_password_equal_to_username():
    """The deskify:deskify shape, renamed."""
    with pytest.raises(ValidationError, match="username as the password"):
        Settings(**prod(database_url="postgresql+asyncpg://acme:acme@db.invalid/deskify"))


@pytest.mark.parametrize("weak", sorted(WEAK_DB_PASSWORDS))
def test_refuses_well_known_placeholder_passwords(weak):
    with pytest.raises(ValidationError, match="placeholder password"):
        Settings(**prod(database_url=f"postgresql+asyncpg://svc:{weak}@db.invalid/deskify"))


def test_placeholder_check_ignores_case():
    with pytest.raises(ValidationError, match="placeholder password"):
        Settings(**prod(database_url="postgresql+asyncpg://svc:ChangeMe@db.invalid/deskify"))


def test_refuses_a_short_password():
    short = "a1B2c3D4"
    assert len(short) < MIN_DB_PASSWORD_LENGTH
    with pytest.raises(ValidationError, match="characters"):
        Settings(**prod(database_url=f"postgresql+asyncpg://svc:{short}@db.invalid/deskify"))


def test_boundary_length_password_is_accepted():
    assert Settings(**prod()).database_url == REAL_DB_URL


def test_one_character_below_the_floor_is_refused():
    pw = "P" * (MIN_DB_PASSWORD_LENGTH - 1)
    with pytest.raises(ValidationError, match="characters"):
        Settings(**prod(database_url=f"postgresql+asyncpg://svc:{pw}@db.invalid/deskify"))


def test_refuses_an_unparseable_url():
    with pytest.raises(ValidationError, match="could not be parsed"):
        Settings(**prod(database_url="this is not a url"))


def test_dev_may_use_the_default_database_url():
    """Otherwise every contributor needs real credentials to run the suite.

    Passed explicitly because conftest points DESKIFY_DATABASE_URL at the
    separate test database -- the property under test is that dev ACCEPTS the
    published default, not what happens to be in the environment."""
    assert (
        Settings(environment="dev", database_url=DEV_DATABASE_URL).database_url
        == DEV_DATABASE_URL
    )


def test_localhost_is_not_itself_rejected():
    """A socket or sidecar in production is legitimate. The guard is about
    credentials, not topology -- it must not become a host allowlist."""
    url = f"postgresql+asyncpg://svc:{REAL_DB_PASSWORD}@localhost:5432/deskify"
    assert Settings(**prod(database_url=url)).database_url == url


# --------------------------------------------------------------------------
# These errors land in logs and crash reporters.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "postgresql+asyncpg://svc:sh0rt@db.invalid/deskify",
        "postgresql+asyncpg://svc:ChangeMe@db.invalid/deskify",
        "postgresql+asyncpg://acme:acme@db.invalid/deskify",
        "this is not a url",
    ],
)
def test_guard_errors_never_echo_the_credential(bad_url):
    """An error that helpfully prints the password it rejected has leaked it
    somewhere worse than the config file."""
    with pytest.raises(ValidationError) as caught:
        Settings(**prod(database_url=bad_url))

    message = str(caught.value)
    assert bad_url not in message
    for secret in ("sh0rt", "ChangeMe", "acme:acme"):
        assert secret not in message, f"{secret!r} leaked into the error message"


def test_jwt_guard_errors_never_echo_the_key():
    with pytest.raises(ValidationError) as caught:
        Settings(**prod(jwt_secret="hunter2-but-too-short"))
    assert "hunter2" not in str(caught.value)


# --------------------------------------------------------------------------
# CORS and database connection options -- both differ between a local
# container and a managed database, and both fail in ways that look like
# application bugs.
# --------------------------------------------------------------------------


def test_cors_origins_accept_a_comma_list():
    """What an operator types into a deployment dashboard."""
    s = Settings(**prod(cors_origins="https://a.example, https://b.example"))
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]


def test_cors_origins_accept_a_json_list():
    s = Settings(**prod(cors_origins='["https://a.example","https://b.example"]'))
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]


def test_cors_origins_forgive_a_trailing_slash():
    """An origin with a trailing slash never matches, and the symptom is a CORS
    failure that looks like a code bug."""
    assert Settings(**prod(cors_origins="https://a.example/")).cors_origin_list == [
        "https://a.example"
    ]


def test_wildcard_cors_is_refused_outside_dev():
    with pytest.raises(ValidationError, match=r"\*"):
        Settings(**prod(cors_origins="https://a.example,*"))


def test_dev_may_use_a_wildcard():
    assert "*" in Settings(environment="dev", cors_origins="*").cors_origin_list


def test_managed_database_gets_tls_and_no_statement_cache():
    """A transaction-mode pooler hands each transaction a different backend, so
    cached prepared statements point at connections that no longer hold them.
    The symptom is an intermittent failure under load."""
    args = Settings(**prod()).db_connect_args
    assert args["ssl"] == "require"
    assert args["statement_cache_size"] == 0


def test_local_dev_keeps_prepared_statements_and_plaintext():
    assert Settings(environment="dev").db_connect_args == {}


# ---------------------------------------------------------------------------
# The DESKFLOW_ -> DESKIFY_ prefix migration (app/config.py).
#
# These run in a SUBPROCESS because the shim rewrites os.environ at IMPORT time;
# in-process it has already run against this session's environment.
#
# Delete this block together with the shim, once no deployment sets DESKFLOW_*.
# ---------------------------------------------------------------------------

import json
import os
import subprocess
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]
_PROBE = (
    "from app.config import settings; import json; "
    "print(json.dumps({'environment': settings.environment, "
    "'jwt_len': len(settings.jwt_secret)}))"
)
_LEGACY_DB_URL = f"postgresql+asyncpg://svc:{REAL_DB_PASSWORD}@db.invalid:5432/d"


def _boot(env: dict[str, str]) -> dict:
    """Start a fresh interpreter with ONLY the given DESK* variables set."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DESKIFY_", "DESKFLOW_"))}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_API_DIR,
        env={**clean, "PYTHONPATH": str(_API_DIR), **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-800:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_deployment_still_on_the_legacy_prefix_boots():
    """The reason the shim exists. Variables live in a dashboard, not in this
    repo, so renaming the prefix here must not take production down until
    someone re-types them."""
    body = _boot(
        {
            "DESKFLOW_ENVIRONMENT": "prod",
            "DESKFLOW_JWT_SECRET": REAL_SECRET,
            "DESKFLOW_DATABASE_URL": _LEGACY_DB_URL,
        }
    )
    assert body == {"environment": "prod", "jwt_len": len(REAL_SECRET)}


def test_the_new_prefix_wins_when_both_are_set():
    """So the migration can go one variable at a time instead of all at once."""
    body = _boot(
        {
            "DESKFLOW_ENVIRONMENT": "prod",
            "DESKFLOW_JWT_SECRET": "S" * 60,
            "DESKIFY_ENVIRONMENT": "staging",
            "DESKIFY_JWT_SECRET": REAL_SECRET,
            "DESKIFY_DATABASE_URL": _LEGACY_DB_URL,
        }
    )
    assert body["environment"] == "staging"
    assert body["jwt_len"] == len(REAL_SECRET)


def test_the_legacy_prefix_does_not_reopen_the_dev_default():
    """A legacy name must still go through every guard -- the shim moves values,
    it does not exempt them."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DESKIFY_", "DESKFLOW_"))}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_API_DIR,
        env={
            **clean,
            "PYTHONPATH": str(_API_DIR),
            "DESKFLOW_ENVIRONMENT": "prod",
            "DESKFLOW_JWT_SECRET": DEV_JWT_SECRET,
            "DESKFLOW_DATABASE_URL": _LEGACY_DB_URL,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0, "booted in prod with the published dev signing key"
    assert "development default" in result.stderr


def test_both_old_and_new_names_are_refused_as_database_passwords():
    """Renaming the product must not retire the old weak password."""
    assert "deskflow" in WEAK_DB_PASSWORDS
    assert "deskify" in WEAK_DB_PASSWORDS
