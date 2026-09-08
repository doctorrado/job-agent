"""Deterministic extraction: pull structured signals out of a Job's raw
text (title, description, location) — skills mentioned, seniority level,
years of experience required, remote/location scope, US work-authorization
requirements, and (best-effort) salary figures in COP or USD.

Computed fresh every time `jobagent rank` runs, not stored — it's cheap,
pure text analysis with nothing worth caching.

No LLM calls here on purpose — see NOTES.md for why, and for the "review
ambiguous fits with Claude" idea this deliberately doesn't try to solve.
"""

from __future__ import annotations

import re

from jobagent.models.job import Job, Seniority
from jobagent.models.profile import Profile

_SENIOR_WORDS = re.compile(r"\b(senior|sr\.?|lead|principal|staff|director|head of)\b", re.I)
_JUNIOR_WORDS = re.compile(
    r"\b(junior|jr\.?|entry[- ]level|graduate|intern(ship)?|associate)\b", re.I
)
_YEARS_PATTERN = re.compile(r"(\d+)\s*(?:\+|-\s*\d+)?\s*years?", re.I)

# Deliberately specific, actionable phrases only — NOT a bare "united states"
# mention, which would also match harmless company-background sentences like
# "Sezzle operates in the United States and Canada." Real examples that drove
# these patterns are in NOTES.md (2026-09-08).
_US_AUTH_PATTERN = re.compile(
    r"(must be authorized to work in the united states|"
    r"u\.?s\.?\s*citizenship|"
    r"authorized to work in the u\.?s\.?\b|"
    r"legally authorized to work in the united states|"
    r"work authorization in the (united states|u\.?s\.?)\b|"
    r"must (?:have )?resid(?:e|ed) (?:in|within) the united states|"
    r"(?:fully )?remote(?:ly)? within the united states)",
    re.I,
)

_COLOMBIA_WORDS = re.compile(r"\b(colombia|medell[ií]n|bogot[aá])\b", re.I)
_REMOTE_ANYWHERE_WORDS = re.compile(
    r"\b(remote[- ]anywhere|worldwide|global|anywhere in the world)\b", re.I
)
_LATAM_WORDS = re.compile(r"\b(latam|latin america)\b", re.I)

# Requires an explicit "COP" mention — a bare "$" is ambiguous (we've seen
# USD annual ranges, CAD/USD ranges, even per-word/per-task freelance rates
# all use "$"), and guessing the currency wrong is worse than not parsing at
# all. See NOTES.md (2026-09-08) for the real false positives this replaced.
_SALARY_COP_PATTERN = re.compile(r"cop\s*\$?\s*([\d.,]{4,})", re.I)

# USD: only an explicit hourly or explicit annual figure — never guessed from
# a bare "$" range with no period keyword, and never converted from a
# per-word/per-task/per-image piecework rate (depends on how fast someone
# works, not something to estimate).
_SALARY_USD_HOURLY_PATTERN = re.compile(
    r"\$\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:usd)?\s*(?:/\s*hr\b|/\s*hour\b|per hour|hourly)", re.I
)
_SALARY_USD_ANNUAL_PATTERN = re.compile(
    r"\$\s*([\d,]{4,})\s*(?:usd)?\s*(?:annually|per year|/\s*yr\b|/\s*year\b)", re.I
)
_FULL_TIME_HOURS_PER_YEAR = 2080  # 40 hr/week x 52 weeks, for annual -> hourly comparison


def matched_skills(job: Job, profile: Profile) -> list[str]:
    """Which of the candidate's own skills are mentioned in this posting."""
    text = f"{job.title} {job.description}".lower()
    return [
        skill for skill in profile.skills if re.search(rf"\b{re.escape(skill.lower())}\b", text)
    ]


def years_required(job: Job) -> int | None:
    """Lowest number of years mentioned near an experience requirement."""
    match = _YEARS_PATTERN.search(job.description)
    return int(match.group(1)) if match else None


def detect_seniority(job: Job) -> Seniority:
    """Keyword-based seniority from the title first, description second.
    Deliberately coarse — see NOTES.md."""
    for haystack in (job.title, job.description):
        if _SENIOR_WORDS.search(haystack):
            return Seniority.senior
        if _JUNIOR_WORDS.search(haystack):
            return Seniority.junior
    return Seniority.unknown


def requires_us_work_authorization(job: Job) -> bool:
    return bool(_US_AUTH_PATTERN.search(job.description))


def remote_scope(job: Job) -> str:
    """One of: remote_from_colombia, remote_latam, remote_anywhere, other, unknown."""
    text = f"{job.location or ''} {job.description}"
    if _COLOMBIA_WORDS.search(text):
        return "remote_from_colombia"
    if _REMOTE_ANYWHERE_WORDS.search(text):
        return "remote_anywhere"
    if _LATAM_WORDS.search(text):
        return "remote_latam"
    if job.remote_type.value == "remote":
        return "unknown"
    return "other"


def salary_monthly_cop(job: Job) -> int | None:
    """Best-effort monthly COP figure — only when the text explicitly says
    COP (assumes a disclosed COP figure is monthly, the Colombian
    convention). Returns None for anything else, including other
    currencies — never guess a currency or a period."""
    text = f"{job.salary_raw or ''} {job.description}"
    match = _SALARY_COP_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[.,]", "", match.group(1))
    return int(digits) if digits.isdigit() else None


def salary_hourly_usd(job: Job) -> float | None:
    """Best-effort hourly USD rate — from an explicit hourly rate, or an
    explicit annual figure converted at a standard 2,080 hr/year. Ignores
    per-word/per-task/per-image piecework rates on purpose: converting
    those to an hourly equivalent depends on how fast someone works."""
    text = f"{job.salary_raw or ''} {job.description}"
    hourly_match = _SALARY_USD_HOURLY_PATTERN.search(text)
    if hourly_match:
        return float(hourly_match.group(1))
    annual_match = _SALARY_USD_ANNUAL_PATTERN.search(text)
    if annual_match:
        annual = float(re.sub(",", "", annual_match.group(1)))
        return annual / _FULL_TIME_HOURS_PER_YEAR
    return None
