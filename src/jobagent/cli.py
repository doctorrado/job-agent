"""Command-line interface for jobagent."""

from __future__ import annotations

import html
import json
import re
import sys
import webbrowser
from pathlib import Path

import typer

from jobagent import __version__
from jobagent.config import get_settings, load_profile
from jobagent.logging import configure_logging, get_logger
from jobagent.pipeline.dedupe import normalize_company, normalize_text
from jobagent.pipeline.fetch import run_fetch
from jobagent.pipeline.score import score_job
from jobagent.resumes.loader import docx_lines, load_resumes
from jobagent.resumes.select import build_weights, choose_resume
from jobagent.resumes.tailor import analyse_gaps, output_path, page_count, tailor_docx
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
        note = f"  (dampened — {', '.join(r.damping_reasons)})" if r.damping_reasons else ""
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


# Matches _MIN_DESCRIPTION_CHARS in scoring: below this there is no posting
# body to reason about, only a title, company and location.
_MIN_EVIDENCE_CHARS = 200


def _posting_path(directory: Path, source: str, job_id: str) -> Path:
    """Where a hand-saved posting body lives for one job."""
    return directory / f"{source}_{job_id}.txt"


def _read_until_sentinel(sentinel: str = "END") -> str | None:
    """Collect pasted lines until a line that is exactly the sentinel.

    Not sys.stdin.read(): that consumes to EOF, so after the first Ctrl-D
    every later read returns "" and the rest of the run would silently skip
    every job. A sentinel line behaves the same in a terminal and in a pipe.
    Returns None only when stdin closes for good.
    """
    lines: list[str] = []
    for line in sys.stdin:
        if line.rstrip("\n") == sentinel:
            return "".join(lines)
        lines.append(line)
    return "".join(lines) if lines else None


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

    # One real opening often appears several times: Sezzle posts the same
    # Data Analyst role once per LATAM country, and the same job reaches us
    # from both Jooble and a LinkedIn alert. Eight of the first forty reviewed
    # were such pairs. Storage keeps them all (they ARE separate listings with
    # separate apply links) but a review batch should spend its slots on
    # distinct openings. Highest score wins, which naturally prefers the
    # Colombia-located variant; the others ride along so no apply link is lost.
    collapsed: dict[tuple[str, str], list] = {}
    for r in pending:
        collapsed.setdefault(
            (normalize_company(r.job.company), normalize_text(r.job.title)), []
        ).append(r)
    unique = sorted(collapsed.values(), key=lambda g: g[0].total, reverse=True)
    batch = [group[0] for group in unique[:limit]]
    variants = {id(group[0]): group[1:] for group in unique[:limit]}

    payload = {
        "instructions": (
            "Fill in 'verdict' for each job: worth_applying | unsure | not_a_fit. "
            "Add a one-line 'reasoning'. Lean towards 'unsure' rather than "
            "'not_a_fit' whenever there is a real argument for applying. "
            "Check the 'evidence' field and judge accordingly. 'full posting' "
            "means decide the fit properly. 'title only' means the source is a "
            "job-alert email that carries no description at all, so seniority "
            "and stack are unknowable — judge it as TRIAGE: is this company, "
            "title and location worth opening the link for? A recognisable "
            "employer with a target title in Colombia is 'worth_applying' even "
            "with no description; reserve 'unsure' for titles whose level or "
            "field is genuinely ambiguous, not for every description-less row. "
            "One verdict covers every listing of the same opening: "
            "'also_posted_in' lists the other locations and apply links for "
            "the same role, so judge it once. "
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
                "evidence": (
                    "full posting"
                    if len((r.job.description or "").strip()) >= _MIN_EVIDENCE_CHARS
                    else "title only"
                ),
                "description": _readable(r.job.description, max_description),
                "also_posted_in": [
                    {
                        "location": v.job.location,
                        "source": v.job.source,
                        "source_job_id": v.job.source_job_id,
                        "url": str(v.job.url),
                    }
                    for v in variants[id(r)]
                ],
                "verdict": "",
                "reasoning": "",
            }
            for r in batch
        ],
    }
    export_path = Path(export)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    duplicates = len(pending) - len(unique)
    typer.echo(
        f"{len(pending)} jobs awaiting review ({len(unique)} distinct openings, "
        f"{duplicates} repeat listings folded in); wrote the top {len(batch)} "
        f"to {export_path}."
    )
    titles_only = len([r for r in batch if len((r.job.description or "").strip()) < 200])
    if titles_only:
        typer.echo(
            f"{titles_only} of those carry no description (job-alert email) — "
            "the batch marks them 'title only' so they are triaged, not guessed at."
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

    # How much is LEFT is the number that actually tells you what to do next,
    # and until now nothing in the workflow printed it: review-queue announced
    # it in whichever terminal built the batch, and the reviewing session never
    # saw it at all. Easy to finish a batch believing it was the whole pool.
    profile = load_profile(settings.profile_path)
    jobs = JobRepository(make_session_factory(settings.db_path)()).all()
    judged = reviews.verdicts()
    pending = [
        score_job(j, profile)
        for j in jobs
        if j.dedupe_key not in judged
    ]
    remaining = [r for r in pending if r.eligible]
    strong = len([r for r in remaining if r.total >= 60])
    typer.echo(
        f"{len(remaining)} eligible jobs still unreviewed ({strong} scoring 60+). "
        f"Next batch: jobagent review-queue --limit 100"
    )


@app.command("pick-resume")
def pick_resume(
    source: str = typer.Option(..., help="Job source, e.g. greenhouse"),
    job_id: str = typer.Option(..., help="source_job_id of the posting"),
) -> None:
    """Say which master resume best fits one stored posting, and why."""
    settings = get_settings()
    repository = JobRepository(make_session_factory(settings.db_path)())
    job = next(
        (j for j in repository.all() if j.source == source and j.source_job_id == job_id),
        None,
    )
    if job is None:
        typer.echo(f"No stored job {source}:{job_id}")
        raise typer.Exit(1)

    resumes = load_resumes(settings.resumes_dir)
    if not resumes:
        typer.echo(f"No .docx resumes found in {settings.resumes_dir}")
        raise typer.Exit(1)

    choice = choose_resume(f"{job.title} {job.description}", build_weights(resumes))

    typer.echo(f"{job.company} — {job.title}\n{job.url}\n")
    for match in choice.ranked:
        marker = "->" if match is choice.best else "  "
        why = ", ".join(match.reasons[:7])
        typer.echo(f" {marker} {match.resume:<7} {match.score:>5.1f}  {why}")

    typer.echo("")
    if choice.is_weak:
        typer.echo("No resume is a strong fit for this posting — worth deciding yourself.")
    elif choice.is_ambiguous:
        runner_up = choice.ranked[1].resume
        typer.echo(
            f"{choice.best.resume} and {runner_up} are too close to call — your judgement."
        )
    else:
        typer.echo(f"Use {choice.best.resume}.")


@app.command()
def tailor(
    source: str = typer.Option(..., help="Job source, e.g. greenhouse"),
    job_id: str = typer.Option(..., help="source_job_id of the posting"),
    resume: str | None = typer.Option(None, help="Override the auto-picked resume"),
    posting: str | None = typer.Option(
        None, help="Text file with the posting body, for sources that carry no description"
    ),
    write: bool = typer.Option(
        False, "--write", help="Write a tailored copy with skills reordered for this job"
    ),
    out_dir: str = typer.Option("data/tailored", help="Where to write the tailored copy"),
) -> None:
    """Show what a posting asks for versus what the chosen resume says.

    Reports three separate things: what is already covered, what is safe to
    add (you have it, the resume just does not mention it), and what the
    posting wants that you genuinely do not have — which is never added, only
    shown so you can judge the gap.
    """
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    repository = JobRepository(make_session_factory(settings.db_path)())
    job = next(
        (j for j in repository.all() if j.source == source and j.source_job_id == job_id),
        None,
    )
    if job is None:
        typer.echo(f"No stored job {source}:{job_id}")
        raise typer.Exit(1)

    resumes = load_resumes(settings.resumes_dir)
    if not resumes:
        typer.echo(f"No .docx resumes found in {settings.resumes_dir}")
        raise typer.Exit(1)

    # LinkedIn alert emails carry a title and a link, nothing else — 11 of the
    # first 16 jobs Andres marked worth_applying had an empty description, so
    # resume selection and gap analysis had nothing to read. Copying the real
    # posting into a text file is the deliberate, ToS-safe way in; scraping
    # the page is not. Same escape-hatch role FileSource plays for fetching.
    description = job.description
    saved = _posting_path(settings.postings_dir, job.source, job.source_job_id)
    if posting:
        posting_path = Path(posting)
        if not posting_path.is_file():
            typer.echo(f"No such posting file: {posting}")
            raise typer.Exit(1)
        description = posting_path.read_text(encoding="utf-8")
    elif len(description.strip()) < _MIN_EVIDENCE_CHARS and saved.is_file():
        # `read-postings` already collected this one; use it without being asked.
        description = saved.read_text(encoding="utf-8")
        typer.echo(f"(using the posting you saved at {saved})")

    job_text = f"{job.title} {description}"
    if resume:
        chosen = next((r for r in resumes if r.name.lower() == resume.lower()), None)
        if chosen is None:
            names = ", ".join(r.name for r in resumes)
            typer.echo(f"Unknown resume {resume!r}. Available: {names}")
            raise typer.Exit(1)
        note = "chosen by you"
    else:
        choice = choose_resume(job_text, build_weights(resumes))
        chosen = next(r for r in resumes if r.name == choice.best.resume)
        if choice.is_weak:
            note = "auto-picked, but no resume fits this posting well"
        elif choice.is_ambiguous:
            note = f"auto-picked, but tied with {choice.ranked[1].resume}"
        else:
            note = "auto-picked"

    resume_text = "\n".join(docx_lines(chosen.path)) if chosen.path else ""
    gaps = analyse_gaps(job_text, resume_text, profile.skills)

    typer.echo(f"{job.company} — {job.title}")
    typer.echo(f"{job.url}\n")
    typer.echo(f"Resume: {chosen.name}  ({note})")
    if gaps.coverage is None:
        typer.echo(
            f"Not enough posting to judge coverage — it named only {gaps.asked} "
            "technolog(ies). Open the URL and read it yourself.\n"
        )
    else:
        typer.echo(
            f"You can meet {gaps.coverage}% of what this posting asks for "
            f"({gaps.asked} named).\n"
        )

    if gaps.missing:
        typer.echo("SAFE TO ADD — you have these, this resume does not say so:")
        for term in gaps.missing:
            typer.echo(f"    + {term}")
        typer.echo("")
    if gaps.absent:
        typer.echo("NOT YOURS — the posting wants these, you do not have them:")
        typer.echo(f"    {', '.join(gaps.absent)}\n")
    if gaps.covered:
        typer.echo(f"Already covered ({len(gaps.covered)}): {', '.join(gaps.covered)}")

    if not write:
        return

    priority = {t.lower() for t in gaps.covered}
    destination = output_path(chosen.path, Path(out_dir))
    moved = tailor_docx(chosen.path, destination, priority)

    pages = page_count(destination)
    noun = "list" if moved == 1 else "lists"
    typer.echo(f"\nWrote {destination} ({moved} skill {noun} reordered)")
    if pages == 1:
        typer.echo("Still one page.")
    elif pages:
        typer.echo(f"WARNING: this renders to {pages} pages — your rule is one.")
    else:
        typer.echo("Could not check the page count (LibreOffice unavailable).")
    if gaps.missing:
        typer.echo("Add the 'safe to add' terms by hand — placing them is your call.")


@app.command("read-postings")
def read_postings(
    verdict: str = typer.Option(
        "worth_applying", help="Which reviewed jobs to work through"
    ),
    limit: int = typer.Option(10, help="How many to go through in one sitting"),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open each posting in your browser"
    ),
) -> None:
    """Work through job-alert leads that arrived with no description.

    Job-alert emails carry a title and a link, nothing else, so resume
    selection and gap analysis have nothing to read. This opens each posting
    in YOUR browser — where you are already logged in — and saves whatever
    you paste back. Fetching those pages with the script instead would be
    scraping: against LinkedIn's terms, and a real risk to your own account
    while you are actively job hunting. Automating the clicking is fine;
    automating the reading is not.
    """
    settings = get_settings()
    session = make_session_factory(settings.db_path)()
    reviews = ReviewRepository(session).verdicts()
    jobs = JobRepository(session).all()

    settings.postings_dir.mkdir(parents=True, exist_ok=True)
    pending = [
        j
        for j in jobs
        if reviews.get(j.dedupe_key) == verdict
        and len((j.description or "").strip()) < _MIN_EVIDENCE_CHARS
        and not _posting_path(settings.postings_dir, j.source, j.source_job_id).is_file()
    ]
    if not pending:
        typer.echo(f"Nothing left: every '{verdict}' lead already has a posting saved.")
        return

    typer.echo(
        f"{len(pending)} '{verdict}' leads still need their posting text. "
        f"Doing up to {limit} now.\n"
    )
    saved = 0
    for job in pending[:limit]:
        typer.echo(f"── {job.company} — {job.title}")
        typer.echo(f"   {job.url}")
        if open_browser:
            webbrowser.open(str(job.url))
        typer.echo(
            "   Paste the job description, then type END on its own line.\n"
            "   (END with nothing above it skips this one, Ctrl-C stops)\n"
        )
        try:
            body = _read_until_sentinel()
        except KeyboardInterrupt:
            typer.echo("\nStopped.")
            break
        if body is None:  # stdin closed entirely
            typer.echo("\nInput ended.")
            break
        if not body.strip():
            typer.echo("   skipped\n")
            continue
        destination = _posting_path(settings.postings_dir, job.source, job.source_job_id)
        destination.write_text(body, encoding="utf-8")
        saved += 1
        typer.echo(f"   saved {len(body):,} chars -> {destination}\n")

    typer.echo(
        f"Saved {saved}. `jobagent tailor --source X --job-id Y` now picks these up "
        "automatically — no --posting needed."
    )
