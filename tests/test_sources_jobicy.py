import httpx

from jobagent.sources.jobicy_source import JobicySource

SAMPLE_RESPONSE = {
    "jobs": [
        {
            "id": 152755,
            "url": "https://jobicy.com/jobs/152755-data-product-analyst",
            "jobTitle": "Data Product Analyst, Corporate",
            "companyName": "YipitData",
            "jobGeo": "USA",
            "jobLevel": "Senior",
            "jobType": ["Full-Time"],
            "jobExcerpt": "About Us...",
            "jobDescription": "<p>Full description...</p>",
            "pubDate": "2026-09-07T16:40:09+00:00",
            "salaryMin": None,
            "salaryMax": 150000,
            "salaryCurrency": "USD",
            "salaryPeriod": "yearly",
        }
    ]
}


def _fake_transport(request: httpx.Request) -> httpx.Response:
    assert request.url.params["tag"] == "data"
    return httpx.Response(200, json=SAMPLE_RESPONSE)


def test_jobicy_source_maps_fields():
    fake_client = httpx.Client(transport=httpx.MockTransport(_fake_transport))
    jobs = JobicySource(tag="data", client=fake_client).fetch()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jobicy"
    assert job.source_job_id == "152755"
    assert job.company == "YipitData"
    assert job.remote_type.value == "remote"
    assert job.employment_type == "Full-Time"
    assert job.salary_raw == "$150,000 USD annually"
    assert job.posted_date.isoformat() == "2026-09-07"
