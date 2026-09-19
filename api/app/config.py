from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DESKFLOW_", env_file=".env")

    database_url: str = "postgresql+asyncpg://deskflow:deskflow@localhost:55432/deskflow"
    jwt_secret: str = "dev-only-not-a-real-secret"
    access_token_ttl_seconds: int = 600
    environment: str = "dev"


settings = Settings()
