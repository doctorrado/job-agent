from jobagent.models.job import Job
from jobagent.models.profile import (
    LocationPreferences,
    Profile,
    SalaryExpectation,
    WorkAuthorization,
)
from jobagent.pipeline.score import score_job


def _profile(**overrides):
    data = dict(
        name="Test",
        target_roles=["Data Analyst"],
        skills=["Python", "SQL", "Power BI"],
        max_years_experience=3,
        locations=LocationPreferences(remote_scopes_ok=["remote_anywhere", "remote_latam"]),
        work_authorization=WorkAuthorization(us_authorized=False),
        salary=SalaryExpectation(minimum_monthly=4_000_000, target_monthly=5_000_000),
    )
    data.update(overrides)
    return Profile(**data)


def _job(**overrides):
    data = dict(
        source="file",
        source_job_id="1",
        url="https://example.com/1",
        title="Data Analyst",
        company="Acme",
        description="",
        location=None,
        salary_raw=None,
    )
    data.update(overrides)
    return Job(**data)


def test_us_work_auth_requirement_is_hard_excluded():
    job = _job(description="Must be authorized to work in the United States.")
    result = score_job(job, _profile())
    assert result.eligible is False
    assert "work authorization" in result.ineligible_reason


def test_us_work_auth_ok_when_candidate_is_authorized():
    job = _job(description="Must be authorized to work in the United States.")
    authorized_profile = _profile()
    authorized_profile.work_authorization.us_authorized = True
    result = score_job(job, authorized_profile)
    assert result.eligible is True


def test_disclosed_salary_below_floor_is_hard_excluded():
    job = _job(salary_raw="COP 2,000,000")
    result = score_job(job, _profile())
    assert result.eligible is False
    assert "below your floor" in result.ineligible_reason


def test_undisclosed_salary_is_not_excluded_and_scored_neutral():
    result = score_job(_job(), _profile())
    assert result.eligible is True
    assert result.breakdown["salary"] == 5


def test_full_skill_match_maxes_skill_category():
    profile = _profile(skills=["Python", "SQL", "Power BI", "Excel", "Docker", "GCP"])
    job = _job(description="Python, SQL, Power BI, Excel, Docker, GCP required daily.")
    result = score_job(job, profile)
    assert result.breakdown["skills"] == 30



def test_senior_title_is_heavily_penalized_not_excluded():
    job = _job(title="Senior Data Analyst")
    result = score_job(job, _profile())
    assert result.eligible is True
    assert result.breakdown["seniority"] == 4

def test_below_hourly_usd_floor_is_hard_excluded():
    job = _job(description="This contract role pays $8/hr.")
    profile = _profile()
    profile.salary.minimum_hourly_usd = 15
    result = score_job(job, profile)
    assert result.eligible is False
    assert "hr floor" in result.ineligible_reason

def test_zero_skill_match_is_dampened_not_hidden():
    # A real description with genuinely zero overlap — long enough to count
    # as a description, which is what makes "no matches" meaningful evidence.
    description = (
        "We are looking for a driven sales professional to join our team. "
        "You will own the full sales cycle, from prospecting through close, "
        "build relationships with key accounts, negotiate contracts, and "
        "consistently exceed quarterly revenue targets in a fast-paced "
        "environment. Prior quota-carrying experience strongly preferred."
    )
    job = _job(title="Sales Jedi", description=description)
    result = score_job(job, _profile())
    assert result.eligible is True
    assert result.breakdown["skills"] == 0
    # Assert on the specific reason, not the total: other dampers (wrong
    # place, off-role) legitimately stack on this fixture too.
    assert "no skill overlap" in result.damping_reasons

def test_description_less_job_is_not_dampened():
    # LinkedIn alert emails carry no description at all, so zero skill
    # matches there means "no information", not "bad fit".
    job = _job(title="Business Intelligence Analyst 2", description="")
    result = score_job(job, _profile())
    assert result.breakdown["skills"] == 0
    assert "no skill overlap" not in result.damping_reasons

