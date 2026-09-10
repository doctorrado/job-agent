from jobagent.models.job import Job
from jobagent.pipeline.dedupe import deduplicate


def _job(source, source_job_id, title="Data Analyst", company="Acme", location="Remote"):
    return Job(
        source=source,
        source_job_id=source_job_id,
        url=f"https://example.com/{source}/{source_job_id}",
        title=title,
        company=company,
        location=location,
    )


def test_exact_duplicate_within_same_source_is_removed():
    jobs = [_job("greenhouse", "1"), _job("greenhouse", "1")]
    assert len(deduplicate(jobs)) == 1


def test_same_posting_from_two_sources_collapses_to_one():
    jobs = [
        _job("greenhouse", "1", title="Data Analyst ", company="Acme"),
        _job("file", "manual-1", title="data analyst", company="ACME"),
    ]
    assert len(deduplicate(jobs)) == 1


def test_different_postings_are_both_kept():
    jobs = [
        _job("greenhouse", "1", title="Data Analyst", company="Acme"),
        _job("greenhouse", "2", title="Data Engineer", company="Acme"),
    ]
    assert len(deduplicate(jobs)) == 2


def test_company_suffixes_and_accents_do_not_split_one_posting():
    """Jooble says "IQVIA, Inc." / "Bogota, D.C."; a LinkedIn alert says
    "IQVIA" / "Bogota, D.C.". The pair reached a review batch as two jobs."""
    from jobagent.pipeline.dedupe import normalize_company, normalize_text

    assert normalize_company("IQVIA, Inc.") == normalize_company("IQVIA")
    assert normalize_company("Auxis LLC") == normalize_company("Auxis")
    assert normalize_company("ScotiaGBS Colombia S.A.S.") == normalize_company(
        "ScotiaGBS Colombia"
    )
    assert normalize_text("Bogotá, D.C.") == normalize_text("Bogota, D.C.")


def test_suffix_stripping_does_not_eat_a_real_name():
    from jobagent.pipeline.dedupe import normalize_company

    assert normalize_company("Cisco") == "cisco"
    assert normalize_company("Incube Metrics") == "incube metrics"
    assert normalize_company("Coca Cola") == "coca cola"
