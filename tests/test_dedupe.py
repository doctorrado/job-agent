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
