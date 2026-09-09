"""The only place that translates between Job (what sources and the
pipeline work with) and JobRecord (what's actually in the database)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from jobagent.models.job import Job, RemoteType, Seniority
from jobagent.storage.orm import JobRecord, JobReview


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, job: Job) -> bool:
        """Store a job if we haven't seen it, or refresh last_seen_at if we
        have. Returns True if this was newly inserted."""
        existing = (
            self.session.query(JobRecord)
            .filter_by(source=job.source, source_job_id=job.source_job_id)
            .one_or_none()
        )
        if existing is not None:
            existing.last_seen_at = datetime.now()
            self.session.commit()
            return False

        record = JobRecord(
            source=job.source,
            source_job_id=job.source_job_id,
            url=str(job.url),
            title=job.title,
            company=job.company,
            location=job.location,
            remote_type=job.remote_type.value,
            description=job.description,
            seniority=job.seniority.value,
            employment_type=job.employment_type,
            salary_raw=job.salary_raw,
            posted_date=job.posted_date,
        )
        self.session.add(record)
        self.session.commit()
        return True

    def all(self) -> list[Job]:
        return [_to_job(r) for r in self.session.query(JobRecord).all()]

    def count(self) -> int:
        return self.session.query(JobRecord).count()


def _to_job(record: JobRecord) -> Job:
    return Job(
        source=record.source,
        source_job_id=record.source_job_id,
        url=record.url,
        title=record.title,
        company=record.company,
        location=record.location,
        remote_type=RemoteType(record.remote_type),
        description=record.description,
        seniority=Seniority(record.seniority),
        employment_type=record.employment_type,
        salary_raw=record.salary_raw,
        posted_date=record.posted_date,
        collected_at=record.first_seen_at,
    )


VERDICTS = ("worth_applying", "unsure", "not_a_fit")


class ReviewRepository:
    """Stores one verdict per posting, so nothing is ever judged twice."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def verdicts(self) -> dict[str, str]:
        """Every recorded verdict, keyed by "source:source_job_id" to match
        Job.dedupe_key so callers can filter without a join."""
        return {
            f"{r.source}:{r.source_job_id}": r.verdict
            for r in self.session.query(JobReview).all()
        }

    def record(
        self,
        source: str,
        source_job_id: str,
        verdict: str,
        reasoning: str = "",
        reviewed_by: str = "claude",
    ) -> bool:
        """Store a verdict. Returns True if newly recorded, False if this
        posting had already been reviewed (existing verdicts are never
        silently overwritten — that would defeat "review once")."""
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}; expected one of {VERDICTS}")
        existing = (
            self.session.query(JobReview)
            .filter_by(source=source, source_job_id=source_job_id)
            .one_or_none()
        )
        if existing is not None:
            return False
        self.session.add(
            JobReview(
                source=source,
                source_job_id=source_job_id,
                verdict=verdict,
                reasoning=reasoning,
                reviewed_by=reviewed_by,
            )
        )
        self.session.commit()
        return True

    def count(self) -> int:
        return self.session.query(JobReview).count()
