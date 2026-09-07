from pathlib import Path

import pytest

from jobagent.models.job import RemoteType, Seniority
from jobagent.sources.file_source import FileSource

FIXTURE = Path(__file__).parent / "fixtures" / "sample_jobs.json"


def test_file_source_fetch_returns_jobs():
    jobs = FileSource(FIXTURE).fetch()

    assert len(jobs) == 2
    first = jobs[0]
    assert first.title == "Data Analyst"
    assert first.company == "Acme Manufacturing"
    assert first.remote_type is RemoteType.hybrid
    assert first.seniority is Seniority.junior
    assert first.dedupe_key == "file:1"


def test_file_source_fetch_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        FileSource(missing).fetch()
