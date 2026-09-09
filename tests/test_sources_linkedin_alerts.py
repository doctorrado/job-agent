from email.message import EmailMessage

from jobagent.sources.linkedin_alert_source import parse_alert_email

SAMPLE = """Your job alert for Business Analyst in Colombia
New jobs match your preferences.

Data Business Junior Analyst
Rappi
Bogota, D.C.

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/4462244500/?trackingId=abc

---------------------------------------------------------

Junior Consultant
Universia Colombia
Chapinero
View job: https://www.linkedin.com/comm/jobs/view/4460630124/?trackingId=xyz

---------------------------------------------------------

See all jobs on LinkedIn: https://www.linkedin.com/comm/jobs/search-results/
"""


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    message["Date"] = "Wed, 9 Sep 2026 12:28:38 +0000 (UTC)"
    message.set_content(SAMPLE)
    return message


def test_parses_every_job_block():
    jobs = parse_alert_email(_message())

    assert len(jobs) == 2
    first, second = jobs
    assert first.source == "linkedin_alerts"
    assert first.source_job_id == "4462244500"
    assert first.title == "Data Business Junior Analyst"
    assert first.company == "Rappi"
    assert first.location == "Bogota, D.C."
    assert str(first.url) == "https://www.linkedin.com/jobs/view/4462244500/"
    assert first.posted_date.isoformat() == "2026-09-09"
    # this block has no status line at all — still parsed correctly
    assert second.title == "Junior Consultant"
    assert second.location == "Chapinero"


def test_footer_without_a_job_link_is_ignored():
    jobs = parse_alert_email(_message())
    assert all("search-results" not in str(job.url) for job in jobs)
