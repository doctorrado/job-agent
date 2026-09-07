"""Remotive job source adapter.

Remotive (https://remotive.com) publishes a small public JSON API of fully
remote job postings — no API key required. Every posting there is remote by
definition, so remote_type is always RemoteType.remote: a known fact about
the source, not something we infer per job.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from jobagent.models.job import Job, RemoteType
from jobagent.sources.base import JobSource

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    name = "remotive"

    def __init__(
        self,
        category: str | None = None,
        search: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        # category/search let us filter server-side, e.g. category="data".
        self.category = category
        self.search = search
        # Accept a client instead of building one here — see write-up above.
        self._client = client or httpx.Client(timeout=10.0)

    def fetch(self) -> list[Job]:
        params = {
            k: v for k, v in {"category": self.category, "search": self.search}.items() if v
        }
        response = self._client.get(API_URL, params=params)
        response.raise_for_status()  # raise loudly on a 4xx/5xx instead of returning nothing
        payload = response.json()
        return [_to_job(raw) for raw in payload["jobs"]]


def _to_job(raw: dict) -> Job:
    return Job(
        source="remotive",
        source_job_id=str(raw["id"]),
        url=raw["url"],
        title=raw["title"],
        company=raw["company_name"].strip(),
        location=raw.get("candidate_required_location"),
        remote_type=RemoteType.remote,
        description=raw.get("description", ""),
        employment_type=raw.get("job_type"),
        salary_raw=raw.get("salary") or None,
        posted_date=_parse_date(raw.get("publication_date")),
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()
