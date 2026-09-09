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
- Built AdzunaSource (US market, "data analyst remote" query). Only trusts
  salary_min when salary_is_predicted=="0" (Adzuna's real-vs-estimated
  flag) — never treats Adzuna's own algorithmic guess as a real disclosed
  figure. Real run: +50 new jobs.
- **Known accepted limitation**: Adzuna's search API truncates descriptions
  to ~500 chars, cutting off before the work-authorization disclaimer that
  usually sits near the end of a full posting. Result: 0/50 Adzuna jobs
  were caught by the US-work-auth filter on the first real run, which is
  a false negative, not evidence the filter works there — no fix without
  either a paid Adzuna tier or re-scraping full pages (which we're
  deliberately not doing). Treat Adzuna results with extra manual judgment
  on work authorization specifically.
- Verified real Greenhouse exclusions are legitimate, not a bug: 96/105
  total exclusions come from just Inovalon (73) and YipitData (23) —
  both apparently put a standard work-authorization disclaimer on nearly
  every posting, so their boards are broadly not viable for this user,
  not a per-role issue.


## 2026-09-09 (LinkedIn alerts + role-fit scoring)

- Built LinkedInAlertSource: reads LinkedIn job-alert digests from Gmail over
  IMAP (read-only; the mailbox is never modified). Parses the text/plain part
  of the multipart email, not the HTML — real alerts carry both and the plain
  part has a regular structure (dashed separators, then title/company/location
  /"View job:" link), so NO HTML parser dependency was needed. I had flagged
  beautifulsoup4 as probably necessary; the real email proved otherwise.
  First real run: 1,194 jobs parsed, 689 new. Total stored 240 -> 2,812.
- Alert emails carry NO job description, only title/company/location/link.
  Two consequences: (a) they can never be caught by the work-auth filter,
  (b) skills can only be matched from the title.
- Fixed a scoring flaw this exposed: zero-skill dampening was treating
  "no description to search" as evidence of a bad fit. Now only dampens when
  there IS a real description (>= 200 chars). Same "never assume" principle
  as undisclosed salary. Sources cluster far from that threshold (LinkedIn
  alerts 0 chars, next-shortest Adzuna ~495), so it isn't a fragile cutoff.
- Bug worth remembering: the LinkedIn wiring was first pasted AFTER
  `return sources` in active_sources() — unreachable dead code, so the source
  silently never ran. ruff's default rules do not flag unreachable code.
- Added `jobagent rank --source X --limit N`. Scores are only really
  comparable within a source: description-rich sources can earn skill points
  that description-less ones structurally cannot (LinkedIn best 73 / median
  53 vs 86-93 elsewhere). --source lets you compare like-for-like.
- Added a role-fit category (20 pts) matching the TITLE against
  profile.role_keywords (primary/secondary), accent-insensitive so Spanish
  titles work — most of the best Colombian jobs are in Spanish ("Analista de
  datos", "Ingeniero de datos", "Analista de Visualización"), which
  English-only matching was missing entirely.
- Rubric rescaled to keep 100: skills 40->30, role 0->20, seniority 25->20,
  location 20 (unchanged), salary 15->10. Salary was cut because it is
  neutral for nearly every job seen, so it was contributing a near-constant
  rather than ranking information.
- Result: the flat wall of 60s broke apart correctly. Top LinkedIn results
  are now all real data/BI roles in Colombia (Blend, TransUnion, Accenture,
  Inter Rapidísimo, COHNECTI); Java backend roles dropped out of the top 15.

## 2026-09-09 (location false-positive fix)

- Found via a real ranked result: "KnowBe4 - Analytics Engineer (Bengaluru,
  India)" scored location=20/20. Cause: _REMOTE_ANYWHERE_WORDS matched the
  bare word "global", which corporate prose uses constantly ("global team",
  "global Support Engineering"). Scale: 708 of 844 remote_anywhere matches
  came from that one word — a quarter of the database on a false signal.
