"""Typed application settings, loaded from environment variables prefixed ``OM_``."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Office-Mates"
    environment: Environment = Environment.LOCAL
    git_sha: str = "dev"

    log_level: str = "INFO"
    log_json: bool = True

    cors_origins: list[str] = Field(default_factory=list)

    # Redis: Celery broker (db 0), Celery results (db 1); later rate limits and caches.
    # Unset means "no Redis": the API still runs, without the Redis readiness check.
    redis_url: SecretStr | None = None

    # MySQL, as mysql+asyncmy://user:password@host:port/database.
    # database_url is the application account (app_rw: data only, no schema changes).
    # database_migration_url is the migrator account and is given only to the migration job.
    database_url: SecretStr | None = None
    database_migration_url: SecretStr | None = None
    database_pool_size: int = 5

    # OpenAPI docs UI is only exposed where we explicitly allow it (never in prod by default).
    docs_enabled: bool | None = None

    # Auth (ADR/blueprint D10). The signing key must be set wherever the app is deployed;
    # locally an unset key means a random one per process (sessions end on restart).
    jwt_secret: SecretStr | None = None
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=14, ge=1, le=90)
    # Self-service sign-up creates a tenant and its owner. Never available when deployed.
    allow_registration: bool = True

    @model_validator(mode="after")
    def _deployed_requirements(self) -> "Settings":
        if self.is_deployed:
            if self.jwt_secret is None or len(self.jwt_secret.get_secret_value()) < 32:
                raise ValueError("OM_JWT_SECRET must be set (32+ characters) when deployed")
            self.allow_registration = False
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.is_deployed

    @property
    def is_deployed(self) -> bool:
        return self.environment in {Environment.STAGING, Environment.PROD}

    @property
    def show_docs(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_deployed


@lru_cache
def get_settings() -> Settings:
    return Settings()
