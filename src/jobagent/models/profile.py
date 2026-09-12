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



class Contact(BaseModel):
    """Contact details for filling application forms. Lives in private/.

    `currently_resides_in_colombia` is deliberately separate from the address.
    An address field is a contact detail and a Bogota one is legitimate for
    someone relocating there; "do you currently reside in Colombia" is a
    factual question and gets the true answer. Conflating the two would be
    the resume-fabrication rule broken in a different file.
    """

    full_name: str
    email: str
    phone: str = ""
    phone_alt: str = ""
    linkedin: str = ""
    github: str = ""
    address_line: str = ""
    postal_code: str = ""
    city: str = ""
    region: str = ""
    country: str = ""
    currently_resides_in_colombia: bool = True
    relocation_note: str = ""

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0] if self.full_name else ""

    @property
    def last_name(self) -> str:
        """Everything after the first name — Spanish naming commonly uses two
        surnames, so this must not assume a single trailing word."""
        parts = self.full_name.split()
        return " ".join(parts[1:]) if len(parts) > 1 else ""

    @property
    def full_address(self) -> str:
        parts = [self.address_line, self.postal_code, self.city, self.region, self.country]
        return ", ".join(p for p in parts if p)


class Employment(BaseModel):
    job_title: str = ""
    company: str = ""
    via: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    current: bool = False
    description: str = ""


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    field_of_study: str = ""
    emphasis: str = ""
    minor: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    gpa: str = ""


class Certification(BaseModel):
    name: str = ""
    issuer: str = ""
    date: str = ""
    note: str = ""


class History(BaseModel):
    """Work history and education, structured for application forms.

    Every Workday form asks for these and they existed only as prose, so 7
    required fields on a real IQVIA application came back "not known".
    Job titles are deliberately allowed to be blank: candidate_profile.md
    never recorded them, and inventing one is the fabrication rule broken.
    """

    employment: list[Employment] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
