from jobagent.answers.resolve import resolve
from jobagent.models.profile import (
    LocationPreferences,
    Profile,
    SalaryExpectation,
    WorkAuthorization,
)


def _profile(**overrides):
    data = dict(
        name="Test",
        target_roles=["Data Analyst"],
        skills=["Python", "SQL", "Microsoft SQL Server", "Power BI", "Snowflake"],
        skill_years={"python": 3, "sql": 3, "microsoft sql server": 1},
        locations=LocationPreferences(preferred_cities=["Bogota"]),
        work_authorization=WorkAuthorization(us_authorized=False),
        salary=SalaryExpectation(minimum_monthly=5_000_000, target_monthly=6_000_000),
    )
    data.update(overrides)
    return Profile(**data)


def test_years_question_is_answered_from_the_profile():
    for question in (
        "How many years of experience do you have with Python?",
        "Years of Python experience?",
        "¿Cuántos años de experiencia tienes con Python?",
    ):
        answer = resolve(question, _profile())
        assert answer is not None and answer.answer == "3", question


def test_the_longest_matching_skill_wins():
    """65 overlapping skill names means "Microsoft SQL Server" must not be
    answered with the years recorded for plain "SQL"."""
    answer = resolve("Years of experience with Microsoft SQL Server?", _profile())
    assert answer.answer == "1"


def test_a_skill_without_a_recorded_duration_says_so_rather_than_zero():
    """He HAS Power BI — it is in the profile. Answering 0 would be a lie and
    guessing would be worse."""
    answer = resolve("How many years of Power BI?", _profile())
    assert answer is not None
    assert answer.confident is False
    assert "not recorded" in answer.answer


def test_an_unknown_technology_is_not_answered_at_all():
    assert resolve("How many years of Kubernetes experience?", _profile()) is None


def test_sponsorship_distinguishes_colombia_from_the_us():
    answer = resolve("Do you require visa sponsorship?", _profile())
    assert "Colombia" in answer.answer
    assert "sponsorship WOULD be required" in answer.answer


def test_salary_comes_from_the_profile_floor_and_target():
    answer = resolve("What is your salary expectation?", _profile())
    assert "6,000,000" in answer.answer and "5,000,000" in answer.answer


def test_an_unrelated_question_is_not_invented():
    assert resolve("Why do you want to work here?", _profile()) is None
