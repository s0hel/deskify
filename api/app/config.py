"""Settings, and the guards that stop an unconfigured deployment from booting.

Two things in this file are gated on `environment`: the signing key below, and
`/auth/dev-sign-in`, which mints a token for any user given only an email
address. Both are safe in dev and catastrophic in production.

So `environment` defaults to **prod**, not dev. An operator who forgets to set
DESKFLOW_ENVIRONMENT gets the locked-down behaviour and a startup failure, not a
silent auth bypass. Running in dev is an explicit opt-in, which is what the dev
tooling does (see the Makefile and .env.example).
"""

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The value shipped in source. Present so the guard can recognise it.
DEV_JWT_SECRET = "dev-only-not-a-real-secret"

#: HS256 keys shorter than this are weak. A guard that only rejected the exact
#: default above would be defeated by someone typing "changeme".
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DESKFLOW_", env_file=".env")

    database_url: str = "postgresql+asyncpg://deskflow:deskflow@localhost:55432/deskflow"
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


settings = Settings()
