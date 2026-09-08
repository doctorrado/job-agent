from jobagent.models.job import Job, Seniority
from jobagent.models.profile import Profile
from jobagent.pipeline.extract import (
    detect_seniority,
    matched_skills,
    remote_scope,
    requires_us_work_authorization,
    salary_monthly_cop,
    years_required,
)


def _job(title="Data Analyst", description="", location=None, salary_raw=None):
    return Job(
        source="file",
        source_job_id="1",
        url="https://example.com/1",
        title=title,
        company="Acme",
        description=description,
        location=location,
        salary_raw=salary_raw,
    )


def _profile(**overrides):
    data = {"name": "Test", "target_roles": ["Data Analyst"], "skills": ["Python", "SQL"]}
    data.update(overrides)
    return Profile(**data)


def test_matched_skills_finds_word_boundary_matches():
    job = _job(description="We use Python and SQL daily.")
    assert set(matched_skills(job, _profile())) == {"Python", "SQL"}


def test_matched_skills_ignores_substring_false_positives():
    job = _job(description="We use Postgresql extensively.")
    assert matched_skills(job, _profile()) == []


def test_years_required_extracts_lowest_number():
    assert years_required(_job(description="3-5 years of experience required.")) == 3


def test_years_required_none_when_absent():
    assert years_required(_job(description="No experience mentioned here.")) is None


def test_detect_seniority_from_title():
    assert detect_seniority(_job(title="Senior Data Analyst")) is Seniority.senior
    assert detect_seniority(_job(title="Junior Data Analyst")) is Seniority.junior
    assert detect_seniority(_job(title="Data Analyst")) is Seniority.unknown


def test_requires_us_work_authorization_detects_phrase():
    job = _job(description="Must be authorized to work in the United States.")
    assert requires_us_work_authorization(job) is True


def test_requires_us_work_authorization_false_when_absent():
    assert requires_us_work_authorization(_job(description="Remote, open globally.")) is False


def test_remote_scope_detects_colombia():
    assert remote_scope(_job(location="Remote - Colombia")) == "remote_from_colombia"


def test_remote_scope_detects_anywhere():
    assert remote_scope(_job(description="Remote, open worldwide.")) == "remote_anywhere"


def test_salary_monthly_cop_parses_disclosed_amount():
    assert salary_monthly_cop(_job(salary_raw="COP 5,000,000")) == 5000000


def test_salary_monthly_cop_none_when_undisclosed():
    assert salary_monthly_cop(_job()) is None

def test_requires_us_work_authorization_detects_residency_requirement():
    job = _job(
        description="Must have resided in the United States for the past three consecutive years."
    )
    assert requires_us_work_authorization(job) is True


def test_requires_us_work_authorization_detects_remote_within_us():
    job = _job(description="This role is fully remote within the United States.")
    assert requires_us_work_authorization(job) is True


def test_requires_us_work_authorization_ignores_generic_company_description():
    job = _job(
        description=(
            "Sezzle is a financial technology company operating in the "
            "United States and Canada."
        )
    )
    assert requires_us_work_authorization(job) is False



def test_salary_monthly_cop_ignores_usd_amounts():
    job = _job(description="The compensation range for the role is $2,500 - $4,500 USD GROSS.")
    assert salary_monthly_cop(job) is None


def test_salary_monthly_cop_ignores_per_word_freelance_rate():
    job = _job(description="Initial compensation is up to $0.06 per word.")
    assert salary_monthly_cop(job) is None

def test_salary_hourly_usd_parses_explicit_hourly_rate():
    job = _job(description="This role pays $22/hr for the right candidate.")
    assert salary_hourly_usd(job) == 22.0


def test_salary_hourly_usd_converts_explicit_annual_figure():
    job = _job(description="Compensation is $41,600 annually for this position.")
    assert salary_hourly_usd(job) == 20.0


def test_salary_hourly_usd_ignores_per_word_piecework():
    job = _job(description="Initial compensation is up to $0.06 per word.")
    assert salary_hourly_usd(job) is None


def test_salary_hourly_usd_none_without_explicit_period():
    job = _job(description="The compensation range for the role is $2,500 - $4,500 USD GROSS.")
    assert salary_hourly_usd(job) is None
