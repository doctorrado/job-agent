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


def normalize_text(value: str | None) -> str:
    """Lowercase and collapse whitespace so "Data Analyst " and
    "data analyst" compare equal."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def fuzzy_key(job: Job) -> str:
    """Cross-source identity: same company + title + location, normalized."""
    return f"{normalize_text(job.company)}|{normalize_text(job.title)}|{normalize_text(job.location)}"


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
