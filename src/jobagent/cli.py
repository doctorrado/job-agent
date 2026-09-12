"""Command-line interface for jobagent."""

from __future__ import annotations

import html
import json
import logging
import re
import shutil
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import typer
import yaml

from jobagent import __version__
from jobagent.answers.form import Outcome, clean_label, fill_form
from jobagent.answers.resolve import ResolvedAnswer, resolve
from jobagent.browser.workday import CDP_ENDPOINT, apply_answers, read_fields
from jobagent.config import get_settings, load_contact, load_history, load_profile
from jobagent.discovery.ats_probe import Candidate, ProbeState, is_probeable, probe_company
from jobagent.logging import configure_logging, get_logger
from jobagent.pipeline.dedupe import normalize_company, normalize_text, posting_identity
from jobagent.pipeline.fetch import COMPANIES_PATH, run_fetch
from jobagent.pipeline.score import score_job
from jobagent.resumes.loader import docx_lines, load_resumes
from jobagent.resumes.select import build_weights, choose_resume
from jobagent.resumes.tailor import analyse_gaps, output_path, page_count, tailor_docx
from jobagent.sources.jooble_source import LIFETIME_LIMIT, JoobleSource, read_usage
from jobagent.storage.db import make_session_factory
from jobagent.storage.repository import (
    STATUSES,
    AnswerRepository,
    ApplicationRepository,
    JobRepository,
    ReviewRepository,
    is_sensitive,
)

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


