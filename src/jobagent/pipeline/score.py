"""Deterministic match scoring: combine extraction signals with the
candidate's Profile into a transparent 0-100 breakdown.

Hard filters run first and exclude a job outright — not score categories,
the non-negotiables from CLAUDE.md:
  - a detected US work-authorization requirement, when the candidate
    isn't US-authorized
  - a salary that's clearly disclosed (COP or USD) and below the
    candidate's floor for that currency

Everything else is soft-scored. Industry and a required-vs-preferred
skill split are deliberately left out — see NOTES.md (2026-09-08) for why.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobagent.models.job import Job, Seniority
from jobagent.models.profile import Profile
from jobagent.pipeline.extract import (
    detect_seniority,
    matched_skills,
    remote_scope,
    requires_us_work_authorization,
    role_relevance,
    salary_hourly_usd,
    salary_monthly_cop,
    years_required,
)

# Below this, treat a job as having no real description to search.
_MIN_DESCRIPTION_CHARS = 200


# Matching this many of the candidate's skills already maxes the category —
# no single posting will ever mention all of them.
_SKILL_MATCH_CAP = 6

_ROLE_POINTS = {"primary": 20, "secondary": 12, "none": 0}



@dataclass
class ScoreResult:
    job: Job
    eligible: bool
    ineligible_reason: str | None = None
    total: int = 0
    breakdown: dict[str, int] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    salary_monthly_cop: int | None = None
    salary_hourly_usd: float | None = None
    salary_hourly_usd: float | None = None
    dampened: bool = False



def score_job(job: Job, profile: Profile) -> ScoreResult:
    if requires_us_work_authorization(job) and not profile.work_authorization.us_authorized:
        return ScoreResult(
            job=job, eligible=False, ineligible_reason="requires US work authorization"
        )

    salary_cop = salary_monthly_cop(job)
    cop_floor = profile.salary.minimum_monthly
    if salary_cop is not None and cop_floor is not None and salary_cop < cop_floor:
        reason = f"disclosed salary ({salary_cop:,} COP/mo) is below your floor ({cop_floor:,})"
        return ScoreResult(job=job, eligible=False, ineligible_reason=reason)

    hourly_usd = salary_hourly_usd(job)
    hourly_floor = profile.salary.minimum_hourly_usd
    if hourly_usd is not None and hourly_floor is not None and hourly_usd < hourly_floor:
        reason = (
            f"disclosed rate (~${hourly_usd:.2f}/hr) is below your ${hourly_floor:.0f}/hr floor"
        )
        return ScoreResult(job=job, eligible=False, ineligible_reason=reason)

    skills = matched_skills(job, profile)
    skill_points = round(min(len(skills), _SKILL_MATCH_CAP) / _SKILL_MATCH_CAP * 30)

    breakdown = {
        "skills": skill_points,
        "role": _ROLE_POINTS[role_relevance(job, profile)],
        "seniority": _score_seniority(job, profile),
        "location": _score_location(job, profile),
        "salary": _score_salary(salary_cop, hourly_usd, profile),
    }
     # Zero skill overlap is only evidence of a poor fit when there WAS a real
    # description to search. LinkedIn alert emails carry no description at all
    # (title/company/location only), so "no skills matched" there means "no
    # information", not "bad match" — dampening those would bury exactly the
    # Colombia-based roles this project exists to find. Same "never assume"
    # principle as undisclosed salary.
    has_description = len(job.description.strip()) >= _MIN_DESCRIPTION_CHARS
    dampening = 0.5 if (not skills and has_description) else 1.0
    total = round(sum(breakdown.values()) * dampening)

    return ScoreResult(
        job=job,
        eligible=True,
        total=total,
        breakdown=breakdown,
        matched_skills=skills,
        salary_monthly_cop=salary_cop,
        salary_hourly_usd=hourly_usd,
        dampened=dampening < 1.0,
    )



def _score_seniority(job: Job, profile: Profile) -> int:
    years = years_required(job)
    if years is not None:
        distance = max(0, years - profile.max_years_experience)
        return max(0, 20 - distance * 6)
    if detect_seniority(job) is Seniority.senior:
        return 4  # heavy penalty, not a hard exclude — title labels are noisy
    return 20  # junior/entry/mid/unknown: no reliable reason to penalize
    

def _score_location(job: Job, profile: Profile) -> int:
    scope = remote_scope(job)
    if scope == "remote_from_colombia" or scope in profile.locations.remote_scopes_ok:
        return 20
    if scope == "unknown":
        return 12
    return 5


def _score_salary(salary_cop: int | None, hourly_usd: float | None, profile: Profile) -> int:
    if salary_cop is None and hourly_usd is None:
        return 5  # undisclosed — neutral, never assumed to meet or miss target
    if salary_cop is not None:
        target = profile.salary.target_monthly
        return 10 if target and salary_cop >= target else 8
    return 9  # cleared the USD hourly floor above; no separate target yet