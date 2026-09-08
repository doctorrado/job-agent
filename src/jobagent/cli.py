"""Command-line interface for jobagent."""

from __future__ import annotations

import typer

from jobagent import __version__
from jobagent.config import get_settings, load_profile
from jobagent.logging import configure_logging, get_logger
from jobagent.pipeline.fetch import run_fetch
from jobagent.pipeline.score import score_job
from jobagent.storage.db import make_session_factory
from jobagent.storage.repository import JobRepository
from jobagent.sources.jooble_source import JoobleSource, read_usage, LIFETIME_LIMIT


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
def rank() -> None:
    """Score every stored job against your profile and print a ranked report."""
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    repository = JobRepository(make_session_factory(settings.db_path)())

    results = [score_job(job, profile) for job in repository.all()]
    eligible = sorted((r for r in results if r.eligible), key=lambda r: r.total, reverse=True)
    ineligible = [r for r in results if not r.eligible]

    typer.echo(f"{len(eligible)} eligible, {len(ineligible)} filtered out\n")
    for r in eligible[:20]:
        matched = ",".join(r.matched_skills) or "none"
        b = r.breakdown
        note = "  (dampened — no skill overlap)" if not r.matched_skills else ""
        typer.echo(
            f"{r.total:3d}  {r.job.company} — {r.job.title}{note}\n"
            f"      skills={b['skills']} seniority={b['seniority']} "
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
