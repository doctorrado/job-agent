"""Fetches every current opening from companies known to run a public
Greenhouse or Lever job board.

Unlike the other sources, coverage here isn't fixed by some API's limits —
it's exactly as wide as config/companies.yaml. Growing that list (by hand,
or via a periodic discovery search) directly grows what this source finds.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import httpx
import yaml

from jobagent.logging import get_logger
from jobagent.models.job import Job
from jobagent.sources.base import JobSource

log = get_logger(__name__)


class CompanyBoardsSource(JobSource):
    name = "company_boards"

    def __init__(self, companies_path: Path, client: httpx.Client | None = None) -> None:
        self.companies_path = companies_path
        self._client = client or httpx.Client(timeout=10.0)

    def fetch(self) -> list[Job]:
        companies = yaml.safe_load(self.companies_path.read_text(encoding="utf-8")) or []
        jobs: list[Job] = []
        for entry in companies:
            fetcher = _FETCHERS.get(entry["platform"])
            if fetcher is None:
                continue  # unknown platform in the config — skip, don't crash the whole run
            try:
                jobs.extend(fetcher(self._client, entry["slug"], entry["name"]))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                # One unreachable or slow board must not cost us the other 20.
                # fetch_all() already skips a failing SOURCE; this is the same
                # rule one level down. A single company timing out used to
                # abort the whole run, leaving ~1,900 stored jobs unrefreshed.
                log.warning(
                    "company_board_failed",
                    company=entry["name"],
                    platform=entry["platform"],
                    error=str(exc),
                )
        return jobs


def _fetch_greenhouse(client: httpx.Client, slug: str, company: str) -> list[Job]:
    r = client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}
    )
    r.raise_for_status()
    return [
        Job(
            source="greenhouse",
            source_job_id=str(j["id"]),
            url=j["absolute_url"],
            title=j["title"],
            company=company,
            location=(j.get("location") or {}).get("name"),
            description=j.get("content", ""),
            posted_date=_parse_iso_date(j.get("updated_at")),
        )
        for j in r.json().get("jobs", [])
    ]


def _fetch_lever(client: httpx.Client, slug: str, company: str) -> list[Job]:
    r = client.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    r.raise_for_status()
    return [
        Job(
            source="lever",
            source_job_id=p["id"],
            url=p["hostedUrl"],
            title=p["text"],
            company=company,
            location=(p.get("categories") or {}).get("location"),
            description=p.get("descriptionPlain", ""),
            employment_type=(p.get("categories") or {}).get("commitment"),
            posted_date=_parse_epoch_ms(p.get("createdAt")),
        )
        for p in r.json()
    ]


def _fetch_ashby(client: httpx.Client, slug: str, company: str) -> list[Job]:
    """Ashby's public job-board API. Returns descriptionPlain, so postings
    arrive as clean text with no HTML stripping needed."""
    r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    r.raise_for_status()
    return [
        Job(
            source="ashby",
            source_job_id=j["id"],
            url=j["jobUrl"],
            title=j["title"],
            company=company,
            location=j.get("location"),
            description=j.get("descriptionPlain", ""),
            employment_type=j.get("employmentType"),
            posted_date=_parse_iso_date(j.get("publishedAt")),
        )
        for j in r.json().get("jobs", [])
        if j.get("isListed", True)
    ]


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
}


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _parse_epoch_ms(value: int | None) -> date | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000).date()
