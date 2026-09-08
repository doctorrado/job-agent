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


## 2026-09-08

- Started Phase 3 (analysis & scoring). Extraction and scoring are both
  pure functions computed at `rank` time — no new DB columns, nothing
  cached, since it's cheap regex over already-stored text.
- Hard filters (exclude entirely, not scored): detected US work-auth
  requirement when not US-authorized; a disclosed salary below the
  monthly COP floor. Undisclosed salary is neutral, never assumed either way.
- Seniority is a distance-based penalty (years required vs. actual
  experience), not a hard exclude — title labels like "senior" are too
  noisy to safely hide a posting outright.
- Rubric (100 pts): skills 40, seniority 25, location 20, salary 15.
  Industry and a required-vs-preferred skill split are deliberately not
  scored — no reliable signal for either with today's data.
- Real test case that will score LOW under this rubric despite being a
  plausible fit (UL Solutions inspector role — zero skill-keyword overlap,
  transferable manufacturing experience a regex can't see): confirms the
  known limitation of pure keyword matching.
- Future idea (not yet built, deliberately deferred): a "review ambiguous
  fits with Claude" feature, as its own separate dashboard interface
  (published Artifact, `db` capability to sync jobs, `sample` capability
  for an embedded chat) — NOT inside this coding session, and NOT a
  standalone Anthropic API integration (real per-token cost the user
  can't justify). Combines with future Phase 5/6 (application tracking +
  hiring-manager research) into one interface. Real scope, its own future
  design pass.

  ## 2026-09-08 (Phase 3 closed out)

- Real-data debugging (not caught by synthetic unit tests) found and fixed:
  salary regex was treating any "$" amount as monthly COP (fixed: COP
  requires an explicit "COP" mention); work-authorization regex missed
  real disqualifying phrases like "must have resided in the United States"
  and "fully remote within the United States" (added, while avoiding
  false positives on generic company-description sentences).
- Added a USD hourly/annual salary floor ($15/hr) alongside the COP
  monthly floor — converts an explicit annual figure at 2,080 hr/year,
  deliberately does NOT convert per-word/per-task/per-image piecework
  rates (depends on how fast someone works).
- Found: ~73/238 eligible jobs (mostly Remotive noise — Sales Jedi, Head of
  Marketing, Freelance Writer/Copywriter) had zero skill-keyword overlap
  but still scored 40-55/100 from neutral defaults alone. Fixed: total
  score is halved (not hard-excluded — keyword matching can miss real
  fits, see the UL Solutions case) when zero skills matched.
- **Phase 3 (analysis & scoring) is complete**: extraction, hard filters,
  transparent rubric, and zero-skill dampening are all real, tested, and
  verified against actual live data, not just synthetic examples.
- Next: Phase 4 (resume intelligence), or round out Phase 2's optional
  source backlog (Jobicy, Adzuna, more companies via a discovery pass).

## 2026-09-08 (rounding out Phase 2)

- Built JobicySource (real filters, structured salaryMin/Max/Currency/Period
  and pubDate — no regex-guessing needed for this one). Also fixed a real
  regression while adding it: "remotely? within the US" only matched the
  literal substring "remotel" + optional "y" (regex mistake), which broke
  detection of "remote within the US" (no -ly) that was previously working.
  Fixed to `remote(?:ly)?` — both forms now correctly detected.
- Ran a company-discovery pass (WebSearch for site:boards.greenhouse.io /
  site:jobs.lever.co + role keywords, each slug verified live before
  adding): grew config/companies.yaml from 2 to 21 companies. Real result:
  291 -> 1,941 total jobs stored on the next fetch.
- Found and deliberately excluded "Jobgether" (Lever slug, 4,543 "jobs"):
  it's a recruiting/matching aggregator posting many *other* real
  companies' jobs through one Lever board, not a single employer.
  CompanyBoardsSource assumes one board = one real employer, so including
  it would mislabel every posting's company field. Real limitation to fix
  later if aggregator boards are ever worth supporting properly.
- Investigated Colombia's SPE job portal for a public API a second time:
  confirmed none exists — only a login-gated citizen portal and a separate
  employer-registration portal, no developer API. Their own site has a
  broken SSL cert. Closing this out: no automated path; FileSource by hand
  is the only option if ever wanted, same as the LinkedIn approach.
- Remaining: Adzuna (needs the user's own API keys) and Jooble (needs the
  user's own API key, 500-lifetime-call budget) — both require the user to
  sign up themselves, walked through interactively rather than automated.

