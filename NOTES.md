# Dev Log

Read this first when picking up work on a new machine or session. Add a
dated entry with important findings/decisions here before committing
significant work — don't let reasoning live only in chat.

## 2026-09-07

- Built `JobSource` interface + `FileSource` + `RemotiveSource` (Phase 2, in progress).
- Finding: Remotive's free API ignores category/search filters — always
  returns the same fixed ~18-job feed regardless of query. Not a bug in
  our code. Their notice also asks for max 4 calls/day.
- Finding: Adzuna's API does NOT cover Colombia (covers UK/US/CA/AU/DE/FR/
  ES/IT/NL/AT/BE/BR/IN/MX/NZ/PL/SG/ZA).
- Open decision: second live source — (1) Adzuna scoped to a covered
  country as a supplemental net, (2) investigate Computrabajo instead,
  (3) skip for now, do dedup + storage with Remotive + FileSource.
- Added .gitattributes (LF) to stop CRLF churn between the two machines.
- Next: resolve the above, then dedup + SQLite storage.

## 2026-09-07 (cont'd)

- Built CompanyBoardsSource (Greenhouse + Lever) + config/companies.yaml.
  Verified live: 224 real jobs from the starter list (Sezzle, Linqia).
- Established a repeatable growth process: periodically ask Claude to run
  a company-discovery pass (WebSearch for site:boards.greenhouse.io /
  site:jobs.lever.co + role keywords, extract company slugs, verify each
  live, append new hits to config/companies.yaml). Not automated on a
  schedule on purpose — triggered deliberately, roughly weekly or whenever.
- Decided against LinkedIn/Indeed/Glassdoor scraping (JobSpy-style): real
  risk is IP-level blocking + our own account getting restricted, not just
  ToS text. Chose email-alert parsing (LinkedIn/Indeed job-alert emails via
  IMAP) as the legal path to that market instead — not yet built, needs:
  which email provider, and whether saved-search alerts are set up yet.
- Remaining source backlog (not blocking Phase 2 close-out): JobicySource,
  AdzunaSource (needs API keys — sign up at developer.adzuna.com), Jooble
  (500 lifetime calls, manual-trigger only), Colombia SPE (unconfirmed API,
  deprioritized — likely lower-paying local roles vs. target multinationals).
- Next: dedupe + SQLite/SQLAlchemy storage to actually close out Phase 2,
  then a `jobagent fetch` command that runs all sources together.

## 2026-09-07 (Phase 2 closed out)

- Built pipeline/dedupe.py (exact source-key + normalized company/title/
  location cross-source match — no fuzzy/embeddings). Deliberately only
  dedupes within one fetch run; a posting reappearing under a different
  source next week isn't caught by this alone.
- Built storage/ (SQLAlchemy ORM `JobRecord` on SQLite at data/jobs.db,
  `JobRepository.upsert` is the dedup-safe write — unique on
  source+source_job_id).
- Built pipeline/fetch.py + `jobagent fetch` CLI command: runs every active
  source, dedupes, stores, reports stats. Skips a failing source instead of
  aborting the whole run.
- First real run: 241 fetched (17 Remotive + 224 CompanyBoards) → 240 after
  dedupe → 240 new → 240 stored.
- **Phase 2 is complete.** Remaining source backlog (JobicySource,
  AdzunaSource, Jooble, Colombia SPE, EmailAlertSource) is optional/ongoing,
  not blocking — can be added any time via the existing JobSource interface.
- Next: Phase 3 — analysis & scoring (transparent match-score breakdown,
  seniority/location/work-auth detection, salary-tier and multinational-
  preference signal per the user's stated priorities).
