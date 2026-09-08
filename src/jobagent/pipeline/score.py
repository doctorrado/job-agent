"""Deterministic match scoring: combine extraction signals with the
candidate's Profile into a transparent 0-100 breakdown.

Two hard filters run first and exclude a job outright — not score
categories, the non-negotiables from CLAUDE.md:
  - a detected US work-authorization requirement, when the candidate
    isn't US-authorized
  - a salary that's clearly disclosed and below the candidate's floor

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
    salary_monthly_cop,
    years_required,
)

# Matching this many of the candidate's skills already maxes the category —
# no single posting will ever mention all of them.
_SKILL_MATCH_CAP = 6


@dataclass
class ScoreResult:
    job: Job
    eligible: bool
    ineligible_reason: str | None = None
    total: int = 0
    breakdown: dict[str, int] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    salary_monthly_cop: int | None = None


def score_job(job: Job, profile: Profile) -> ScoreResult:
    if requires_us_work_authorization(job) and not profile.work_authorization.us_authorized:
        return ScoreResult(job=job, eligible=False, ineligible_reason="requires US work authorization")

    salary = salary_monthly_cop(job)
    floor = profile.salary.minimum_monthly
    if salary is not None and floor is not None and salary < floor:
        return ScoreResult(
            job=job,
            eligible=False,
            ineligible_reason=f"disclosed salary ({salary:,} COP/mo) is below your floor ({floor:,})",
        )

    skills = matched_skills(job, profile)
    skill_points = round(min(len(skills), _SKILL_MATCH_CAP) / _SKILL_MATCH_CAP * 40)

    breakdown = {
        "skills": skill_points,
        "seniority": _score_seniority(job, profile),
        "location": _score_location(job, profile),
        "salary": _score_salary(salary, profile),
    }
    return ScoreResult(
        job=job,
        eligible=True,
        total=sum(breakdown.values()),
        breakdown=breakdown,
        matched_skills=skills,
        salary_monthly_cop=salary,
    )


def _score_seniority(job: Job, profile: Profile) -> int:
    years = years_required(job)
    if years is not None:
        distance = max(0, years - profile.max_years_experience)
        return max(0, 25 - distance * 8)
    if detect_seniority(job) is Seniority.senior:
        return 5  # heavy penalty, not a hard exclude — title labels are noisy
    return 25  # junior/entry/mid/unknown: no reliable reason to penalize


def _score_location(job: Job, profile: Profile) -> int:
    scope = remote_scope(job)
    if scope == "remote_from_colombia" or scope in profile.locations.remote_scopes_ok:
        return 20
    if scope == "unknown":
        return 12
    return 5


def _score_salary(salary: int | None, profile: Profile) -> int:
    if salary is None:
        return 8  # undisclosed — neutral, never assumed to meet or miss target
    target = profile.salary.target_monthly
    if target and salary >= target:
        return 15
    return 12  # meets the floor (already checked above) but under target
