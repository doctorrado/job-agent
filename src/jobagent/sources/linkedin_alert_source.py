"""LinkedIn job-alert email source.

The ToS-compliant path into LinkedIn's job market: LinkedIn sends these
digests because the user asked for them, and reading your own inbox is not
scraping LinkedIn. Needs GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env — an
app password from myaccount.google.com/apppasswords, never the real account
password. The mailbox is opened read-only; nothing is ever modified or
marked as read.

Parses the text/plain part of each multipart alert, not the HTML. Real
alerts carry both, and the plain-text part has a regular structure — job
blocks separated by dashed lines, each "title / company / location /
optional status line / View job: <url>" — so no HTML-parser dependency is
needed. Verified against a real alert email (2026-09-09).

Known limitation: alerts carry NO job description, only title, company,
location and a link. Description-driven extraction (skills, years required,
work authorization) has nothing to read here, so these can never be caught
by the work-authorization filter. Scoring deliberately does not dampen
description-less jobs — see pipeline/score.py and NOTES.md.
"""

from __future__ import annotations

import email
import imaplib
import re
from datetime import date, datetime, timedelta
from email.message import Message
from email.utils import parsedate_to_datetime

from jobagent.models.job import Job
from jobagent.sources.base import JobSource

IMAP_HOST = "imap.gmail.com"
ALERT_SENDER = "jobalerts-noreply@linkedin.com"

_SEPARATOR = re.compile(r"^-{20,}\s*$", re.M)
_VIEW_JOB = re.compile(r"View job:\s*(\S+)")
_JOB_ID = re.compile(r"/jobs/view/(\d+)")
_HEADER_LINE = re.compile(r"^(your job alert for|new jobs match your preferences)", re.I)


class LinkedInAlertSource(JobSource):
    name = "linkedin_alerts"

    def __init__(
        self,
        address: str,
        app_password: str,
        since_days: int = 30,
        mailbox: str = "INBOX",
    ) -> None:
        self.address = address
        self.app_password = app_password
        self.since_days = since_days
        self.mailbox = mailbox

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
            imap.login(self.address, self.app_password)
            imap.select(self.mailbox, readonly=True)  # never modify the mailbox
            since = (datetime.now() - timedelta(days=self.since_days)).strftime("%d-%b-%Y")
            _, data = imap.search(None, "FROM", f'"{ALERT_SENDER}"', "SINCE", since)
            for message_id in data[0].split():
                _, raw = imap.fetch(message_id, "(RFC822)")
                message = email.message_from_bytes(raw[0][1])
                jobs.extend(parse_alert_email(message))
        return jobs


def parse_alert_email(message: Message) -> list[Job]:
    """Pull every job out of one LinkedIn alert digest."""
    text = _plain_text_part(message)
    if not text:
        return []
    sent = _sent_date(message)
    return [_to_job(fields, sent) for fields in _parse_blocks(text)]


def _plain_text_part(message: Message) -> str | None:
    for part in message.walk():
        if part.get_content_type() != "text/plain":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return None


def _parse_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for chunk in _SEPARATOR.split(text):
        url_match = _VIEW_JOB.search(chunk)
        if not url_match:
            continue  # skips the digest's footer, which has no job link
        id_match = _JOB_ID.search(url_match.group(1))
        if not id_match:
            continue
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        while lines and _HEADER_LINE.match(lines[0]):
            lines.pop(0)  # only the first block carries the digest header
        if len(lines) < 3:
            continue
        blocks.append(
            {
                "job_id": id_match.group(1),
                "title": lines[0],
                "company": lines[1],
                "location": lines[2],
            }
        )
    return blocks


def _to_job(fields: dict[str, str], sent: date | None) -> Job:
    job_id = fields["job_id"]
    return Job(
        source="linkedin_alerts",
        source_job_id=job_id,
        # Canonical URL, not the email's tracking link — that carries
        # per-recipient tokens and differs between digests for the same job.
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        title=fields["title"],
        company=fields["company"],
        location=fields["location"],
        description="",  # alerts carry no description — see module docstring
        posted_date=sent,
    )


def _sent_date(message: Message) -> date | None:
    """The digest's send date, used as a proxy for the posting date. These
    fire on newly matched jobs so it's close, but it is an approximation —
    not the employer's actual posting date."""
    raw = message.get("Date")
    if not raw:
        return None
    parsed = parsedate_to_datetime(raw)
    return parsed.date() if parsed else None
