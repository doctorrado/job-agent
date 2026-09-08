"""Jooble job source adapter.

Jooble aggregates jobs from many boards and covers Colombia specifically —
needs a key from the country-specific domain (co.jooble.org/api/about for
Colombia; a key from the plain jooble.org page only covers the US).

Deliberately NOT part of jobagent fetch's routine active_sources() — the
free tier is a hard LIFETIME cap of 500 calls total, not a monthly quota,
so this only runs via the explicit `jobagent jooble-search` command, with
a persisted call counter so remaining budget is always visible.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from jobagent.models.job import Job
from jobagent.sources.base import JobSource

USAGE_PATH = Path("data/jooble_usage.json")
LIFETIME_LIMIT = 500


class JoobleBudgetExceeded(Exception):
    pass


class JoobleSource(JobSource):
    name = "jooble"

    def __init__(
        self,
        api_key: str,
        keywords: str,
        location: str = "Colombia",
        client: httpx.Client | None = None,
        usage_path: Path = USAGE_PATH,
    ) -> None:
        self.api_key = api_key
        self.keywords = keywords
        self.location = location
        self._client = client or httpx.Client(timeout=15.0)
        self.usage_path = usage_path

    def fetch(self) -> list[Job]:
        used = read_usage(self.usage_path)
        if used >= LIFETIME_LIMIT:
            raise JoobleBudgetExceeded(f"Jooble's {LIFETIME_LIMIT}-call lifetime limit is used up.")
        response = self._client.post(
            f"https://co.jooble.org/api/{self.api_key}",
            json={"keywords": self.keywords, "location": self.location},
        )
        response.raise_for_status()
        write_usage(self.usage_path, used + 1)
        payload = response.json()
        return [_to_job(raw) for raw in payload.get("jobs", [])]


def _to_job(raw: dict) -> Job:
    return Job(
        source="jooble",
        source_job_id=str(raw["id"]),
        url=raw["link"],
        title=raw["title"],
        company=raw.get("company") or "Unknown",
        location=raw.get("location"),
        description=raw.get("snippet", ""),
        salary_raw=raw.get("salary") or None,
        posted_date=_parse_date(raw.get("updated")),
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value.split("T")[0])


def read_usage(path: Path = USAGE_PATH) -> int:
    if not path.exists():
        return 0
    return json.loads(path.read_text(encoding="utf-8")).get("calls_used", 0)


def write_usage(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calls_used": count}), encoding="utf-8")
