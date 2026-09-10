import httpx

from jobagent.discovery.ats_probe import (
    Candidate,
    extract_jobs,
    is_probeable,
    looks_real,
    probe_company,
    slug_candidates,
)


def test_slug_candidates_are_few_and_obvious():
    assert slug_candidates("Wizeline") == ["wizeline"]
    assert slug_candidates("GFT Technologies LATAM") == [
        "gfttechnologieslatam",
        "gft-technologies-latam",
        "gft",
    ]
    # accents must not leak into a URL path
    assert "bogota" in slug_candidates("Bogotá Tech")[0]


def test_job_boards_and_parse_artefacts_are_not_probed():
    assert is_probeable("Wizeline")
    assert not is_probeable("elempleo")
    assert not is_probeable("Empresa Confidencial")
    assert not is_probeable(
        "You’ll receive notifications when new jobs are posted that match your search"
    )


def test_trial_accounts_are_rejected():
    """Accenture and EY both answer 200 on Recruitee with this exact
    placeholder; four such false positives were found on live data."""
    assert not looks_real([("sales executive", ""), ("Senior Marketer (Sample)", "")])
    assert not looks_real([("DevOps Engineer", "")])  # one unrelated job
    assert looks_real([(t, "") for t in ("Data Analyst", "AI Eng", "Backend", "Sales")])


def test_extract_jobs_handles_each_platform_and_bad_shapes():
    greenhouse = {"jobs": [{"title": "A", "location": {"name": "Bogota"}}]}
    assert extract_jobs("greenhouse", greenhouse) == [("A", "Bogota")]
    assert extract_jobs("lever", [{"text": "B", "categories": {"location": "Lima"}}]) == [
        ("B", "Lima")
    ]
    assert extract_jobs("recruitee", {"offers": [{"title": "D", "location": "Quito"}]}) == [
        ("D", "Quito")
    ]
    assert extract_jobs("greenhouse", {"unexpected": 1}) == []
    assert extract_jobs("lever", None) == []


def test_first_word_slug_needs_location_corroboration():
    """"Inter Rapidisimo" (Bogota) matched Inter, a Brazilian bank with 136
    jobs and none in Colombia. "Experian Spanish Latam" really does have
    Colombia openings, so it should still be found."""
    from jobagent.discovery.ats_probe import corroborated

    brazilian = [(f"Analista {i}", "Sao Paulo, Brazil") for i in range(9)]
    assert not corroborated({"Bogota, D.C., Colombia"}, brazilian)

    mixed = brazilian + [("Data Analyst", "Bogota, Colombia")]
    assert corroborated({"Bogota, D.C., Colombia"}, mixed)
    assert not corroborated(set(), mixed)


def test_full_name_slug_skips_corroboration():
    def handler(request: httpx.Request) -> httpx.Response:
        if "greenhouse" in str(request.url) and "/acme/" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {"title": f"R{i}", "location": {"name": "Berlin"}} for i in range(9)
                    ]
                },
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # single-word company -> full-name slug, accepted despite no location overlap
    found = probe_company(client, "Acme", known_locations={"Bogota, Colombia"})
    assert found is not None and found.slug == "acme"


def test_probe_returns_the_first_real_board():
    def handler(request: httpx.Request) -> httpx.Response:
        if "greenhouse" in str(request.url):
            return httpx.Response(200, json={"jobs": [{"title": "Senior Marketer (Sample)"}]})
        if "ashby" in str(request.url):
            return httpx.Response(
                200, json={"jobs": [{"title": f"Role {i}"} for i in range(9)]}
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    found = probe_company(client, "Acme")
    assert isinstance(found, Candidate)
    assert found.platform == "ashby"
    assert found.job_count == 9


def test_probe_returns_none_when_nothing_is_real():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert probe_company(client, "Acme") is None


def test_a_platform_that_rate_limits_is_dropped_for_the_run():
    """A live 120-company run had Workable answering 429 to everything by the
    end. Once a platform says stop, stop asking it."""
    from jobagent.discovery.ats_probe import ProbeState

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "workable" in str(request.url):
            return httpx.Response(429)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    state = ProbeState()
    for name in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon"):
        probe_company(client, name, state)

    assert "workable" in state.disabled
    workable_calls = [c for c in calls if "workable" in c]
    assert len(workable_calls) == 3  # stopped at _MAX_RATE_LIMITS
