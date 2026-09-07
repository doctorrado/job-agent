"""The normalized Job shape every source adapter must produce."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class RemoteType(StrEnum):
    on_site = "on_site"
    hybrid = "hybrid"
    remote = "remote"
    unknown = "unknown"


class Seniority(StrEnum):
    intern = "intern"
    entry = "entry"
    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"
    unknown = "unknown"


class Job(BaseModel):
    # Identity
    source: str  # "remotive", "adzuna", "file"
    source_job_id: str  # id as given by that source
    url: HttpUrl

    # Core content
    title: str
    company: str
    location: str | None = None
    remote_type: RemoteType = RemoteType.unknown
    description: str = ""

    # Enrichment — filled in during Phase 3 analysis, optional for now
    seniority: Seniority = Seniority.unknown
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    salary_raw: str | None = None
    employment_type: str | None = None

    # Provenance
    posted_date: date | None = None
    collected_at: datetime = Field(default_factory=datetime.now)

    @property
    def dedupe_key(self) -> str:
        """Exact-match key for dedupe within one source."""
        return f"{self.source}:{self.source_job_id}"
