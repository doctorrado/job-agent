"""Deduplication: decide whether jobs fetched together actually represent
the same posting.

Two layers, deliberately simple:
  - exact: same source, same source_job_id (re-fetching the same posting)
  - cross-source: same company + title + location once normalized (two
    different sources reporting the same real-world posting)

No fuzzy/similarity matching here on purpose — normalized-exact catches the
realistic case; upgrade only if real postings are shown to slip through it.

Limitation: this only dedupes within one fetch run (an in-memory list). A
posting reappearing under a different source next week needs the storage
layer to catch too — that's the next piece, not this one.
"""

from __future__ import annotations

import re

from jobagent.models.job import Job
from jobagent.pipeline.extract import strip_accents

# Legal-entity suffixes carry no identity: Jooble lists "IQVIA, Inc." where a
# LinkedIn alert says "IQVIA", and the pair survived dedupe into a review
# batch as two separate jobs. Accents differ across sources for the same
# reason ("Bogota, D.C." vs "Bogota, D.C.").
_COMPANY_SUFFIX = re.compile(
    r"[\s,]+(inc|llc|ltd|limited|corp|corporation|co|plc|gmbh|"
    r"s\.?a\.?s?|s\.?a\.?s\.?|sas|srl|s\.?r\.?l|bv|nv|ag|oy|ab)\.?$",
    re.I,
)


def normalize_text(value: str | None) -> str:
    """Lowercase, strip accents and collapse whitespace so "Bogota, D.C.",
    "Bogota, D.C. " and "BOGOTA, D.C." all compare equal."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", strip_accents(value).strip().lower())


def normalize_company(value: str | None) -> str:
    """Company identity with legal-entity suffixes removed."""
    name = normalize_text(value)
    previous = None
    while name != previous:  # "Foo S.A.S. Ltd" needs more than one pass
        previous = name
        name = _COMPANY_SUFFIX.sub("", name).strip()
    return name


def posting_identity(company: str | None, title: str | None) -> str:
    """Identity of a real-world opening, ignoring source and location.

    Coarser than fuzzy_key on purpose. A verdict is a judgment about a JOB,
    not about a row: Twilio's BI Analyst 2 arrives from both a LinkedIn alert
    and Twilio's Greenhouse board with different source_job_ids, and judging
    one used to leave the other sitting in the queue. 35 such groups existed
    across 3,985 jobs, 13 of them already half-judged.
    """
    return f"{normalize_company(company)}|{normalize_text(title)}"


def fuzzy_key(job: Job) -> str:
    """Cross-source identity: same company + title + location, normalized."""
    company = normalize_company(job.company)
    title = normalize_text(job.title)
    location = normalize_text(job.location)
    return f"{company}|{title}|{location}"

def deduplicate(jobs: list[Job]) -> list[Job]:
    """Return one Job per real posting. First occurrence wins."""
    seen_exact: set[str] = set()
    seen_fuzzy: set[str] = set()
    result: list[Job] = []
    for job in jobs:
        exact = job.dedupe_key
        fuzzy = fuzzy_key(job)
        if exact in seen_exact or fuzzy in seen_fuzzy:
            continue
        seen_exact.add(exact)
        seen_fuzzy.add(fuzzy)
        result.append(job)
    return result