- Fix: the location FIELD and the DESCRIPTION now get different trust levels.
  The location field is high-signal (Remotive literally uses "Worldwide" as a
  location value, which really does mean worldwide). The description is noisy
  prose, so it only matches specific phrases: "work from anywhere", "anywhere
  in the world", "remote-anywhere", "fully/globally distributed".
- Impact: remote_anywhere 844 -> 86. Artefact "Data Engineer - GenAI" fell
  from the #1 slot (90) to 75 once its bogus location points were removed.
- Lesson repeated from earlier bugs: single-word keyword matching against
  free-text marketing copy produces false positives at scale. Prefer phrases,
  and prefer structured fields over prose when the source offers both.

## 2026-09-09 (review pile: judge once, never again)

- Added a `job_reviews` table + ReviewRepository. Verdicts are
  worth_applying / unsure / not_a_fit, one per posting, and record() refuses
  to overwrite an existing verdict — that refusal is what makes "review once"
  actually hold.
- Own table rather than columns on JobRecord: conceptually a review is a
  different fact from a posting, and practically SQLAlchemy's create_all can
  add a table but cannot ALTER an existing one (no migration tool here).
- Workflow is a file round-trip so it batches and needs no API:
  `jobagent review-queue` -> data/to_review.json -> Claude fills verdicts ->
  `jobagent import-reviews`. The batch file carries everything needed to
  judge, so a review session needs no other project context.
- Decided NOT to delete not_a_fit jobs, despite it being tempting: the
  posting still exists at the source, so a deleted row is re-fetched and
  re-reviewed next run — deletion actively defeats "judge once". Hidden from
  `rank` by default instead, `--all` to see them. Nothing is ever deleted.
- `rank` is now review-aware: hides not_a_fit, shows the verdict inline.
- Review exports run descriptions through `_readable()` (unescape + strip
  tags). A rough regex tag-strip is acceptable THERE because the output is
  only read by a human/Claude; extraction still uses the original text, so
  scoring never depends on it.
- Documented the three session types in CLAUDE.md (review / discovery /
  building) and made explicit that the repo is the memory, not Claude.

### Open follow-ups
- ~~Feed the 385 LinkedIn-sourced companies into company-discovery~~ TESTED
  AND REJECTED (2026-09-09): checked the 25 most common LinkedIn companies
  against Greenhouse and Lever with generated slug variants — **0/25 hits**.
  Greenhouse/Lever are US-tech-startup ATSs; Colombian employers (elempleo,
  BairesDev, Scotiabank, Inetum, Accenture Colombia, EPAM, EY, Softtek,
  Stefanini, Auxis, Keralty, Enel) run SuccessFactors/Workday/Taleo instead.
  Do not re-attempt this as-is. Note these companies' jobs are NOT missing —
  they already arrive via the LinkedIn alerts themselves; a board would only
  add depth. Also: "elempleo" (25 postings) is Colombia's big job board, not
  an employer — same aggregator-as-company trap as Jobgether.
- ~~ATS detection / more platforms~~ INVESTIGATED AND DROPPED (2026-09-09).
  Tested the top LinkedIn companies against Ashby/Workable/Recruitee/
  SmartRecruiters too: 3/20 "hits" that were all FALSE — accenture.recruitee
  .com and ey.recruitee.com are abandoned trial accounts containing Recruitee's
  built-in "Senior Marketer (Sample)" demo job, and agileengine had 1 unrelated
  US posting. Real rate is 0/20; adding these platforms would import sample
  data. Colombian employers use SuccessFactors/Workday/Taleo.
  Workday IS where these multinationals are, and its careers sites call
  POST /wday/cxs/{tenant}/{site}/jobs — public and unauthenticated, but NOT
  published as a third-party API (unlike Greenhouse/Lever, which document
  theirs for this use). That is a grayer standard than anything else in this
  project, and the only thing it buys is more postings from companies whose
  jobs already arrive via LinkedIn alerts. Deliberately not pursued. Revisit
  only if the user explicitly accepts that tradeoff.
  Takeaway: the Colombian market is not reachable via startup-ATS APIs;
  LinkedIn alert parsing is the pipeline that covers it.
