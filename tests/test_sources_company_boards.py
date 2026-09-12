import httpx

from jobagent.sources.company_boards_source import (
    CompanyBoardsSource,
    _fetch_recruitee,
    _fetch_smartrecruiters,
)

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


def test_one_failing_board_does_not_lose_the_others(tmp_path):
    """A slow or unreachable company must not abort the whole run."""
    config = tmp_path / "companies.yaml"
    config.write_text(
        "- name: Broken\n  platform: greenhouse\n  slug: broken\n"
        "- name: Working\n  platform: greenhouse\n  slug: working\n",
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "broken" in str(request.url):
            raise httpx.ReadTimeout("too slow", request=request)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Data Analyst",
                        "absolute_url": "https://example.com/1",
                        "location": {"name": "Bogota, Colombia"},
                        "updated_at": "2026-09-01T00:00:00Z",
                        "content": "SQL and Python",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = CompanyBoardsSource(config, client=client).fetch()
    assert [j.company for j in jobs] == ["Working"]


def test_recruitee_board_is_read_with_descriptions():
    """Four companies sat in companies.yaml fetching nothing because the
    probe can write a platform this module could not read."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "offers": [
                    {
                        "id": 7,
                        "title": "Data Analyst",
                        "careers_url": "https://acme.recruitee.com/o/data-analyst",
                        "location": "Bogota, Colombia",
                        "description": "Build dashboards.",
                        "requirements": "SQL and Python.",
                        # Recruitee's format, which fromisoformat rejects
                        "published_at": "2026-09-10 09:36:16 UTC",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = _fetch_recruitee(client, "acme", "Acme")
    assert len(jobs) == 1
    assert "SQL and Python" in jobs[0].description
    assert jobs[0].posted_date is not None


def test_an_unparseable_date_does_not_lose_the_job():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "offers": [
                    {
                        "id": 8,
                        "title": "Data Analyst",
                        "careers_url": "https://acme.recruitee.com/o/x",
                        "location": "Bogota",
                        "description": "x",
                        "requirements": "y",
                        "published_at": "last Tuesday",
                    }
                ]
            },
        )

    jobs = _fetch_recruitee(httpx.Client(transport=httpx.MockTransport(handler)), "acme", "Acme")
    assert len(jobs) == 1 and jobs[0].posted_date is None


def test_smartrecruiters_pulls_the_body_from_the_detail_call():
    """Its list response carries no description at all — unlike every other
    platform here, the body needs a per-posting request."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "abc",
                            "name": "Data Analyst",
                            "location": {"city": "Bogotá", "country": "co"},
                            "releasedDate": "2026-09-01T00:00:00.000Z",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "jobAd": {
                    "sections": {
                        "jobDescription": {"text": "Build reports with SQL."},
                        "qualifications": {"text": "Python required."},
                    }
                }
            },
        )

    jobs = _fetch_smartrecruiters(
        httpx.Client(transport=httpx.MockTransport(handler)), "acme", "Acme"
    )
    assert len(jobs) == 1
    assert "SQL" in jobs[0].description and "Python" in jobs[0].description
    assert "Bogotá" in jobs[0].location
