"""SQLite database setup via SQLAlchemy.

SQLite because this is a single-user tool with no simultaneous multi-machine
writes — no need for a database server. SQLAlchemy because it's a real ORM
worth learning, and because if this ever needs Postgres later, only this
file changes, not the rest of the app.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_session_factory(db_path: Path) -> sessionmaker[Session]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
