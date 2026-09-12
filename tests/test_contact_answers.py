from jobagent.answers.resolve import resolve
from jobagent.models.profile import (
    Contact,
    LocationPreferences,
    Profile,
    SalaryExpectation,
    WorkAuthorization,
)


def _profile():
    return Profile(
        name="Test",
        target_roles=["Data Analyst"],
        skills=["Python"],
        skill_years={"python": 3},
        locations=LocationPreferences(preferred_cities=["Bogota"]),
        work_authorization=WorkAuthorization(us_authorized=False),
        salary=SalaryExpectation(minimum_monthly=5_000_000, target_monthly=6_000_000),
    )


def _contact(**overrides):
    data = dict(
        full_name="Andres Torrado",
        email="a@example.com",
        phone="+1 555 000 0000",
        linkedin="https://linkedin.com/in/x",
        github="https://github.com/x",
        address_line="Cl. 25B",
        postal_code="110931",
        city="Bogota",
        country="Colombia",
        currently_resides_in_colombia=True,
    )
    data.update(overrides)
    return Contact(**data)


def test_contact_fields_are_answered():
    for question, expected in (
        ("What is your email address?", "a@example.com"),
        ("Phone number", "+1 555 000 0000"),
        ("LinkedIn profile URL", "linkedin.com/in/x"),
        ("What is your postal code?", "110931"),
        ("City", "Bogota"),
    ):
        answer = resolve(question, _profile(), _contact())
        assert answer is not None and expected in answer.answer, question


def test_residence_is_checked_before_the_address_fields():
    """"What country do you currently reside in" contains "country".
    Answering it from the address field states a fact the address does not
    establish."""
    answer = resolve("What country do you currently reside in?", _profile(),
                     _contact(currently_resides_in_colombia=False,
                              relocation_note="Relocating; not resident yet."))
    assert "not resident" in answer.answer.lower()
    assert answer.confident is False


def test_a_bogota_address_does_not_imply_living_there():
    """The address field and the residence question are different facts, and
    conflating them would break the never-fabricate rule in a new file."""
    away = _contact(currently_resides_in_colombia=False, relocation_note="Relocating.")
    assert "Bogota" in resolve("Address", _profile(), away).answer
    assert "Relocating" in resolve("Do you currently live in Colombia?", _profile(), away).answer


def test_relocation_answer_does_not_claim_he_is_already_there():
    away = _contact(currently_resides_in_colombia=False, relocation_note="Relocating.")
    answer = resolve("Are you willing to relocate?", _profile(), away)
    assert "Based in Colombia" not in answer.answer


def test_everything_still_works_without_a_contact_file():
    assert resolve("What is your email address?", _profile(), None) is None
    assert resolve("How many years of Python?", _profile(), None).answer == "3"
