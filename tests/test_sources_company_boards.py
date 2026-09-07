import httpx

from jobagent.sources.company_boards_source import CompanyBoardsSource

GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "id": 111,
            "title": "Data Analyst",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
            "location": {"name": "Remote"},
            "content": "<p>Analyze data.</p>",
            "updated_at": "2026-01-10T12:00:00Z",
        }
    ]
}

LEVER_RESPONSE = [
    {
        "id": "abc-123",
        "text": "Data Engineer",
        "hostedUrl": "https://jobs.lever.co/beta/abc-123",
        "categories": {"location": "Remote", "commitment": "Full-time"},
        "descriptionPlain": "Build pipelines.",
        "createdAt": 1768000000000,
    }
]


def _fake_transport(request: httpx.Request) -> httpx.Response:
    if "greenhouse" in str(request.url):
        return httpx.Response(200, json=GREENHOUSE_RESPONSE)
    if "lever" in str(request.url):
        return httpx.Response(200, json=LEVER_RESPONSE)
    return httpx.Response(404)


def test_company_boards_source_maps_both_platforms(tmp_path):
    companies_file = tmp_path / "companies.yaml"
    companies_file.write_text(
        "- name: Acme\n  platform: greenhouse\n  slug: acme\n"
        "- name: Beta\n  platform: lever\n  slug: beta\n",
        encoding="utf-8",
    )
    fake_client = httpx.Client(transport=httpx.MockTransport(_fake_transport))
    jobs = CompanyBoardsSource(companies_file, client=fake_client).fetch()

    assert len(jobs) == 2
    gh_job = next(j for j in jobs if j.source == "greenhouse")
    assert gh_job.company == "Acme"
    assert gh_job.title == "Data Analyst"
    assert gh_job.location == "Remote"

    lv_job = next(j for j in jobs if j.source == "lever")
    assert lv_job.company == "Beta"
    assert lv_job.title == "Data Engineer"
    assert lv_job.employment_type == "Full-time"
