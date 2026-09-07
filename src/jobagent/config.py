"""Runtime settings — configuration that comes from the environment, not from
a file you hand-edit. Loaded from real environment variables and, for local
dev, a `.env` file. pydantic-settings does both automatically and validates
the types (e.g. rejects a non-numeric log level if we typed one)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from jobagent.models.profile import Profile


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


def load_profile(path: Path) -> Profile:
    """Load and validate your profile YAML into a Profile object."""
    if not path.exists():
        raise FileNotFoundError(
            f"Profile file not found: {path}. Copy config/profile.example.yaml "
            f"to {path} and edit it."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Profile.model_validate(data)
