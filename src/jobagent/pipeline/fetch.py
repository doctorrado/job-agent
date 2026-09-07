"""Orchestrates fetching from every active source, deduplicating the
results, and persisting them.

"Active" sources are whichever ones have what they need available:
CompanyBoardsSource runs if config/companies.yaml exists, FileSource runs
if data/manual_jobs.json exists, RemotiveSource always runs (needs nothing).
A source that fails (e.g. network error) is logged and skipped rather than
aborting the whole run — one flaky source shouldn't block the others.
"""

from __future__ import annotations

from pathlib import Path

from jobagent.logging import get_logger
from jobagent.models.job import Job
from jobagent.pipeline.dedupe import deduplicate
from jobagent.sources.base import JobSource
from jobagent.sources.company_boards_source import CompanyBoardsSource
from jobagent.sources.file_source import FileSource
from jobagent.sources.remotive_source import RemotiveSource
from jobagent.storage.repository import JobRepository

log = get_logger(__name__)

MANUAL_JOBS_PATH = Path("data/manual_jobs.json")
COMPANIES_PATH = Path("config/companies.yaml")


def active_sources() -> list[JobSource]:
    sources: list[JobSource] = [RemotiveSource()]
    if COMPANIES_PATH.exists():
        sources.append(CompanyBoardsSource(COMPANIES_PATH))
    if MANUAL_JOBS_PATH.exists():
        sources.append(FileSource(MANUAL_JOBS_PATH))
    return sources


def fetch_all(sources: list[JobSource]) -> list[Job]:
    jobs: list[Job] = []
    for source in sources:
        try:
            fetched = source.fetch()
        except Exception:
            log.warning("source_fetch_failed", source=source.name, exc_info=True)
            continue
        log.info("source_fetched", source=source.name, count=len(fetched))
        jobs.extend(fetched)
    return jobs


def run_fetch(repository: JobRepository, sources: list[JobSource] | None = None) -> dict[str, int]:
    if sources is None:
        sources = active_sources()
    raw_jobs = fetch_all(sources)
    deduped = deduplicate(raw_jobs)

    new_count = sum(1 for job in deduped if repository.upsert(job))

    return {
        "sources_run": len(sources),
        "raw_fetched": len(raw_jobs),
        "after_dedupe": len(deduped),
        "new": new_count,
        "already_seen": len(deduped) - new_count,
    }
