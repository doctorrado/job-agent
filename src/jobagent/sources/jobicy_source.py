"""Jobicy job source adapter.

Jobicy (https://jobicy.com) publishes a public JSON API of remote jobs with
real working filters — verified live: an invalid tag correctly returns zero
results, unlike Remotive/RemoteOK which ignore filters entirely — and, for
many postings, structured salary data. No key required.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from jobagent.models.job import Job, RemoteType
from jobagent.sources.base import JobSource

API_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicySource(JobSource):
    name = "jobicy"

    def __init__(
        self,
        tag: str | None = None,
        count: int = 50,
        client: httpx.Client | None = None,
    ) -> None:
        self.tag = tag
        self.count = count
        self._client = client or httpx.Client(timeout=10.0)

    def fetch(self) -> list[Job]:
        params = {"count": self.count}
        if self.tag:
            params["tag"] = self.tag
        response = self._client.get(API_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        return [_to_job(raw) for raw in payload.get("jobs", [])]


def _to_job(raw: dict) -> Job:
    return Job(
        source="jobicy",
        source_job_id=str(raw["id"]),
        url=raw["url"],
        title=raw["jobTitle"],
        company=raw["companyName"],
        location=raw.get("jobGeo"),
        remote_type=RemoteType.remote,
        description=raw.get("jobDescription") or raw.get("jobExcerpt", ""),
        employment_type=", ".join(raw.get("jobType", [])) or None,
        salary_raw=_salary_raw(raw),
        posted_date=_parse_date(raw.get("pubDate")),
    )


def _salary_raw(raw: dict) -> str | None:
    """Reuses the USD annual/hourly regex already in pipeline/extract.py
    instead of a second structured-salary code path — Jobicy gives clean
    numbers, so this just formats them the way that parser expects."""
    amount = raw.get("salaryMin") or raw.get("salaryMax")
    currency = raw.get("salaryCurrency")
    period = raw.get("salaryPeriod")
    if not amount or currency != "USD":
        return None
    if period == "yearly":
        return f"${amount:,} USD annually"
    if period == "hourly":
        return f"${amount} USD/hr"
    return None  # unrecognized period — don't guess


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()
