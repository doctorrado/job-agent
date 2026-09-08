"""Deterministic extraction: pull structured signals out of a Job's raw
text (title, description, location) — skills mentioned, seniority level,
years of experience required, remote/location scope, US work-authorization
requirements, and (best-effort) a monthly COP salary figure.

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
_JUNIOR_WORDS = re.compile(r"\b(junior|jr\.?|entry[- ]level|graduate|intern(ship)?|associate)\b", re.I)
_YEARS_PATTERN = re.compile(r"(\d+)\s*(?:\+|-\s*\d+)?\s*years?", re.I)

_US_AUTH_PATTERN = re.compile(
    r"(must be authorized to work in the united states|"
    r"u\.?s\.?\s*citizenship|"
    r"authorized to work in the u\.?s\.?\b|"
    r"legally authorized to work in the united states|"
    r"work authorization in the (united states|u\.?s\.?)\b)",
    re.I,
)

_COLOMBIA_WORDS = re.compile(r"\b(colombia|medell[ií]n|bogot[aá])\b", re.I)
_REMOTE_ANYWHERE_WORDS = re.compile(
    r"\b(remote[- ]anywhere|worldwide|global|anywhere in the world)\b", re.I
)
_LATAM_WORDS = re.compile(r"\b(latam|latin america)\b", re.I)

_SALARY_COP_PATTERN = re.compile(r"(?:cop\s*\$?|\$)\s*([\d.,]{4,})", re.I)


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
    """Best-effort monthly COP figure from salary_raw or the description.
    Assumes a disclosed COP figure is monthly (the Colombian convention).
    Returns None when nothing parseable is found — treat as undisclosed,
    never as zero or as a failure."""
    text = f"{job.salary_raw or ''} {job.description}"
    match = _SALARY_COP_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[.,]", "", match.group(1))
    return int(digits) if digits.isdigit() else None