- Skill scoring measures overlap, never COVERAGE: a JD listing 40
  technologies where the user matches 6 scores the same as one listing
  exactly his 6. Needs required-vs-preferred extraction to fix properly —
  the best remaining case for the deferred LLM review pass.

## 2026-09-09 (resumes read; profile brought up to date)

- Read the four master resumes in private/resumes/ (DOCX; extracted with the
  already-installed `soffice --headless --convert-to txt`). They differ only
  in EMPHASIS — same employers, dates and achievements, reframed:
  DA = dashboards/KPI/BI · D_Eng = ETL/dimensional modeling/warehousing ·
  BPA = process mapping/requirements/Lean · Manf = OEE/downtime/TPS/safety.
- The resumes revealed the profile was STALE. Added to candidate_profile.md:
  Mazda Toyota Manufacturing (May-Aug 2025, Huntsville) — the most recent and
  most substantial role, absent entirely from the old doc ($35k overtime
  reduction, real-time production DB with 98% compression, bodyweld downtime
  dashboard, ergonomic safety programme); the ML vision system work at Toyota
  (26% inspection downtime reduction); GPA 3.74; International Academic
  Excellence Scholarship; Toyota Production Systems certification (May 2023);
  and the portfolio project's growth from ~535K to 6.3M events with Metabase
  and DuckDB.
- config/profile.yaml skills: 19 -> 62, taken verbatim from the resumes.
  Previously-invisible skills worth 300+ job mentions: Linux (106 jobs),
  Data Modeling (45), ETL (39), BASH (34), Data Warehousing (29), SQL Server
  (25), BigQuery (20), Pandas (8), Power Automate (7), NumPy (3).
  DELIBERATELY NOT ADDED: Tableau (49 jobs), Snowflake (70), dbt (42) — they
  appear in job postings but NOT on his resumes. Adding them would be
  fabrication, which is the first non-negotiable.
- Checked whether the bigger list flattens the skills signal: only 4% of
  eligible jobs now hit the 6-skill cap, so _SKILL_MATCH_CAP stays at 6.
  Decision made on measurement, not guesswork.
- Effect: Sezzle "Data Analyst" 85 -> 95 (full skill marks); Sezzle "Data
  Infrastructure Engineer Intern" rose to 87 on newly-recognised ETL/
  Data Pipelines/Data Warehousing/Data Validation.
- Phase 4 design decision (from the DOCX format question): tailoring must
  EDIT A COPY of the .docx in place, never regenerate the document, so the
  one-page/9.5pt/ATS-clean formatting survives. Known hard part: python-docx
  splits paragraph text across "runs", so naive replace breaks styling.
  LibreOffice is installed, so a tailored file can be converted to PDF and
  page-counted to enforce the one-page rule.
- Resume SELECTION design: derive each resume's keyword profile from its own
  text and match against the JD — but weight terms distinctive to ONE resume
  (star schema -> D_Eng, OEE -> Manf, requirements gathering -> BPA), because
  the four share ~70% of their wording. Deterministic, no LLM, auto-updates
  when a resume is edited.

## 2026-09-09 (Phase 4 begins: resume selection)

- New `jobagent/resumes/` package: `loader.py` (read .docx, parse SKILLS +
  PROFESSIONAL SUMMARY) and `select.py` (pick the best-fitting resume).
  `jobagent pick-resume --source X --job-id Y` shows the ranking and why.
- .docx read with stdlib zipfile + ElementTree — a .docx is just a zip holding
  word/document.xml. python-docx is NOT added yet; it is needed for tailoring
  (editing in place), so it waits until that step actually needs it.
