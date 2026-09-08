"""Shape of your job-search preferences, loaded from config/profile.yaml.

Kept separate from Settings (config.py): this is data about you and your job
search, not secrets, and it's fine for it to live in a plain YAML file you
hand-edit."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkAuthorization(BaseModel):
    # Countries/regions you can legally work in with no visa or sponsorship
    authorized_countries: list[str] = Field(default_factory=lambda: ["Colombia"])
    # Whether to even surface roles elsewhere that would require sponsorship
    open_to_sponsorship: bool = False


class LocationPreferences(BaseModel):
    # Free-text location names/phrases you'd accept, e.g. "Colombia"
    allowed: list[str] = Field(default_factory=list)
    # Cities to weigh higher when scoring, e.g. "Medellín"
    preferred_cities: list[str] = Field(default_factory=list)
    # Which flavors of "remote" count as OK for you
    remote_scopes_ok: list[str] = Field(default_factory=list)


salary:
  currency: COP
  target_monthly: 5000000
  minimum_monthly: 4000000


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
    preferred_industries: list[str] = Field(default_factory=list)
    locations: LocationPreferences = Field(default_factory=LocationPreferences)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    salary: SalaryExpectation = Field(default_factory=SalaryExpectation)
