import pytest
from pydantic import ValidationError

from jobagent.models.job import Job, RemoteType, Seniority


def test_job_minimal_valid():
    job = Job(
        source="file",
        source_job_id="1",
        url="https://example.com/j/1",
        title="Data Analyst",
        company="Acme",
    )
    assert job.remote_type is RemoteType.unknown
    assert job.seniority is Seniority.unknown
    assert job.dedupe_key == "file:1"


def test_job_missing_required_field():
    with pytest.raises(ValidationError):
        Job(source="file", source_job_id="1", title="x", company="y")  # no url
