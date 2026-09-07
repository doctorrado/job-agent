import httpx

from jobagent.sources.remotive_source import RemotiveSource

SAMPLE_RESPONSE = {
    "job-count": 1,
    "jobs": [
        {
            "id": 123,
            "url": "https://remotive.com/remote-jobs/data/data-analyst-123",
            "title": "Data Analyst",
            "company_name": "Acme Analytics ",
            "category": "Data and Analytics",
            "tags": ["sql", "python"],
            "job_type": "full_time",
            "publication_date": "2026-01-15T10:00:00",
            "candidate_required_location": "LATAM",
            "salary": "",
            "description": "<p>Analyze data.</p>",
        }
    ],
}


def _fake_transport(request: httpx.Request) -> httpx.Response:
    # Prove OUR code sends the right query param — independent of whether
    # Remotive's server actually honors it (we just learned it might not!).
    assert request.url.params["category"] == "data"
    return httpx.Response(200, json=SAMPLE_RESPONSE)


def test_remotive_source_maps_fields():
    fake_client = httpx.Client(transport=httpx.MockTransport(_fake_transport))
    jobs = RemotiveSource(category="data", client=fake_client).fetch()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "remotive"
    assert job.source_job_id == "123"
    assert job.title == "Data Analyst"
    assert job.company == "Acme Analytics"  # trailing space stripped
    assert job.remote_type.value == "remote"
    assert job.employment_type == "full_time"
    assert job.posted_date.isoformat() == "2026-01-15"
