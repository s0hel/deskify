"""Settings, and the guards that stop an unconfigured deployment from booting.

Three things in this file are gated on `environment`: the JWT signing key, the
database credentials, and `/auth/dev-sign-in`, which mints a token for any user
given only an email address. All three are safe in dev and catastrophic in
production.

So `environment` defaults to **prod**, not dev. An operator who forgets to set
DESKFLOW_ENVIRONMENT gets the locked-down behaviour and a startup failure, not a
silent auth bypass. Running in dev is an explicit opt-in, which the dev tooling
does (see the Makefile and .env.example).

Note that no guard below ever puts a secret in its error message. These errors
land in logs and crash reporters; an error that helpfully echoes the password it
rejected has leaked it somewhere worse than the config file.
"""

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

#: The values shipped in source. Present so the guards can recognise them.
DEV_JWT_SECRET = "dev-only-not-a-real-secret"
DEV_DATABASE_URL = "postgresql+asyncpg://deskflow:deskflow@localhost:55432/deskflow"

#: HS256 keys shorter than this are weak. A guard that only rejected the exact
#: default above would be defeated by someone typing "changeme".
MIN_JWT_SECRET_LENGTH = 32

#: Same reasoning for the database password.
MIN_DB_PASSWORD_LENGTH = 16

#: Passwords that are technically "changed" but no better than the default.
WEAK_DB_PASSWORDS = frozenset(
    {
        "deskflow", "postgres", "password", "passwd", "changeme", "change_me",
        "admin", "root", "secret", "test", "dev", "letmein", "database",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DESKFLOW_", env_file=".env")

    database_url: str = DEV_DATABASE_URL
    jwt_secret: str = DEV_JWT_SECRET
    access_token_ttl_seconds: int = 600
    environment: Literal["dev", "staging", "prod"] = "prod"

    @property
    def is_dev(self) -> bool:
        return self.environment == "dev"

    @model_validator(mode="after")
    def _refuse_weak_signing_key_outside_dev(self) -> "Settings":
        if self.is_dev:
            return self

        if self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError(
                f"DESKFLOW_JWT_SECRET is still the development default while "
                f"DESKFLOW_ENVIRONMENT={self.environment!r}. That key is published in "
                f"this repository's source, so anyone could mint valid tokens. "
                f"Set a real secret, e.g. `openssl rand -base64 48`."
            )

        if len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"DESKFLOW_JWT_SECRET is {len(self.jwt_secret)} characters; "
                f"at least {MIN_JWT_SECRET_LENGTH} are required outside dev. "
                f"Generate one with `openssl rand -base64 48`."
            )

        return self

    @model_validator(mode="after")
    def _refuse_weak_database_credentials_outside_dev(self) -> "Settings":
        if self.is_dev:
            return self

        env = self.environment
        hint = "Generate one with `openssl rand -base64 32`."

        if self.database_url == DEV_DATABASE_URL:
            raise ValueError(
                f"DESKFLOW_DATABASE_URL is still the development default while "
                f"DESKFLOW_ENVIRONMENT={env!r}. Those credentials are published in this "
                f"repository's source. Point it at the real database. {hint}"
            )

        try:
            url = make_url(self.database_url)
        except ArgumentError:
            # The raised message may contain the URL, so it is not chained in.
            raise ValueError(
                "DESKFLOW_DATABASE_URL could not be parsed as a database URL."
            ) from None

        # Everything below reports only the SHAPE of the problem, never the value.
        if not url.password:
            raise ValueError(
                f"DESKFLOW_DATABASE_URL has no password while "
                f"DESKFLOW_ENVIRONMENT={env!r}. {hint}"
            )

        if url.password == url.username:
            raise ValueError(
                f"DESKFLOW_DATABASE_URL uses the username as the password while "
                f"DESKFLOW_ENVIRONMENT={env!r}. {hint}"
            )

        if url.password.lower() in WEAK_DB_PASSWORDS:
            raise ValueError(
                f"DESKFLOW_DATABASE_URL uses a well-known placeholder password while "
                f"DESKFLOW_ENVIRONMENT={env!r}. {hint}"
            )

        if len(url.password) < MIN_DB_PASSWORD_LENGTH:
            raise ValueError(
                f"The DESKFLOW_DATABASE_URL password is {len(url.password)} characters; "
                f"at least {MIN_DB_PASSWORD_LENGTH} are required outside dev. {hint}"
            )

        return self


settings = Settings()
