from jobagent.answers.form import Outcome, clean_label, fill_form
from jobagent.models.profile import (
    Contact,
    LocationPreferences,
    Profile,
    SalaryExpectation,
    WorkAuthorization,
)


def _profile():
    return Profile(
        name="Andres Torrado",
        target_roles=["Data Analyst"],
        skills=["SQL", "Power BI"],
        skill_years={"sql": 3, "power bi": 2},
        locations=LocationPreferences(preferred_cities=["Bogota"]),
        work_authorization=WorkAuthorization(us_authorized=False),
        salary=SalaryExpectation(minimum_monthly=5_000_000, target_monthly=6_000_000),
    )


def _contact():
    return Contact(
        full_name="Andres Torrado Gil",
        email="a@example.com",
        phone="+1 555 000 0000",
        address_line="Cl. 25B #69 C-80",
        postal_code="110931",
        city="Bogota",
        region="Distrito Capital",
        country="Colombia",
        currently_resides_in_colombia=True,
    )


def test_form_chrome_is_stripped_from_labels():
    for raw, expected in (
        ("* First Name", "First Name"),
        ("1. Email Address:", "Email Address"),
        ("Phone Number (optional)", "Phone Number"),
        ("• City", "City"),
    ):
        assert clean_label(raw) == expected


def test_a_sponsorship_question_is_not_answered_from_the_country_field():
    """"Do you require sponsorship to work in this country" contains
    "country". Keyword matching answered it "Colombia" — a nonsense reply to
    an important question."""
    filled = fill_form(
        ["Do you require sponsorship to work in this country?"], _profile(), _contact()
    )
    assert filled[0].outcome is Outcome.ANSWERED
    assert "sponsorship" in filled[0].answer.lower()
    assert filled[0].answer.strip() != "Colombia"


def test_address_line_1_gets_the_street_not_the_whole_address():
    """Workday splits the address across fields; repeating city and country
    into line 1 would produce a mangled address."""
    filled = fill_form(["Address Line 1", "City", "Postal Code"], _profile(), _contact())
    assert filled[0].answer == "Cl. 25B #69 C-80"
    assert "Bogota" not in filled[0].answer
    assert filled[1].answer == "Bogota"


def test_two_surnames_are_kept_together():
    filled = fill_form(["First Name", "Last Name"], _profile(), _contact())
    assert filled[0].answer == "Andres"
    assert filled[1].answer == "Torrado Gil"


def test_the_three_outcomes_are_distinguished():
    filled = fill_form(
        [
            "How many years of experience with SQL?",
            "How many years of experience with Terraform?",
            "Are you a protected veteran?",
        ],
        _profile(),
        _contact(),
    )
    assert [f.outcome for f in filled] == [
        Outcome.ANSWERED,
        Outcome.UNKNOWN,
        Outcome.REFUSED,
    ]
    # an unknown field is reported, never filled with a guess
    assert filled[1].answer == ""


def test_blank_lines_are_ignored():
    assert len(fill_form(["City", "", "   "], _profile(), _contact())) == 1
