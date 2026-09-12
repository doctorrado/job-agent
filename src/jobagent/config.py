"""Runtime settings — configuration that comes from the environment, not from
a file you hand-edit. Loaded from real environment variables and, for local
dev, a `.env` file. pydantic-settings does both automatically and validates
the types (e.g. rejects a non-numeric log level if we typed one)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from jobagent.models.profile import Contact, History, Profile


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    profile_path: Path = Path("config/profile.yaml")
    db_path: Path = Path("data/jobs.db")
    resumes_dir: Path = Path("private/resumes")
    postings_dir: Path = Path("private/postings")
    contact_path: Path = Path("private/contact.yaml")
    history_path: Path = Path("private/history.yaml")

    anthropic_api_key: str | None = None
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    jooble_api_key: str | None = None
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    # Shared password for the candidate accounts every ATS makes you create.
    # Lives in .env and is never printed — the resolver says where it is.
    application_password: str | None = None




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


def load_contact(path: Path | None = None) -> Contact | None:
    """Contact details for form filling, or None if the file does not exist.

    Optional on purpose: everything else in this project works without it,
    and it holds the most sensitive data in the repo.
    """
    settings = get_settings()
    target = path or settings.contact_path
    if not target.is_file():
        return None
    return Contact(**yaml.safe_load(target.read_text(encoding="utf-8")))


def load_history(path: Path | None = None) -> History | None:
    """Work history and education, or None if the file does not exist."""
    target = path or get_settings().history_path
    if not target.is_file():
        return None
    return History(**yaml.safe_load(target.read_text(encoding="utf-8")))
