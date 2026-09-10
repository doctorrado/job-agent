"""The only place that translates between Job (what sources and the
pipeline work with) and JobRecord (what's actually in the database)."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from jobagent.models.job import Job, RemoteType, Seniority
from jobagent.pipeline.extract import strip_accents
from jobagent.storage.orm import Application, ApplicationAnswer, JobRecord, JobReview


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


STATUSES = (
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "ghosted",
)

# Questions that must never be banked. CLAUDE.md forbids auto-answering
# demographic and sensitive questions, so the bank refuses to hold them at
# all — an empty table cannot tempt a future form-filler into using it.
# Prefixes, not whole words: "disab" must match "disability", so these
# deliberately have no trailing \b. A trailing boundary silently matched
# nothing and let every EEO question through.
_SENSITIVE = re.compile(
    r"\b(rac(e|ial)|ethnic|gender|sex|disab|veteran|military|"
    r"religio|age\b|date of birth|marital|pregnan|citizenship status|"
    r"criminal|conviction|felony|salary history|protected class)",
    re.I,
)


def normalise_question(question: str) -> str:
    """Collapse phrasings of the same question to one key.

    "Years of experience with Python?" and "How many years of Python
    experience do you have" should hit the same banked answer, so filler
    words and punctuation come out and the remaining words are sorted.
    """
    text = strip_accents(question).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    stop = {
        "how", "many", "much", "do", "you", "have", "the", "a", "an", "of",
        "with", "in", "your", "please", "what", "is", "are", "and", "to",
        "for", "any", "years", "year", "experience",
    }
    words = sorted({w for w in text.split() if w and w not in stop})
    return " ".join(words)


def is_sensitive(question: str) -> bool:
    """True for demographic/EEO questions, which are never banked."""
    return _SENSITIVE.search(question or "") is not None


class ApplicationRepository:
    """Applications actually sent, and what happened after."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        source: str,
        source_job_id: str,
        company: str,
        title: str,
        url: str = "",
        resume_used: str | None = None,
        applied_via: str | None = None,
        notes: str = "",
    ) -> bool:
        """Log an application. False if this job was already applied to —
        re-applying to the same posting is a mistake, not an update."""
        existing = (
            self.session.query(Application)
            .filter_by(source=source, source_job_id=source_job_id)
            .one_or_none()
        )
        if existing is not None:
            return False
        self.session.add(
            Application(
                source=source,
                source_job_id=source_job_id,
                company=company,
                title=title,
                url=url,
                resume_used=resume_used,
                applied_via=applied_via,
                notes=notes,
            )
        )
        self.session.commit()
        return True

    def set_status(self, source: str, source_job_id: str, status: str, note: str = "") -> bool:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
        row = (
            self.session.query(Application)
            .filter_by(source=source, source_job_id=source_job_id)
            .one_or_none()
        )
        if row is None:
            return False
        row.status = status
        row.updated_at = datetime.now()
        if note:
            row.notes = f"{row.notes}\n{note}".strip()
        self.session.commit()
        return True

    def all(self, status: str | None = None) -> list[Application]:
        query = self.session.query(Application)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(Application.applied_at.desc()).all()

    def applied_keys(self) -> set[str]:
        """"source:source_job_id" for everything already applied to, so the
        rest of the pipeline can stop surfacing them."""
        return {f"{a.source}:{a.source_job_id}" for a in self.session.query(Application).all()}

    def count(self) -> int:
        return self.session.query(Application).count()


class AnswerRepository:
    """The answer bank: what forms asked, and what Andres answered."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def remember(self, question: str, answer: str, category: str = "other") -> bool:
        """Bank one answer. False if refused (sensitive) or already known."""
        if is_sensitive(question):
            return False
        key = normalise_question(question)
        if not key:
            return False
        existing = self.session.query(ApplicationAnswer).filter_by(question_key=key).one_or_none()
        if existing is not None:
            existing.times_used += 1
            existing.updated_at = datetime.now()
            self.session.commit()
            return False
        self.session.add(
            ApplicationAnswer(
                question_key=key, question=question, answer=answer, category=category
            )
        )
        self.session.commit()
        return True

    def lookup(self, question: str) -> ApplicationAnswer | None:
        return (
            self.session.query(ApplicationAnswer)
            .filter_by(question_key=normalise_question(question))
            .one_or_none()
        )

    def search(self, text: str = "") -> list[ApplicationAnswer]:
        rows = self.session.query(ApplicationAnswer).order_by(
            ApplicationAnswer.times_used.desc()
        )
        if not text:
            return rows.all()
        needle = text.lower()
        return [r for r in rows.all() if needle in r.question.lower() or needle in r.answer.lower()]

    def count(self) -> int:
        return self.session.query(ApplicationAnswer).count()
