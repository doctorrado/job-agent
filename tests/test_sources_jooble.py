import httpx

from jobagent.sources.jooble_source import JoobleSource, read_usage

SAMPLE_RESPONSE = {
    "jobs": [
        {
            "id": 3568162060718868843,
            "title": "Data Analyst",
            "location": "Medellín, Antioquia",
            "snippet": "Looking for a data analyst...",
            "salary": "",
            "company": "INGEPSY",
            "link": "https://co.jooble.org/jdp/3568162060718868843",
            "updated": "2026-09-07T00:00:00.0000000",
        }
    ]
}


def _fake_transport(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=SAMPLE_RESPONSE)


def test_jooble_source_maps_fields_and_tracks_usage(tmp_path):
    usage_path = tmp_path / "usage.json"
    fake_client = httpx.Client(transport=httpx.MockTransport(_fake_transport))
    source = JoobleSource(
        api_key="x", keywords="data analyst", client=fake_client, usage_path=usage_path
    )

    jobs = source.fetch()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jooble"
    assert job.company == "INGEPSY"
    assert job.posted_date.isoformat() == "2026-09-07"
    assert read_usage(usage_path) == 1
