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
