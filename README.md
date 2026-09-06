# Job Agent

An AI-powered job search and application assistant — built to actually use during my own job search, and as a portfolio project.

## Status

🚧 Phase 1 — Foundation (in progress)

## Why

Job searching involves a lot of repetitive work: finding postings, checking fit, tailoring resumes, tracking applications. This project automates the repetitive parts while keeping a human in control of every important decision — it never submits an application, answers sensitive questions, or fabricates qualifications on its own.

## Architecture

See `CLAUDE.md` for the working agreement and phased roadmap.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

\`\`\`bash
uv sync
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
\`\`\`
