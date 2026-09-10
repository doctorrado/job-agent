import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jobagent.storage.db import Base
from jobagent.storage.repository import (
    AnswerRepository,
    ApplicationRepository,
    is_sensitive,
    normalise_question,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_applying_twice_to_one_posting_is_refused(session):
    """Re-applying to the same posting is a mistake, not an update."""
    repo = ApplicationRepository(session)
    assert repo.record("greenhouse", "1", "Sezzle", "Data Analyst") is True
    assert repo.record("greenhouse", "1", "Sezzle", "Data Analyst") is False
    assert repo.count() == 1


def test_status_moves_and_appends_notes(session):
    repo = ApplicationRepository(session)
    repo.record("greenhouse", "1", "Sezzle", "Data Analyst")
    assert repo.set_status("greenhouse", "1", "interview", "recruiter call Tuesday")
    row = repo.all()[0]
    assert row.status == "interview"
    assert "Tuesday" in row.notes
    assert repo.set_status("greenhouse", "missing", "interview") is False
    with pytest.raises(ValueError):
        repo.set_status("greenhouse", "1", "vibes")


def test_phrasings_of_one_question_share_an_answer(session):
    repo = AnswerRepository(session)
    assert repo.remember("How many years of experience do you have with Python?", "3")
    # different wording, same question
    found = repo.lookup("Years of Python experience?")
    assert found is not None and found.answer == "3"
    # re-asking bumps the counter rather than duplicating
    assert repo.remember("Years of Python experience?", "3") is False
    assert repo.count() == 1
    assert repo.lookup("Python years").times_used == 2


def test_normalise_question_ignores_filler_and_order():
    assert normalise_question("How many years of experience with Python?") == normalise_question(
        "Python experience, in years?"
    )
    assert normalise_question("Do you require visa sponsorship?") != normalise_question(
        "Are you willing to relocate?"
    )


def test_demographic_questions_are_never_banked(session):
    """CLAUDE.md forbids auto-answering these, so the bank refuses to hold
    them at all — an empty table cannot tempt a future form-filler."""
    repo = AnswerRepository(session)
    for question in (
        "What is your race/ethnicity?",
        "Do you identify as having a disability?",
        "Are you a protected veteran?",
        "What is your gender?",
        "What was your salary history at your last employer?",
    ):
        assert is_sensitive(question), question
        assert repo.remember(question, "prefer not to say") is False
    assert repo.count() == 0


def test_ordinary_application_questions_are_banked(session):
    repo = AnswerRepository(session)
    for question in (
        "Do you require visa sponsorship?",
        "What is your notice period?",
        "How many years of experience with Airflow?",
    ):
        assert not is_sensitive(question), question
        assert repo.remember(question, "answer") is True
    assert repo.count() == 3
