from jobagent.models.job import Job
from jobagent.storage.db import make_session_factory
from jobagent.storage.repository import JobRepository


def _job(source_job_id="1", title="Data Analyst"):
    return Job(
        source="file",
        source_job_id=source_job_id,
        url=f"https://example.com/{source_job_id}",
        title=title,
        company="Acme",
    )


def test_upsert_new_job_returns_true(tmp_path):
    session = make_session_factory(tmp_path / "test.db")()
    repo = JobRepository(session)
    assert repo.upsert(_job()) is True
    assert repo.count() == 1


def test_upsert_existing_job_returns_false_and_does_not_duplicate(tmp_path):
    session = make_session_factory(tmp_path / "test.db")()
    repo = JobRepository(session)
    repo.upsert(_job())
    assert repo.upsert(_job()) is False
    assert repo.count() == 1


def test_all_round_trips_job_fields(tmp_path):
    session = make_session_factory(tmp_path / "test.db")()
    repo = JobRepository(session)
    repo.upsert(_job(title="Data Engineer"))
    [stored] = repo.all()
    assert stored.title == "Data Engineer"
    assert stored.company == "Acme"
