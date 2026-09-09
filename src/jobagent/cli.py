"""Command-line interface for jobagent."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import typer

from jobagent import __version__
from jobagent.config import get_settings, load_profile
from jobagent.logging import configure_logging, get_logger
from jobagent.pipeline.fetch import run_fetch
from jobagent.pipeline.score import score_job
from jobagent.sources.jooble_source import LIFETIME_LIMIT, JoobleSource, read_usage
from jobagent.storage.db import make_session_factory
from jobagent.storage.repository import JobRepository, ReviewRepository

app = typer.Typer(help="AI-powered job search and application assistant.")
log = get_logger(__name__)


@app.callback()
def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command("check-profile")
def check_profile() -> None:
    """Load and validate your profile YAML, then print a short summary."""
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    log.info("profile_loaded", name=profile.name, target_roles=len(profile.target_roles))
    typer.echo(
        f"OK: {profile.name} — {len(profile.target_roles)} target roles, "
        f"{len(profile.skills)} skills."
    )


@app.command()
def rank(
    source: str | None = typer.Option(
        None, help="Only rank jobs from this source, e.g. linkedin_alerts"
    ),
    limit: int = typer.Option(20, help="How many jobs to show"),
    show_all: bool = typer.Option(
        False, "--all", help="Include postings already reviewed as not_a_fit"
    ),
) -> None:
    """Score every stored job against your profile and print a ranked report.

    Scores are only really comparable within a source: sources carrying full
    job descriptions can earn skill points that description-less ones (like
    LinkedIn alert emails) structurally cannot. Use --source to compare
    like-for-like.
    """
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    repository = JobRepository(make_session_factory(settings.db_path)())

    all_jobs = repository.all()
    jobs = [job for job in all_jobs if job.source == source] if source else all_jobs
    if source and not jobs:
        available = ", ".join(sorted({job.source for job in all_jobs}))
        typer.echo(f"No jobs from source {source!r}. Available: {available}")
        raise typer.Exit(1)

    verdicts = ReviewRepository(make_session_factory(settings.db_path)()).verdicts()
    results = [score_job(job, profile) for job in jobs]
    eligible = sorted((r for r in results if r.eligible), key=lambda r: r.total, reverse=True)
    ineligible = [r for r in results if not r.eligible]

    hidden = 0
    if not show_all:
        kept = [r for r in eligible if verdicts.get(r.job.dedupe_key) != "not_a_fit"]
        hidden = len(eligible) - len(kept)
        eligible = kept

    scope = f" from {source}" if source else ""
    hidden_note = f", {hidden} hidden as not_a_fit (--all to show)" if hidden else ""
    typer.echo(f"{len(eligible)} eligible{scope}, {len(ineligible)} filtered out{hidden_note}\n")
    for r in eligible[:limit]:
        matched = ",".join(r.matched_skills) or "none"
        b = r.breakdown
        note = "  (dampened — no skill overlap)" if r.dampened else ""
        verdict = verdicts.get(r.job.dedupe_key)
        if verdict:
            note += f"  [{verdict}]"
        typer.echo(
            f"{r.total:3d}  [{r.job.source}] {r.job.company} — {r.job.title}{note}\n"
            f"      skills={b['skills']} role={b['role']} seniority={b['seniority']} "
            f"location={b['location']} salary={b['salary']}  matched={matched}\n"
            f"      {r.job.url}"
        )



@app.command()
def fetch() -> None:
    """Fetch jobs from every active source, dedupe, and store them."""
    settings = get_settings()
    session = make_session_factory(settings.db_path)()
    repository = JobRepository(session)
    stats = run_fetch(repository)
    typer.echo(
        f"Ran {stats['sources_run']} source(s): {stats['raw_fetched']} fetched, "
        f"{stats['after_dedupe']} after dedupe, {stats['new']} new, "
        f"{stats['already_seen']} already in the database. "
        f"Total jobs stored: {repository.count()}."
    )


@app.command("jooble-search")
def jooble_search(
    keywords: str = typer.Option("data analyst", help="Search keywords"),
    location: str = typer.Option("Colombia", help="Search location"),
) -> None:
    """Run one deliberate Jooble search — counts against the 500-call
    lifetime budget, so this is never part of the routine `fetch`."""
    settings = get_settings()
    if not settings.jooble_api_key:
        typer.echo("No JOOBLE_API_KEY set in .env — get one at co.jooble.org/api/about")
        raise typer.Exit(1)

    used = read_usage()
    typer.echo(f"Jooble calls used so far: {used}/{LIFETIME_LIMIT}")
    if not typer.confirm("Use one more call now?"):
        raise typer.Exit(0)

    repository = JobRepository(make_session_factory(settings.db_path)())
    jobs = JoobleSource(settings.jooble_api_key, keywords=keywords, location=location).fetch()
    new_count = sum(1 for job in jobs if repository.upsert(job))
    typer.echo(f"Fetched {len(jobs)} jobs, {new_count} new. Total stored: {repository.count()}.")


def _readable(text: str, limit: int) -> str:
    """Flatten a job description into plain text for the review file.

    Greenhouse and friends return HTML (often entity-escaped twice), which is
    unreadable in a review batch. A rough tag strip is fine HERE because the
    output is only ever read by a human or by Claude — the worst failure is
    cosmetic. Extraction still runs against the original stored text, so
    nothing about scoring depends on this.
    """
    unescaped = html.unescape(html.unescape(text))
    stripped = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", stripped).strip()[:limit]


@app.command("review-queue")
def review_queue(
    export: str = typer.Option("data/to_review.json", help="Where to write the batch"),
    limit: int = typer.Option(40, help="How many jobs to put in the batch"),
    max_description: int = typer.Option(
        1500, help="Truncate descriptions to keep the file readable"
    ),
) -> None:
    """Export the highest-scoring not-yet-reviewed jobs for a review pass.

    Everything needed to judge a posting is in the file itself, so a review
    session needs no other project context — just this batch and
    private/candidate_profile.md.
    """
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    session = make_session_factory(settings.db_path)()
    verdicts = ReviewRepository(session).verdicts()

    results = [score_job(job, profile) for job in JobRepository(session).all()]
    pending = [
        r
        for r in results
        if r.eligible and r.job.dedupe_key not in verdicts
    ]
    pending.sort(key=lambda r: r.total, reverse=True)
    batch = pending[:limit]

    payload = {
        "instructions": (
            "Fill in 'verdict' for each job: worth_applying | unsure | not_a_fit. "
            "Add a one-line 'reasoning'. Lean towards 'unsure' rather than "
            "'not_a_fit' whenever there is a real argument for applying. "
            "Then run: jobagent import-reviews <this file>"
        ),
        "jobs": [
            {
                "source": r.job.source,
                "source_job_id": r.job.source_job_id,
                "company": r.job.company,
                "title": r.job.title,
                "location": r.job.location,
                "url": str(r.job.url),
                "score": r.total,
                "breakdown": r.breakdown,
                "matched_skills": r.matched_skills,
                "description": _readable(r.job.description, max_description),
                "verdict": "",
                "reasoning": "",
            }
            for r in batch
        ],
    }
    export_path = Path(export)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(
        f"{len(pending)} jobs awaiting review; wrote the top {len(batch)} to {export_path}."
    )


@app.command("import-reviews")
def import_reviews(
    path: str = typer.Argument("data/to_review.json", help="Reviewed batch file"),
    reviewed_by: str = typer.Option("claude", help="Who made these calls"),
) -> None:
    """Persist verdicts from a reviewed batch. Judged once, never again."""
    settings = get_settings()
    reviews = ReviewRepository(make_session_factory(settings.db_path)())

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    recorded = skipped = blank = 0
    for entry in payload.get("jobs", []):
        verdict = (entry.get("verdict") or "").strip()
        if not verdict:
            blank += 1
            continue
        if reviews.record(
            entry["source"],
            entry["source_job_id"],
            verdict,
            entry.get("reasoning", ""),
            reviewed_by,
        ):
            recorded += 1
        else:
            skipped += 1

    typer.echo(
        f"Recorded {recorded} new verdicts, {skipped} already reviewed, "
        f"{blank} left blank. Total reviewed: {reviews.count()}."
    )
