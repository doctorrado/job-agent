"""Find which companies already in the job bank run a public ATS job board.

Earlier discovery passes searched the open web (`site:boards.greenhouse.io`
plus role keywords) and guessed at company names. This works the other way
round: the LinkedIn job alerts already name ~540 companies that are hiring
Andres's roles in his country, so probe THOSE against the documented public
board APIs. Far better hit rate, because relevance is established before the
first request.

Every API here is the platform's own documented public job-board endpoint —
the same ones CompanyBoardsSource already fetches from. No scraping.

A 200 is not a real board. Verified on live data 2026-09-10: Accenture and EY
both answer on Recruitee with trial accounts containing the identical
"Senior Marketer (Sample)" placeholder, and AgileEngine and Bold answer on
SmartRecruiters and Greenhouse with a single unrelated US job. `looks_real`
is what separates those from Wizeline's 31 openings.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

import httpx

from jobagent.pipeline.extract import strip_accents

# Politeness. These are free public endpoints run for employers' benefit, not
# ours; hammering them is both rude and self-defeating. A live run of 120
# companies had Workable answering 429 to every request by the end.
_REQUEST_DELAY_SECONDS = 0.15
_MAX_RATE_LIMITS = 3

# Fewer than this many openings and it is a placeholder account, not an
# employer's board. Wizeline 31 and Nubank 122 pass; the four false
# positives found on live data had 1, 1, 2 and 3.
_MIN_REAL_JOBS = 4

# Recruitee and Workable seed trial accounts with demo content.
_PLACEHOLDER = re.compile(r"\(sample\)|\bsample\b|\bdemo\b|lorem ipsum", re.I)

# Names that are job boards, staffing aggregators or parse artefacts rather
# than employers with their own careers site.
_NOT_AN_EMPLOYER = re.compile(
    r"^(elempleo|empresa confidencial|confidencial|computrabajo|indeed|"
    r"remote jobs|jobs|talent pool|varios|multiple)\b|"
    r"receive notifications|talent pool\)$",
    re.I,
)

PLATFORMS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
}


@dataclass(frozen=True)
class Candidate:
    company: str
    platform: str
    slug: str
    job_count: int
    sample_titles: tuple[str, ...]


def slug_candidates(company: str) -> list[str]:
    """Plausible board slugs for a company name, most likely first.

    Deliberately few: every extra variant multiplies the request count across
    six platforms, and the realistic hits are the obvious spellings.
    """
    ascii_name = unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", ascii_name).lower()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    words = cleaned.split()
    variants = [cleaned.replace(" ", ""), "-".join(words)]
    if len(words) > 1:
        # Risky: a first word alone is often a common one ("inter", "ultimate",
        # "solutions", "mas", "automation" all matched somebody else's board).
        # probe_company demands location corroboration for this variant.
        variants.append(words[0])
    return list(dict.fromkeys(v for v in variants if len(v) >= 3))


def is_probeable(company: str) -> bool:
    """False for job boards, staffing aggregators and parse artefacts."""
    name = (company or "").strip()
    return bool(name) and len(name) <= 60 and not _NOT_AN_EMPLOYER.search(name)


def extract_jobs(platform: str, payload: object) -> list[tuple[str, str]]:
    """(title, location) per posting, or [] if the response shape is wrong."""
    try:
        if platform == "greenhouse":
            return [
                (j["title"], (j.get("location") or {}).get("name", ""))
                for j in payload["jobs"]
            ]
        if platform == "lever":
            return [
                (p["text"], (p.get("categories") or {}).get("location") or "") for p in payload
            ]
        if platform == "ashby":
            return [(j["title"], j.get("location") or "") for j in payload["jobs"]]
        if platform == "smartrecruiters":
            return [
                (j["name"], " ".join(str(v) for v in (j.get("location") or {}).values()))
                for j in payload["content"]
            ]
        if platform == "recruitee":
            return [(o["title"], o.get("location") or "") for o in payload["offers"]]
        if platform == "workable":
            return [(j["title"], j.get("location") or "") for j in payload["jobs"]]
    except (KeyError, TypeError, IndexError, AttributeError):
        return []
    return []


def _place_tokens(text: str) -> set[str]:
    ascii_text = strip_accents(text or "").lower()
    return {w for w in re.split(r"[^a-z]+", ascii_text) if len(w) >= 4}


def corroborated(known_locations: set[str], postings: list[tuple[str, str]]) -> bool:
    """Does this board post anywhere we have actually seen this company hire?

    Only applied to the risky first-word slug. On live data that slug matched
    "Inter Rapidisimo" (Bogota logistics) to Inter, a Brazilian bank with 136
    Portuguese-language jobs and none in Colombia, and "Ultimate Jet
    Vacations" to a US HVAC contractor. Both would have flooded the job bank.
    Experian's board, by contrast, really does carry 5 Colombia openings.
    """
    if not known_locations:
        return False
    wanted = set().union(*(_place_tokens(loc) for loc in known_locations))
    return any(wanted & _place_tokens(location) for _, location in postings)


def looks_real(postings: list[tuple[str, str]]) -> bool:
    """Whether a 200 response is an employer's board or a trial account."""
    if len(postings) < _MIN_REAL_JOBS:
        return False
    return not any(_PLACEHOLDER.search(title or "") for title, _ in postings)


@dataclass
class ProbeState:
    """Carried across a whole run so back-off survives between companies."""

    rate_limited: dict[str, int] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)

    def note_rate_limit(self, platform: str) -> None:
        self.rate_limited[platform] = self.rate_limited.get(platform, 0) + 1
        if self.rate_limited[platform] >= _MAX_RATE_LIMITS:
            self.disabled.add(platform)


def probe_company(
    client: httpx.Client,
    company: str,
    state: ProbeState | None = None,
    known_locations: set[str] | None = None,
) -> Candidate | None:
    """First real board found for one company, or None."""
    state = state if state is not None else ProbeState()
    slugs = slug_candidates(company)
    full_name_slugs = set(slugs[:2])
    for slug in slugs:
        for platform, template in PLATFORMS.items():
            if platform in state.disabled:
                continue
            time.sleep(_REQUEST_DELAY_SECONDS)
            try:
                response = client.get(template.format(slug=slug))
            except httpx.HTTPError:
                continue
            if response.status_code == 429:
                # Stop asking a platform that has told us to stop.
                state.note_rate_limit(platform)
                continue
            if response.status_code != 200:
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            postings = extract_jobs(platform, payload)
            if not looks_real(postings):
                continue
            if slug not in full_name_slugs and not corroborated(known_locations or set(), postings):
                continue
            return Candidate(
                company=company,
                platform=platform,
                slug=slug,
                job_count=len(postings),
                sample_titles=tuple(title for title, _ in postings[:3]),
            )
    return None
