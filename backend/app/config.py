"""Application configuration loaded from environment variables (and an optional .env file)."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    @field_validator("redis_url", "build_sha", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
