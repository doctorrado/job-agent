"""SQLAlchemy ORM model for persisted jobs — the DB-row shape, separate
from jobagent.models.job.Job (the in-memory/validation shape used by
sources and the pipeline). Only the storage layer touches this class."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from jobagent.storage.db import Base


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_source_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_job_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    remote_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    seniority: Mapped[str] = mapped_column(String(20))
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    salary_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class JobReview(Base):
    """A one-time verdict on whether a posting is worth applying to.

    Deliberately its own table rather than columns on JobRecord: a review is a
    different fact from the posting itself, and keeping it separate means a
    re-fetched posting never loses its verdict — which is what makes
    "review once, ever" actually hold. (Practically it also matters that
    SQLAlchemy's create_all can add a new table but cannot ALTER an existing
    one, and this project has no migration tool.)
    """

    __tablename__ = "job_reviews"
    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_review_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_job_id: Mapped[str] = mapped_column(String(200))
    verdict: Mapped[str] = mapped_column(String(20))
    reasoning: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(20), default="claude")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Application(Base):
    """One application Andres actually sent, and what happened afterwards.

    Separate from JobReview for the same reason JobReview is separate from
    JobRecord: "is this worth applying to" and "what happened after I applied"
    are different facts with different lifetimes. A verdict is written once;
    a status changes for months.
    """

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_application_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_job_id: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default="applied")
    resume_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Which system the application was actually submitted through — often not
    # the same as where the job was listed. A Greenhouse listing can hand you
    # off to Workday to apply, and knowing which is what makes form-filling
    # automatable later.
    applied_via: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ApplicationAnswer(Base):
    """A question an application asked, and the answer Andres gave.

    The point is reuse: forms ask the same things endlessly ("years with
    Python?", "do you require sponsorship?", "notice period?"), and every
    answer captured by hand now is one the form-filler will not have to ask
    for later. This table IS the training data for Phase 7 — without it that
    phase starts from nothing.

    Demographic and EEO questions are never stored here. That is deliberate,
    not an oversight: CLAUDE.md forbids auto-answering them, so banking them
    would only create the temptation.
    """

    __tablename__ = "application_answers"
    __table_args__ = (UniqueConstraint("question_key", name="uq_answer_question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Normalised form of the question, so "Years of experience with Python?"
    # and "How many years of Python experience do you have" collapse to one.
    question_key: Mapped[str] = mapped_column(String(300))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="other")
    times_used: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
