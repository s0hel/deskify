"""The deployment guards in app/config.py.

Two things are gated on `environment`: the JWT signing key, and
/auth/dev-sign-in, which mints a token for any user given only an email. Both
are safe in dev and catastrophic in production, so the default must fail closed.

These tests exist to stop someone "simplifying" the default back to dev.
"""

import pytest
from pydantic import ValidationError

from app.config import DEV_JWT_SECRET, MIN_JWT_SECRET_LENGTH, Settings

REAL_SECRET = "K" * MIN_JWT_SECRET_LENGTH


def test_environment_defaults_to_prod_not_dev():
    """The whole point. An operator who sets nothing gets locked-down
    behaviour, not a silent auth bypass."""
    assert Settings.model_fields["environment"].default == "prod"


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_refuses_to_boot_with_the_source_default_secret(env):
    with pytest.raises(ValidationError, match="development default"):
        Settings(environment=env, jwt_secret=DEV_JWT_SECRET)


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_refuses_a_short_secret(env):
    """A guard that only rejected the exact default would be defeated by
    someone typing 'changeme'."""
    with pytest.raises(ValidationError, match="characters"):
        Settings(environment=env, jwt_secret="changeme")


def test_boundary_length_is_accepted():
    assert Settings(environment="prod", jwt_secret=REAL_SECRET).jwt_secret == REAL_SECRET


def test_one_character_below_the_floor_is_refused():
    with pytest.raises(ValidationError):
        Settings(environment="prod", jwt_secret="K" * (MIN_JWT_SECRET_LENGTH - 1))


def test_dev_may_use_the_default_secret():
    """Otherwise every contributor needs a secret to run the test suite."""
    assert Settings(environment="dev").jwt_secret == DEV_JWT_SECRET
    assert Settings(environment="dev").is_dev is True


def test_unknown_environment_is_refused():
    """A typo like 'production' must not silently behave as a third mode."""
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret=REAL_SECRET)


def test_is_dev_is_false_outside_dev():
    """This property gates /auth/dev-sign-in."""
    assert Settings(environment="prod", jwt_secret=REAL_SECRET).is_dev is False
    assert Settings(environment="staging", jwt_secret=REAL_SECRET).is_dev is False