def test_role_keywords_separate_target_roles_from_unrelated_ones():
    profile = _profile()
    profile.role_keywords.primary = ["data engineer", "analista de datos"]
    profile.role_keywords.secondary = ["analista"]

    on_target = score_job(_job(title="Data Engineer (SQL-focused)"), profile)
    spanish = score_job(_job(title="Analista de Visualización de Datos"), profile)
    unrelated = score_job(_job(title="Backend Junior - Java"), profile)

    assert on_target.breakdown["role"] == 20
    assert spanish.breakdown["role"] == 12  # matches "analista", accent-insensitive
    assert unrelated.breakdown["role"] == 0



def test_internship_is_excluded_outright():
    for title in ("Data Analyst Intern", "Practicante de Datos", "Data Co-op"):
        result = score_job(_job(title=title), _profile())
        assert result.eligible is False, title
        assert "internship" in result.ineligible_reason


def test_internal_and_international_are_not_internships():
    for title in ("Internal Audit Analyst", "International Data Engineer"):
        assert score_job(_job(title=title), _profile()).eligible is True, title


def test_senior_title_penalised_even_when_years_look_junior():
    # Artefact's real "Senior Data Engineer" says "3+ years", which used to
    # return early on the years branch and score a full 20/20.
    job = _job(title="Senior Data Engineer", description="3+ years of experience required. " * 10)
    assert score_job(job, _profile()).breakdown["seniority"] == 4


def test_boilerplate_tech_list_does_not_inflate_skills():
    profile = _profile()
    real = "You will build data pipelines. Requirements: strong Python and SQL. " * 4
    padded = real + " NOT YOUR TECH STACK? We also hire for Scala, Rust, PHP, Java."
    assert score_job(_job(description=real), profile).matched_skills == score_job(
        _job(description=padded), profile
    ).matched_skills


def test_senior_title_damps_the_whole_score_not_just_seniority():
    """Docking 16 seniority points was outweighed by a full 30 for skills, so
    "Senior Analytics Engineer" scored 79 — above a well-matched Bogota BI
    Analyst at 75 the reviewer actually wanted."""
    profile = _profile()
    description = "Build pipelines with Python, SQL and Airflow. " * 12
    senior = score_job(_job(title="Senior Data Engineer", description=description), profile)
    plain = score_job(_job(title="Data Engineer", description=description), profile)
    assert "senior-level title" in senior.damping_reasons
    assert senior.total < plain.total


def test_a_years_gulf_damps_even_without_a_senior_title():
    profile = _profile()
    job = _job(
        title="Data Engineer",
        description="We need 8+ years of experience with Python, SQL and Airflow. " * 8,
    )
    result = score_job(job, profile)
    assert any("years" in r for r in result.damping_reasons)


def test_off_role_override_needs_skills_in_the_TITLE():
    """Counting description matches rescued every tech job in existence:
    UX Researcher and Total Rewards Analyst both scored 65 with role=0."""
    profile = _profile()
    body = "You will collaborate with teams using Python, SQL and Power BI. " * 12

    # skills named in the title -> genuinely a data job under an odd name,
    # the real case being "Dev Python (PySpark/Airflow/PostgreSQL) - Remoto"
    titled = score_job(_job(title="Dev Python / SQL / Power BI", description=""), profile)
    assert "not a target role" not in titled.damping_reasons

    # skills only mentioned in passing in a long body -> still off-role
    incidental = score_job(_job(title="UX Researcher", description=body), profile)
    assert "not a target role" in incidental.damping_reasons


def test_required_third_language_is_excluded_but_optional_is_not():
    """Skydropx's RevOps Data Analyst scored 80 and was a flat no: it wants
    "Portugues C1 o superior". Accents matter — [eê] silently never matched."""
    profile = _profile()
    required = _job(description="REQUISITOS: Indispensable: Portugués C1 o superior. " * 8)
    assert score_job(required, profile).eligible is False

    optional = _job(description="Deseable: Portugués avanzado. Python and SQL required. " * 8)
    assert score_job(optional, profile).eligible is True
