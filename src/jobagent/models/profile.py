"""Shape of your job-search preferences, loaded from config/profile.yaml.

Kept separate from Settings (config.py): this is data about you and your job
search, not secrets, and it's fine for it to live in a plain YAML file you
hand-edit."""
from __future__ import annotations

from pydantic import BaseModel, Field


class WorkAuthorization(BaseModel):
    us_authorized: bool = False
    eu_authorized: bool = False
    needs_sponsorship: bool = True


class LocationPreferences(BaseModel):
    # Free-text location names/phrases you'd accept, e.g. "Colombia"
    allowed: list[str] = Field(default_factory=list)
    # Cities to weigh higher when scoring, e.g. "Medellín"
    preferred_cities: list[str] = Field(default_factory=list)
    # Which flavors of "remote" count as OK for you
    remote_scopes_ok: list[str] = Field(default_factory=list)


class SalaryExpectation(BaseModel):
    currency: str = "COP"
    target_monthly: int | None = None
    minimum_monthly: int | None = None
    minimum_hourly_usd: float | None = None

class RoleKeywords(BaseModel):
    """Short phrases matched against a job title, in any language you search
    in. Kept separate from target_roles/secondary_roles (the human-readable
    role names) because matching needs partial phrases — "data engineer"
    matches "Data Engineer II (Python/PySpark)" where the full role name
    "Junior Data Engineer" would not."""

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    name: str
    # Tier 1 — strongest fit
    target_roles: list[str]
    # Tier 2 — worth considering, evaluated by responsibilities not just title
    secondary_roles: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    max_years_experience: int = 3
    # Skills you can genuinely back up with real experience. The resume
    # system will never claim a skill that isn't in this list.
    skills: list[str] = Field(default_factory=list)
    # Years per technology, lowercased keys. "How many years of X?" is the
    # most common variable question on an application form, and it is the one
    # thing the answer bank cannot derive from anything else. Absent from
    # here means "not stated" — never "zero" and never a guess.
    skill_years: dict[str, float] = Field(default_factory=dict)
    preferred_industries: list[str] = Field(default_factory=list)
    locations: LocationPreferences = Field(default_factory=LocationPreferences)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    salary: SalaryExpectation = Field(default_factory=SalaryExpectation)
    role_keywords: RoleKeywords = Field(default_factory=RoleKeywords)

