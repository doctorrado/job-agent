from jobagent.models.job import Job
from jobagent.pipeline.fetch import fetch_all, run_fetch
from jobagent.sources.base import JobSource
from jobagent.storage.db import make_session_factory
from jobagent.storage.repository import JobRepository


class _FakeSource(JobSource):
    def __init__(self, name: str, jobs: list[Job], fails: bool = False) -> None:
        self.name = name
        self._jobs = jobs
        self._fails = fails

    def fetch(self) -> list[Job]:
        if self._fails:
            raise RuntimeError("network down")
        return self._jobs


def _job(source_job_id: str, title: str = "Data Analyst") -> Job:
    return Job(
        source="fake",
        source_job_id=source_job_id,
        url=f"https://example.com/{source_job_id}",
        title=title,
        company="Acme",
    )


def test_fetch_all_skips_a_failing_source():
    good = _FakeSource("good", [_job("1")])
    bad = _FakeSource("bad", [], fails=True)
    assert len(fetch_all([good, bad])) == 1


def test_run_fetch_stores_new_jobs_and_reports_stats(tmp_path):
    session = make_session_factory(tmp_path / "test.db")()
    repository = JobRepository(session)
    source = _FakeSource("fake", [_job("1"), _job("2")])

    stats = run_fetch(repository, sources=[source])

    assert stats == {
        "sources_run": 1,
        "raw_fetched": 2,
        "after_dedupe": 2,
        "new": 2,
        "already_seen": 0,
    }
    assert repository.count() == 2


def test_run_fetch_second_run_finds_nothing_new(tmp_path):
    session = make_session_factory(tmp_path / "test.db")()
    repository = JobRepository(session)
    source = _FakeSource("fake", [_job("1")])

    run_fetch(repository, sources=[source])
    stats = run_fetch(repository, sources=[source])

    assert stats["new"] == 0
    assert stats["already_seen"] == 1
