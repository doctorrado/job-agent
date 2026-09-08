"""Adzuna job source adapter.

Adzuna aggregates postings across many boards. Requires free credentials
(ADZUNA_APP_ID/ADZUNA_APP_KEY in .env — developer.adzuna.com). Doesn't cover
Colombia, so this is scoped to the US market with a remote-friendly query;
existing work-authorization/location scoring decides real fit, not this
adapter.

Known limitation: Adzuna's search API truncates descriptions to a short
snippet rather than the full posting, so extraction (skills, years
required, work-auth phrases) sees less text here than for other sources.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from jobagent.models.job import Job
from jobagent.sources.base import JobSource

API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


class AdzunaSource(JobSource):
    name = "adzuna"

    def __init__(
        self,
        app_id: str,
        app_key: str,
        query: str = "data analyst remote",
        country: str = "us",
        results_per_page: int = 50,
        client: httpx.Client | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.query = query
        self.country = country
        self.results_per_page = results_per_page
        self._client = client or httpx.Client(timeout=15.0)

    def fetch(self) -> list[Job]:
        response = self._client.get(
            API_URL.format(country=self.country),
            params={
                "app_id": self.app_id,
                "app_key": self.app_key,
                "results_per_page": self.results_per_page,
                "what": self.query,
                "content-type": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        return [_to_job(raw) for raw in payload.get("results", [])]


def _to_job(raw: dict) -> Job:
    return Job(
        source="adzuna",
        source_job_id=str(raw["id"]),
        url=raw["redirect_url"],
        title=raw["title"],
        company=raw.get("company", {}).get("display_name", "Unknown"),
        location=raw.get("location", {}).get("display_name"),
        description=raw.get("description", ""),
        employment_type=raw.get("contract_time"),
        salary_raw=_salary_raw(raw),
        posted_date=_parse_date(raw.get("created")),
    )


def _salary_raw(raw: dict) -> str | None:
    """Adzuna normalizes salary to an annualized USD figure across its
    whole database, and flags real-vs-estimated via salary_is_predicted.
    Only the real, disclosed figure is trusted — same "never assume"
    principle as everywhere else in this pipeline."""
    if raw.get("salary_is_predicted") != "0":
        return None
    amount = raw.get("salary_min")
    if not amount:
        return None
    return f"${amount:,.0f} USD annually"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
