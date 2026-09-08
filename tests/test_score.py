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
    assert result.breakdown["salary"] == 8


def test_full_skill_match_maxes_skill_category():
    profile = _profile(skills=["Python", "SQL", "Power BI", "Excel", "Docker", "GCP"])
    job = _job(description="Python, SQL, Power BI, Excel, Docker, GCP required daily.")
    result = score_job(job, profile)
    assert result.breakdown["skills"] == 40



def test_senior_title_is_heavily_penalized_not_excluded():
    job = _job(title="Senior Data Analyst")
    result = score_job(job, _profile())
    assert result.eligible is True
    assert result.breakdown["seniority"] == 5

def test_below_hourly_usd_floor_is_hard_excluded():
    job = _job(description="This contract role pays $8/hr.")
    profile = _profile()
    profile.salary.minimum_hourly_usd = 15
    result = score_job(job, profile)
    assert result.eligible is False
    assert "hr floor" in result.ineligible_reason
