# Job Agent

An AI-powered job search and application assistant — built to actually use during my own job search, and as a portfolio project.

## Status

✅ Phase 1 — Foundation: complete (config, logging, `Profile`/`Job` models, CLI, tests)
🚧 Phase 2 — Job data & sources: next up (`JobSource` interface, Remotive + Adzuna adapters, normalization, dedup, SQLite storage)

## Why

Job searching involves a lot of repetitive work: finding postings, checking fit, tailoring resumes, tracking applications. This project automates the repetitive parts while keeping a human in control of every important decision — it never submits an application, answers sensitive questions, or fabricates qualifications on its own.

## Architecture

See `CLAUDE.md` for the working agreement and phased roadmap (kept local, not committed — see Setup below).

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
```

Three files are intentionally gitignored and won't come from `git clone` — copy them over by hand from wherever you keep them (not through git, since they hold personal data):

- `CLAUDE.md` — working agreement for Claude Code
- `private/candidate_profile.md` — full background/preferences
- `config/profile.yaml` — edit after copying from the example above, or copy your real one over directly