def _unimported_verdicts(export_path: Path, verdicts: dict[str, str]) -> int:
    """Verdicts sitting in an export file that never reached the database."""
    if not export_path.is_file():
        return 0
    try:
        payload = json.loads(export_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return 0
    return len(
        [
            entry
            for entry in payload.get("jobs", [])
            if (entry.get("verdict") or "").strip()
            and f"{entry.get('source')}:{entry.get('source_job_id')}" not in verdicts
        ]
    )


def _posting_path(directory: Path, source: str, job_id: str) -> Path:
    """Where a hand-saved posting body lives for one job."""
    return directory / f"{source}_{job_id}.txt"


# Ordered by how likely each is to be the right tool for the session type.
_CLIPBOARD_READERS = (
    ["wl-paste", "--no-newline"],
    ["xclip", "-selection", "clipboard", "-o"],
    ["xsel", "--clipboard", "--output"],
)


def _clipboard_reader() -> list[str] | None:
    """The first clipboard command available on this machine, if any."""
    return next((cmd for cmd in _CLIPBOARD_READERS if shutil.which(cmd[0])), None)


def _read_clipboard(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


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
    force: bool = typer.Option(
        False, "--force", help="Overwrite the export even if it holds unimported verdicts"
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

    # Overwriting this file destroys any verdicts sitting in it that were
    # never imported. That is not hypothetical: a re-export wiped a completed
    # 100-job review pass, which only survived because the reviewing session
    # still had it. Refuse rather than clobber.
    export_path = Path(export)
    unimported = _unimported_verdicts(export_path, verdicts)
    if unimported and not force:
        typer.echo(
            f"{export_path} holds {unimported} verdict(s) that were never imported.\n"
            f"Import them first:  jobagent import-reviews {export_path}\n"
            f"Or discard them:    jobagent review-queue --force"
        )
        raise typer.Exit(1)

    jobs = JobRepository(session).all()
    judged_postings = {
        posting_identity(j.company, j.title) for j in jobs if j.dedupe_key in verdicts
    }
    results = [score_job(job, profile) for job in jobs]
    pending = [
        r
        for r in results
        if r.eligible
        and r.job.dedupe_key not in verdicts
        # A verdict is a judgment about the job, not the row it arrived on.
        and posting_identity(r.job.company, r.job.title) not in judged_postings
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
    judged_postings = {
        posting_identity(j.company, j.title) for j in jobs if j.dedupe_key in judged
    }
    remaining = [
        score_job(j, profile)
        for j in jobs
        if j.dedupe_key not in judged
        and posting_identity(j.company, j.title) not in judged_postings
    ]
    remaining = [r for r in remaining if r.eligible]
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
    clipboard: bool = typer.Option(
        True, "--clipboard/--paste", help="Read the copied text straight off the clipboard"
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
    reader = _clipboard_reader() if clipboard else None
    if clipboard and reader is None:
        typer.echo("(no clipboard tool found — falling back to pasting)\n")

    saved = 0
    previous = ""
    for job in pending[:limit]:
        typer.echo(f"── {job.company} — {job.title}")
        typer.echo(f"   {job.url}")
        if open_browser:
            webbrowser.open(str(job.url))

        try:
            if reader:
                typer.echo("   Select the posting and copy it, then press Enter here.")
                answer = input("   [Enter=save, s=skip, q=quit] ").strip().lower()
                if answer == "q":
                    break
                if answer == "s":
                    typer.echo("   skipped\n")
                    continue
                body = _read_clipboard(reader)
                # Forgetting to copy would otherwise file the PREVIOUS job's
                # text under this job's name — silently wrong, and wrong in
                # the direction that puts the wrong role on a resume.
                if body.strip() and body.strip() == previous:
                    typer.echo("   clipboard unchanged — did the copy work? skipped\n")
                    continue
            else:
                typer.echo(
                    "   Paste the job description, then type END on its own line.\n"
                    "   (END with nothing above it skips this one)\n"
                )
                read = _read_until_sentinel()
                if read is None:
                    typer.echo("\nInput ended.")
                    break
                body = read
        except (KeyboardInterrupt, EOFError):
            typer.echo("\nStopped.")
            break

        if len(body.strip()) < _MIN_EVIDENCE_CHARS:
            typer.echo(f"   only {len(body.strip())} chars — skipped\n")
            continue
        previous = body.strip()
        destination = _posting_path(settings.postings_dir, job.source, job.source_job_id)
        destination.write_text(body, encoding="utf-8")
        saved += 1
        typer.echo(f"   saved {len(body):,} chars -> {destination}\n")

    typer.echo(
        f"Saved {saved}. `jobagent tailor --source X --job-id Y` now picks these up "
        "automatically — no --posting needed."
    )


@app.command("discover-companies")
def discover_companies(
    min_score: int = typer.Option(
        40, help="Only probe companies with at least one job scoring this high"
    ),
    limit: int = typer.Option(60, help="How many companies to probe in one run"),
    write: bool = typer.Option(
        False, "--write", help="Append verified boards to config/companies.yaml"
    ),
) -> None:
    """Probe companies from the job bank for a public ATS board.

    The LinkedIn alerts already name hundreds of companies hiring your roles
    in your country. Any of them running a Greenhouse/Lever/Ashby board can be
    fetched properly — full descriptions, no copying by hand — so this checks
    which ones do and adds them to the fetch list.
    """
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    jobs = JobRepository(make_session_factory(settings.db_path)()).all()

    known = {
        entry["name"].strip().lower()
        for entry in (yaml.safe_load(COMPANIES_PATH.read_text(encoding="utf-8")) or [])
    }

    best: dict[str, int] = {}
    seen_locations: dict[str, set[str]] = {}
    for job in jobs:
        result = score_job(job, profile)
        score = result.total if result.eligible else 0
        best[job.company] = max(best.get(job.company, 0), score)
        if job.location:
            seen_locations.setdefault(job.company, set()).add(job.location)

    candidates = sorted(
        (
            company
            for company, score in best.items()
            if score >= min_score
            and company.strip().lower() not in known
            and is_probeable(company)
        ),
        key=lambda c: -best[c],
    )[:limit]

    typer.echo(
        f"{len(best)} companies in the bank, {len(known)} already fetched. "
        f"Probing {len(candidates)} (best job scoring {min_score}+).\n"
    )

    # httpx logs every request at INFO; a 120-company run is thousands of
    # lines that bury the handful of hits.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    found: list[Candidate] = []
    state = ProbeState()
    with httpx.Client(timeout=8.0, follow_redirects=True) as client:
        for index, company in enumerate(candidates, start=1):
            hit = probe_company(
                client, company, state, known_locations=seen_locations.get(company, set())
            )
            if hit is None:
                continue
            found.append(hit)
            typer.echo(
                f"  [{index}/{len(candidates)}] {hit.company} -> {hit.platform} "
                f"({hit.slug}, {hit.job_count} jobs)"
            )
            typer.echo(f"        e.g. {', '.join(hit.sample_titles)}")

    if state.disabled:
        typer.echo(f"\n(rate-limited, skipped: {', '.join(sorted(state.disabled))})")
    typer.echo(f"\n{len(found)} of {len(candidates)} run a public board.")
    if not found:
        return
    if not write:
        typer.echo("Re-run with --write to add them to config/companies.yaml.")
        return

    lines = [
        f"# Found by probing companies already in the job bank — {date.today().isoformat()}",
    ]
    for hit in found:
        lines.append(f"- name: {hit.company}")
        lines.append(f"  platform: {hit.platform}")
        lines.append(f"  slug: {hit.slug}")
    with COMPANIES_PATH.open("a", encoding="utf-8") as handle:
        handle.write("\n" + "\n".join(lines) + "\n")
    typer.echo(f"Appended {len(found)} to {COMPANIES_PATH}. Run `jobagent fetch` to pull them.")


@app.command("apply")
def apply_command(
    source: str = typer.Option(..., help="Job source, e.g. greenhouse"),
    job_id: str = typer.Option(..., help="source_job_id of the posting"),
    resume: str | None = typer.Option(None, help="Which resume you sent"),
    via: str | None = typer.Option(
        None, help="Where you actually applied: workday, greenhouse, lever, email, ..."
    ),
    note: str = typer.Option("", help="Anything worth remembering"),
) -> None:
    """Record that you applied to a posting."""
    settings = get_settings()
    session = make_session_factory(settings.db_path)()
    job = next(
        (
            j
            for j in JobRepository(session).all()
            if j.source == source and j.source_job_id == job_id
        ),
        None,
    )
    if job is None:
        typer.echo(f"No stored job {source}:{job_id}")
        raise typer.Exit(1)

    applications = ApplicationRepository(session)
    if not applications.record(
        source=source,
        source_job_id=job_id,
        company=job.company,
        title=job.title,
        url=str(job.url),
        resume_used=resume,
        applied_via=via,
        notes=note,
    ):
        typer.echo(f"Already logged as applied: {job.company} — {job.title}")
        raise typer.Exit(1)

    typer.echo(f"Logged: {job.company} — {job.title}")
    typer.echo(f"Total applications: {applications.count()}")
    typer.echo(
        "\nWhat did the form ask that isn't on your resume? "
        "`jobagent remember` banks it for next time."
    )


@app.command("applications")
def applications_command(
    status: str | None = typer.Option(None, help=f"Filter: {', '.join(STATUSES)}"),
) -> None:
    """List what you've applied to and where each one stands."""
    settings = get_settings()
    rows = ApplicationRepository(make_session_factory(settings.db_path)()).all(status)
    if not rows:
        typer.echo("Nothing logged yet." if not status else f"Nothing with status {status!r}.")
        return

    counts = Counter(r.status for r in rows)
    typer.echo("  ".join(f"{name}: {n}" for name, n in counts.most_common()) + "\n")
    for row in rows:
        via = f" via {row.applied_via}" if row.applied_via else ""
        used = f" [{row.resume_used}]" if row.resume_used else ""
        typer.echo(
            f"  {row.applied_at:%Y-%m-%d}  {row.status:<10} {row.company[:26]:26} "
            f"{row.title[:38]:38}{used}{via}"
        )


@app.command("set-status")
def set_status_command(
    source: str = typer.Option(..., help="Job source"),
    job_id: str = typer.Option(..., help="source_job_id"),
    status: str = typer.Option(..., help=f"One of: {', '.join(STATUSES)}"),
    note: str = typer.Option("", help="What happened"),
) -> None:
    """Move an application along: screening, interview, offer, rejected..."""
    settings = get_settings()
    applications = ApplicationRepository(make_session_factory(settings.db_path)())
    try:
        moved = applications.set_status(source, job_id, status, note)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    if not moved:
        typer.echo(f"No application logged for {source}:{job_id}")
        raise typer.Exit(1)
    typer.echo(f"{source}:{job_id} -> {status}")


@app.command("remember")
def remember_command(
    question: str = typer.Option(..., "--question", "-q", help="What the form asked"),
    answer: str = typer.Option(..., "--answer", "-a", help="What you answered"),
    category: str = typer.Option("other", help="e.g. experience, logistics, authorization"),
) -> None:
    """Bank an application question and your answer, for reuse.

    Every form asks the same handful of things. Banking an answer once means
    the next application — and eventually the form-filler — already knows it.
    Demographic and EEO questions are refused on purpose.
    """
    settings = get_settings()
    answers = AnswerRepository(make_session_factory(settings.db_path)())
    if is_sensitive(question):
        typer.echo(
            "Refused: that looks like a demographic or sensitive question.\n"
            "Those are never banked and never auto-answered — answer it yourself."
        )
        raise typer.Exit(1)
    if answers.remember(question, answer, category):
        typer.echo(f"Banked. {answers.count()} answers on file.")
    else:
        existing = answers.lookup(question)
        typer.echo(f"Already knew that one: {existing.answer!r} (asked {existing.times_used}x)")


@app.command("answers")
def answers_command(
    search: str = typer.Argument("", help="Filter by text in the question or answer"),
) -> None:
    """Show the answer bank."""
    settings = get_settings()
    answers = AnswerRepository(make_session_factory(settings.db_path)())
    rows = answers.search(search)
    if not rows:
        typer.echo("Answer bank is empty. `jobagent remember -q ... -a ...` fills it.")
        return
    for row in rows:
        typer.echo(f"  [{row.category}] {row.question}")
        typer.echo(f"      -> {row.answer}   (asked {row.times_used}x)")


@app.command("answer")
def answer_command(
    question: str = typer.Argument(..., help="The question the form is asking"),
) -> None:
    """Answer one application-form question from what is already known.

    Checks the answer bank first (something you have actually answered), then
    the profile (years per technology, work authorization, salary). Says so
    plainly when it does not know, rather than guessing — a wrong answer on an
    application is worse than an unanswered one.
    """
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    answers = AnswerRepository(make_session_factory(settings.db_path)())

    if is_sensitive(question):
        typer.echo(
            "Refused: demographic and sensitive questions are never answered "
            "automatically. Answer that one yourself."
        )
        raise typer.Exit(1)

    banked = answers.lookup(question)
    if banked is not None:
        typer.echo(f"{banked.answer}")
        typer.echo(f"   (from the answer bank, asked {banked.times_used}x)")
        return

    resolved = resolve(question, profile, load_contact(), load_history())
    if resolved is None:
        typer.echo("Not known. Answer it yourself, then bank it:")
        typer.echo(f'   jobagent remember -q "{question}" -a "<your answer>"')
        raise typer.Exit(1)

    typer.echo(resolved.answer)
    typer.echo(f"   (from {resolved.source})")
    if not resolved.confident:
        typer.echo("   ^ low confidence — check this before using it.")


@app.command("fill")
def fill_command(
    fields: str = typer.Argument(..., help="Text file with one form label per line"),
) -> None:
    """Answer a whole application form from what is already known.

    Paste the labels off the form — literally what is on screen, one per line
    — and this returns an answer for each, the source it came from, and an
    explicit list of what it cannot answer. Nothing is guessed: a field it
    does not know is reported, not filled.
    """
    settings = get_settings()
    profile = load_profile(settings.profile_path)
    contact = load_contact()
    session = make_session_factory(settings.db_path)()
    answers = AnswerRepository(session)

    path = Path(fields)
    if not path.is_file():
        typer.echo(f"No such file: {fields}")
        raise typer.Exit(1)
    labels = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    banked = {}
    for raw in labels:
        label = clean_label(raw)
        hit = answers.lookup(label)
        if hit is not None:
            banked[label] = ResolvedAnswer(answer=hit.answer, source="answer bank")

    filled = fill_form(labels, profile, contact, banked, load_history())
    known = [f for f in filled if f.outcome is Outcome.ANSWERED]
    unknown = [f for f in filled if f.outcome is Outcome.UNKNOWN]
    refused = [f for f in filled if f.outcome is Outcome.REFUSED]

    width = min(max((len(f.label) for f in filled), default=10), 44)
    for field in filled:
        if field.outcome is Outcome.ANSWERED:
            flag = " ?" if not field.confident else "  "
            typer.echo(f"{field.label[:width]:<{width}}{flag}  {field.answer[:60]}")
            typer.echo(f"{'':<{width}}      ({field.source})")
        elif field.outcome is Outcome.UNKNOWN:
            mark = "*" if field.required else " "
            typer.echo(
                f"{field.label[:width]:<{width}}    {mark} -- NOT KNOWN, answer this yourself"
            )
        else:
            note = " -- REQUIRED, so you must answer it yourself" if field.required else ""
            typer.echo(f"{field.label[:width]:<{width}}      -- REFUSED (sensitive){note}")

    typer.echo(
        f"\n{len(known)} answered, {len(unknown)} unknown, {len(refused)} refused "
        f"(of {len(filled)} fields)."
    )
    if unknown:
        typer.echo("\nBank the ones you answer, so the next form knows them:")
        for field in unknown[:6]:
            typer.echo(f'   jobagent remember -q "{field.label}" -a "<answer>"')


@app.command("autofill")
def autofill_command(
    endpoint: str = typer.Option(CDP_ENDPOINT, help="Chrome debug endpoint"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be filled without typing anything"
    ),
) -> None:
    """Fill the application form open in your browser. Never submits it.

    Start Chrome once with debugging enabled, log in and navigate to the form
    yourself, then run this:

        google-chrome --remote-debugging-port=9222
        # this machine has Chrome Canary:
        /opt/google/chrome-canary/google-chrome-canary --remote-debugging-port=9222

    It attaches to that browser — your session, your profile — reads the
    visible fields, and types only what it can answer. Dropdowns, uploads,
    passwords and anything sensitive are left for you, and listed at the end.
    Submit is always yours.
    """
    import asyncio

    settings = get_settings()
    profile = load_profile(settings.profile_path)
    contact = load_contact()
    history = load_history()
    answers_repo = AnswerRepository(make_session_factory(settings.db_path)())

    async def run() -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.connect_over_cdp(endpoint)
            except Exception as exc:  # noqa: BLE001
                typer.echo(
                    f"Could not attach to Chrome at {endpoint} ({type(exc).__name__}).\n"
                    "Start it with:  google-chrome --remote-debugging-port=9222\n"
                    "then open the application form and run this again."
                )
                raise typer.Exit(1) from exc

            contexts = browser.contexts
            pages = [p for ctx in contexts for p in ctx.pages]
            if not pages:
                typer.echo("No open tabs found in that browser.")
                raise typer.Exit(1)
            page = pages[-1]
            typer.echo(f"Attached to: {page.url[:90]}\n")

            fields = await read_fields(page)
            if not fields:
                typer.echo("No fillable fields found on this page.")
                return

            labels = [f"{f['label']}{'*' if f['required'] else ''}" for f in fields]
            banked = {}
            for raw in labels:
                label = clean_label(raw)
                hit = answers_repo.lookup(label)
                if hit is not None:
                    banked[label] = ResolvedAnswer(answer=hit.answer, source="answer bank")
            resolved = fill_form(labels, profile, contact, banked, history)

            if dry_run:
                for field, answer in zip(fields, resolved, strict=False):
                    state = (
                        answer.answer[:50]
                        if answer.outcome is Outcome.ANSWERED
                        else f"-- {answer.outcome.value}"
                    )
                    typer.echo(f"  {field['label'][:40]:40} [{field['kind']:8}] {state}")
                typer.echo(f"\n{len(fields)} fields found. Nothing typed (--dry-run).")
                return

            report = await apply_answers(page, fields, resolved)
            for label, value in report["filled"]:
                typer.echo(f"  filled   {label[:38]:38} {value[:40]}")
            typer.echo("")
            for label, why in report["skipped"]:
                typer.echo(f"  SKIPPED  {label[:38]:38} {why}")
            typer.echo(
                f"\n{len(report['filled'])} filled, {len(report['skipped'])} left for you. "
                "Nothing was submitted."
            )

    asyncio.run(run())
