"""Runtime settings — configuration that comes from the environment, not from
a file you hand-edit. Loaded from real environment variables and, for local
dev, a `.env` file. pydantic-settings does both automatically and validates
the types (e.g. rejects a non-numeric log level if we typed one)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    profile_path: Path = Path("config/profile.yaml")

    anthropic_api_key: str | None = None
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process and cache them."""
    return Settings()
