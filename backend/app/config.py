"""Application configuration loaded from environment variables (and an optional .env file)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_JWT_SECRET = "atlas-local-development-signing-key-not-for-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        # The repository-root .env is shared with Docker Compose; backend/.env may override it.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ATLAS Global Bank"
    environment: Literal["development", "test", "staging", "production"] = "development"
    build_sha: str | None = Field(
        default=None, description="Git commit of the running build, if supplied by the deploy."
    )

    database_url: str = "postgresql+psycopg://atlas:atlas@localhost:5432/atlas"
    database_pool_size: int = 5
    database_connect_timeout_seconds: int = 3

    # Redis is optional in Phase 1. When unset, the platform reports it as "disabled".
    redis_url: str | None = None

    # NoDecode: parse comma-separated env values ourselves instead of requiring JSON.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Signing key for access tokens. The default is for local development only and is
    # rejected in staging and production.
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    access_token_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)

    # Background jobs (Phase 14). "inline": the API runs the jobs it queues itself (no
    # worker process needed); "worker": dedicated `python -m app.cli worker` processes do.
    jobs_execution: Literal["inline", "worker"] = "inline"
    # A running job whose worker has not sent a heartbeat for this long is taken back.
    jobs_stale_after_seconds: int = Field(default=300, ge=30)

    # Simulation history archives (Phase 15): compressed COPY files, one directory per run.
    # The API and every worker must see the same directory (a shared volume in Docker).
    simulation_archive_dir: Path = Path("var/simulation-archive")

    # Observability (Phase 15). Statements slower than this are logged and kept in the
    # slow-query log; 0 turns the log off.
    slow_query_ms: int = Field(default=250, ge=0)
    # Bearer token for the Prometheus endpoint `/api/metrics`; unset means it is disabled.
    metrics_token: SecretStr | None = None

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        # Accept a comma-separated string as well as a JSON list.
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        # An empty ATLAS_JWT_SECRET (as in .env.example) must never become an empty signing
        # key; it means "unset", which falls back to the development key (rejected in
        # staging/production by the check below).
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEV_JWT_SECRET
        return value

    @field_validator("redis_url", "build_sha", "metrics_token", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _require_real_secret_outside_development(self) -> "Settings":
        if self.environment in {"staging", "production"}:
            secret = self.jwt_secret.get_secret_value()
            if secret == DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError(
                    "ATLAS_JWT_SECRET must be set to a random value of at least 32 characters "
                    f"in the {self.environment} environment."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
