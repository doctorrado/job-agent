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
    requires_internship,
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

# Multiplicative penalties for facts that undermine a posting wholesale rather
# than costing it points in one category. Real measurement on 2,700 stored jobs
# drove these: with category points alone, 36 of the top 100 were on-site roles
# in cities Andres cannot work in (Doha, Bengaluru, San Francisco) sitting at
# 80/100 — ABOVE genuine Bogota roles at 75 — and 12 more matched none of his
# target roles at all. Losing 15 of 20 location points was not enough; the
# other four categories carried them. See NOTES.md (2026-09-10).
_NO_SKILLS_DAMPING = 0.5
_WRONG_PLACE_DAMPING = 0.6
_OFF_ROLE_DAMPING = 0.6
# ...but an unfamiliar title is only weak evidence, and real skill overlap
# outvotes it. "Dev Python (PySpark/Airflow/PostgreSQL) - Remoto" in Colombia
# matches no role keyword yet names three of Andres's skills in the title
# alone; damping it to 36 was wrong. Half the skill cap is the threshold.
_OFF_ROLE_SKILL_OVERRIDE = _SKILL_MATCH_CAP // 2



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
    damping_reasons: list[str] = field(default_factory=list)

    @property
    def dampened(self) -> bool:
        return bool(self.damping_reasons)



def score_job(job: Job, profile: Profile) -> ScoreResult:
    if requires_us_work_authorization(job) and not profile.work_authorization.us_authorized:
        return ScoreResult(
            job=job, eligible=False, ineligible_reason="requires US work authorization"
        )

    if requires_internship(job):
        return ScoreResult(
            job=job, eligible=False, ineligible_reason="internship / student placement"
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

    relevance = role_relevance(job, profile)
    breakdown = {
        "skills": skill_points,
        "role": _ROLE_POINTS[relevance],
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

    damping = 1.0
    reasons: list[str] = []
    if not skills and has_description:
        damping *= _NO_SKILLS_DAMPING
        reasons.append("no skill overlap")
    if remote_scope(job) == "other":
        damping *= _WRONG_PLACE_DAMPING
        reasons.append("located where you cannot work")
    if relevance == "none" and len(skills) < _OFF_ROLE_SKILL_OVERRIDE:
        damping *= _OFF_ROLE_DAMPING
        reasons.append("not a target role")
    total = round(sum(breakdown.values()) * damping)

    return ScoreResult(
        job=job,
        eligible=True,
        total=total,
        breakdown=breakdown,
        matched_skills=skills,
        salary_monthly_cop=salary_cop,
        salary_hourly_usd=hourly_usd,
        damping_reasons=reasons,
    )



def _score_seniority(job: Job, profile: Profile) -> int:
    points = 20
    years = years_required(job)
    if years is not None:
        distance = max(0, years - profile.max_years_experience)
        points = 20 - distance * 6
    if detect_seniority(job) is Seniority.senior:
        # Checked even when a years figure was found. Previously the years
        # branch returned early, so Artefact's "Senior Data Engineer" saying
        # "3+ years" scored a full 20/20 — 29 senior-titled postings did.
        points = min(points, 4)
    return max(0, points)
    

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