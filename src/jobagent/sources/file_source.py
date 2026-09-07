"""Reads jobs from a local JSON file.

Two purposes: it's a source we can test the rest of the pipeline against
without network flakiness, and later it's a manual escape hatch for adding
a job you found by hand and want tracked like any other.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobagent.models.job import Job
from jobagent.sources.base import JobSource


class FileSource(JobSource):
    name = "file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch(self) -> list[Job]:
        """The file holds a JSON list of objects already shaped like Job
        (same fields as the model — see tests/fixtures/sample_jobs.json)."""
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Job.model_validate(item) for item in raw]
