import httpx

from jobagent.sources.adzuna_source import AdzunaSource

SAMPLE_RESPONSE = {
    "results": [
        {
            "id": "5874459777",
            "title": "Data Analyst - Remote",
            "company": {"display_name": "Acme Corp"},
            "location": {"display_name": "Remote, US"},
            "description": "We are looking for a data analyst...",
            "contract_time": "full_time",
            "created": "2026-09-07T16:17:09Z",
            "redirect_url": "https://www.adzuna.com/land/ad/5874459777",
            "salary_min": 80000,
            "salary_max": 90000,
            "salary_is_predicted": "0",
        }
    ]
}


def _fake_transport(request: httpx.Request) -> httpx.Response:
    assert request.url.params["app_id"] == "test-id"
    assert request.url.params["app_key"] == "test-key"
    return httpx.Response(200, json=SAMPLE_RESPONSE)


def test_adzuna_source_maps_fields():
    fake_client = httpx.Client(transport=httpx.MockTransport(_fake_transport))
    jobs = AdzunaSource(app_id="test-id", app_key="test-key", client=fake_client).fetch()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "adzuna"
    assert job.company == "Acme Corp"
    assert job.employment_type == "full_time"
    assert job.salary_raw == "$80,000 USD annually"
    assert job.posted_date.isoformat() == "2026-09-07"


def test_adzuna_source_ignores_predicted_salary():
    response = {
        "results": [
            {
                "id": "1",
                "title": "Data Analyst",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Remote"},
                "description": "desc",
                "created": "2026-09-07T16:17:09Z",
                "redirect_url": "https://example.com/1",
                "salary_min": 80000,
                "salary_is_predicted": "1",
            }
        ]
    }

    def fake_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    fake_client = httpx.Client(transport=httpx.MockTransport(fake_transport))
    jobs = AdzunaSource(app_id="x", app_key="y", client=fake_client).fetch()
    assert jobs[0].salary_raw is None