- FIRST PROTOTYPE REJECTED: weighting every word by rarity across the four
  resumes (TF-IDF over 4 docs) surfaced junk reasons — "delivering",
  "fast-paced", "including", "issues" — accidents of phrasing, not signal,
  and it got the manufacturing case wrong. Replaced by using each resume's
  own SKILLS section: a vocabulary the candidate curated by hand.
  Distinctive terms then look right: star schema, dimensional modeling, OEE,
  downtime analysis, process mapping, change management, Sysmac.
- SECOND FIX: scores were normalised by each resume's total vocabulary
  weight, which meant the SHORTEST skills list won ties (D_Eng carries 23.9
  total weight vs BPA's 14.6 — a 60% handicap on an irrelevant factor).
  Switched to absolute matched weight. Ties now happen honestly.
- Thresholds calibrated on real postings: clear matches score 2.0-3.5,
  no-fit postings 0.5-1.0. WEAK_MATCH_SCORE=1.5, AMBIGUOUS_MARGIN=0.5.
- Tried harder penalties on shared terms (1/df^2, 1/df^3) to break ties.
  IT CANNOT WORK and this is worth remembering: tied resumes matched the
  IDENTICAL set of terms, so every weighting function returns the same
  ordering. The ties are an information problem, not a maths problem — the
  posting simply says nothing that separates DA from Manf. Kept 1/df.
- Real behaviour: "Senior Data Engineer" -> D_Eng 3.5 (decisive);
  "Data Analyst" -> DA/Manf tied, flagged; "Business Analyst II" -> BPA/DA
  tied, flagged; "Manufacturing Quality Engineer" (a hardware-QA role at a
  security company) -> all scores low, correctly reported as no fit.
- Tests use plain line lists, never the real .docx files, since those are
  gitignored personal documents that will not exist in CI or on a fresh clone.

## 2026-09-09 (Phase 4: tailoring)

- `jobagent tailor --source X --job-id Y [--write]`. Reports three things
  SEPARATELY because they lead to different actions:
    covered - asked for, owned, already on the resume. Nothing to do.
    missing - asked for, genuinely owned, resume doesn't say so. Safe to add.
    absent  - asked for, NOT owned. Never added; shown only so the gap can be
              judged. "Safe to add" means truthful, NOT advisable — adding PHP
              to a data-engineering resume is honest and unhelpful.
- Reports a COVERAGE figure ("you can meet 53% of what this posting asks
  for"), which is the metric the scoring rubric structurally lacks. Note the
  divergence: Sezzle "Data Analyst" scores 95/100 in `rank` but only 46%
  coverage — `rank` measures whether your skills appear, coverage measures
  what share of THEIR asks you meet. Worth folding into scoring later; that
  is a deliberate change, not a quiet one.
- --write produces a tailored COPY with skills reordered so job-relevant
  terms lead. Truthful by construction: identical terms in and out, only the
  order changes. A test asserts that invariant.
- No python-docx needed after all. Inspecting the real files showed the
  SKILLS paragraph is 8 runs alternating bold label / plain term list, one
  list per run — so editing means replacing text in specific plain runs and
  never touching formatting properties. stdlib zipfile + ElementTree rewrite
  the document. The dreaded "runs" problem did not apply to these documents.
- Deliberately NOT automated: rewriting bullet prose. Reframing requires
  judging whether new wording is still true — a human call, not a regex.
- Two bugs found by running it for real:
  * _reorder dropped the trailing " | " separator between categories,
    corrupting the layout. Now preserves leading AND trailing text verbatim.
  * page_count always returned None: LibreOffice writes "/Type/Page" with NO
    space and the code counted the spaced form. The page tree's "/Count" is
    the reliable figure. One-page rule is now actually enforced.
  * (third) the output filename sanitiser replaced "/" across the whole path,
    flattening data/tailored/x.docx into a file in the repo root. Sanitise
    the filename only, never the directory separators.
