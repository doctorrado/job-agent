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

## 2026-09-10 (naming + a real-data scoring audit)

### Tailored-file naming

- The sanitised `{resume}__{company}__{job_id}` name is gone. Andres's own
  name was nowhere in it, which is exactly what a recruiter's download folder
  needs to show. `tailor.output_path()` now derives it from the source file:
  `Andres_Torrado_Resume_D_Eng.docx` -> `Andres_Torrado_D_Eng.docx`, with
  `(1)`, `(2)` only when an earlier copy is still sitting there. Derived, not
  hardcoded, so renaming the masters carries through. Tailored copies are
  meant to be deleted once submitted.
- Known gap, deliberately accepted: the filename no longer records WHICH job
  it was tailored for. Phase 5's application tracker is the right place for
  that (job -> file -> date submitted), not the filename.

### The audit that prompted everything below

Claude had been reasoning about scoring from ONE posting (Lemon.io Senior
Data Engineer, 83/100). Andres pushed back — "you still haven't checked the
jobs personally in our job bank" — and scoring every one of the 2,812 stored
jobs told a very different story than the single sample did. Lesson, again,
and stronger than the Phase 3 version: a plausible diagnosis from one example
is not a finding. Rank the whole bank and read the top 100.

What the full pass showed, in order of real cost:

- **36 of the top 100 were places Andres cannot work.** Doha, Beirut,
  Bengaluru, Riyadh, San Francisco, New York — all scoring 80/100, ABOVE
  genuine Bogota roles at 75. Location was worth 20 points and being in the
  wrong country only cost 15 of them; the other four categories carried it.
- **12 of the top 100 matched none of his target roles** (Security
  Infrastructure Engineer, Marketing Growth Analytics, SRE Platform).
  Role is 20 of 100, so scoring zero still left 80 reachable.
- **Two companies owned 37% of the top 100** (Sezzle 22, Artefact 15) —
  Greenhouse returns every opening from all 21 companies in companies.yaml.
- **10 internships in the 70+ band.**
- Senior-title short-circuit and boilerplate skill inflation were both real
  but, measured, minor: only 2 senior-titled jobs reached 70+. The original
  single-sample diagnosis had ranked these FIRST. They were nearly last.

### Fixes

- **Internships hard-excluded** (`requires_internship`), not downweighted —
  Andres graduated Dec 2025. Matches intern/internship/practicante/pasantia/
  becario/co-op on word boundaries, so "Internal Audit" and "International"
  are safe. 47 excluded, all manually verified as genuine placements, zero
  false positives.
- **Multiplicative damping generalised.** The single zero-skills factor is now
  a list of factors with reasons, surfaced in `rank` output:
  `_NO_SKILLS_DAMPING 0.5`, `_WRONG_PLACE_DAMPING 0.6` (remote_scope=="other"),
  `_OFF_ROLE_DAMPING 0.6` (role_relevance=="none"). Points alone could not fix
  this — zeroing location still left an on-site Doha role at 75.
- **The off-role damper yields to skill evidence** (`_OFF_ROLE_SKILL_OVERRIDE`
  = half the skill cap). Found by inspecting what got damped: "Dev Python
  (PySpark/Airflow/PostgreSQL) - Remoto", Colombia, was pushed to 36 despite
  naming three of his skills in the title alone. An unfamiliar title is weak
  evidence; real overlap outvotes it.
- **Senior-title check no longer short-circuited.** `_score_seniority` used to
  `return` inside the years branch, so Artefact's "Senior Data Engineer"
  saying "3+ years" scored a full 20/20. 29 senior-titled postings did.
- **`years_required` now matches its own docstring** — it said "lowest", the
  code took the FIRST match. Lemon.io only scored correctly because "5+ years
  as a Data Engineer" happened to be bulleted above "2+ years with Databricks".
  Reorder those bullets and it would have jumped to 95/100.
- **Boilerplate tech lists stripped before skill matching** (`own_requirements`).
  Lemon.io's "NOT YOUR TECH STACK?" paragraph names ~60 technologies across
  every role they recruit for and handed the posting free matches on Java,
  PHP, JavaScript and Data Analysis — maxing out a 30/30 skills score off
  four terms that were not in the job's requirements at all.

### Result

Top 60 is now 44 LinkedIn-alert jobs, 8 Greenhouse, 5 Jooble — real Colombian
data roles at Mercado Libre, Falabella, Accenture, Philip Morris, Twilio,
Scotiabank, BairesDev. Company concentration dropped from Sezzle-22 to
Sezzle-8. Zero top-100 jobs are now located where he cannot work, and zero
match none of his target roles.

### Known, accepted

- LinkedIn-alert jobs carry no description, so they plateau at 65-70 and tie
  in large blocks. That is honest — the ordering within a tie is arbitrary
  because there genuinely is no more information. Fixing it would mean
  fetching the posting body, i.e. scraping, which stays ruled out.
- `tailor` does not consult the score. It answers "which resume, what gap",
  not "should you bother".

### Robustness: company boards now fail independently (2026-09-10)

A routine `fetch` hit a ReadTimeout on one of the 21 boards in
companies.yaml and lost ALL of them — greenhouse + lever, ~1,920 stored jobs,
left unrefreshed. `fetch_all()` already skips a failing SOURCE; that same rule
just was not applied one level down, inside CompanyBoardsSource's loop over
companies. Now wrapped per company with a `company_board_failed` warning.
The very next run pulled 1,851 jobs cleanly, so the timeout was transient —
but 66% of the bank should never hang on one company's slow response.

## 2026-09-10 (first real review batch, and what it exposed)

First 40 jobs reviewed in a separate context-light session, as CLAUDE.md
intends: 16 worth_applying, 20 unsure, 4 not_a_fit. Running the Phase 4
pipeline across those 16 immediately found two things.

### coverage reported 100% off a single word

`GapReport.coverage` divided covered+missing by total asked with no floor on
the denominator. IQVIA's "Data Analyst-Business Intelligence" is a LinkedIn
alert — title only, zero description — so it yielded exactly one term,
covered, and reported a confident **100%**. Now `coverage` returns None below
`_MIN_ASKS_FOR_COVERAGE` (4) and the CLI says how many technologies the
posting actually named alongside the percentage.

This is the SAME mistake as the `_MIN_DESCRIPTION_CHARS` fix in scoring:
treating "no evidence" as "good evidence". It was fixed for skill dampening
in Phase 3 and never applied one step later in the gap report. Worth watching
for a third instance anywhere a ratio is computed from posting text.

### 11 of the 16 leads had no description at all

LinkedIn alert emails carry a title and a link. Resume selection, gap analysis
and tailoring all read the description, so for two-thirds of his best leads
the whole of Phase 4 had nothing to work with — every one auto-picked BPA
with a "no resume fits this well" warning, which was an artefact of empty
input, not a real judgment.

Added `jobagent tailor --posting <file>`: copy the real posting body out of
the browser into a text file and it replaces the empty description. Verified
on the IQVIA job — went from "only 1 technology named, open the URL yourself"
to a real resume choice and 81.8% coverage over 11 named technologies.
Deliberately a manual paste, the same escape-hatch role FileSource plays for
fetching; scraping the LinkedIn page stays ruled out. Put the files in
`private/postings/` (already gitignored via `private/`).

Not tested: the `--posting` flag itself. There are no CLI tests anywhere in
this project — the convention is to test pipeline functions and drive the CLI
by hand. Noting the gap rather than pretending otherwise.

### Workflow gap: nothing told Andres how much was left (2026-09-10)

He finished the first 40-job batch believing 40 WAS the eligible pool. Fair
reading: `review-queue` prints "N jobs awaiting review" in whichever terminal
built the batch, the reviewing session never sees that line, and
`import-reviews` — the one command he actually runs — reported only what it
had just recorded. Real numbers: 2,950 stored, 164 hard-filtered, 2,786
eligible, 40 reviewed. `import-reviews` now closes with how many eligible
jobs remain, how many score 60+, and the command for the next batch.

Lesson for anything split across sessions: a number printed in one session is
not information the user has. Print it where they will act on it.

### Duplicate listings collapsed in review batches

The review session flagged 8 of 40 rows as repeat listings. Two causes:

- `fuzzy_key` used raw company text, so "IQVIA, Inc." (Jooble) and "IQVIA"
  (LinkedIn alert) were different postings — as were "Bogota, D.C." and
  "Bogota, D.C.", which differ only by an accent. `normalize_text` now strips
  accents and `normalize_company` strips legal-entity suffixes (Inc/LLC/SAS/
  Ltd/...), looping so "Foo S.A.S. Ltd" fully reduces. `_strip_accents` in
  extract.py was promoted to `strip_accents` and reused rather than copied.
- Sezzle posts the same Data Analyst role once per LATAM country, which are
  genuinely separate listings with separate apply links. Storage keeps them
  all; `review-queue` now groups by (company, title), spends each batch slot
  on a distinct opening, and carries the other locations along as
  `also_posted_in` so no apply link is lost. Highest score wins the slot,
  which naturally prefers the Colombia-located variant.

Across the current pool: 2,746 unreviewed = 2,092 distinct openings + 654
repeat listings. Batches are ~24% denser.

### `read-postings`: automating the clicking, not the reading (2026-09-10)

Andres asked whether the script could follow each job-alert link and read the
description itself. It could technically; it will not. Fetching those pages
programmatically is scraping — against LinkedIn's terms, and the risk we
already recorded on 2026-09-07 is not theoretical: IP-level blocking, and his
own account getting restricted in the middle of an active job search. The
line that holds: automating the clicking is fine, automating the reading is
not.

`jobagent read-postings` walks the reviewed leads that have no description,
opens each in HIS browser (where he is already logged in), and saves whatever
he pastes to `private/postings/{source}_{job_id}.txt`. `tailor` then picks
that file up automatically when the stored description is empty — `--posting`
is only needed for a file kept somewhere else. Defaults to `worth_applying`,
`--limit 10` a sitting, `--verdict unsure` to work the maybes.

Verified end to end on Blend's Data Engineer (SQL-focused): "title only,
open the URL yourself" became "Resume: D_Eng (auto-picked), 83.3% coverage
over 6 named technologies, NOT YOURS: dbt".

Bug caught before it shipped: the first version used `sys.stdin.read()`,
which consumes to EOF — so after the first paste every later read returns ""
and jobs 2..N would have silently skipped, reporting success. Replaced with a
sentinel-line reader (`END`) that behaves identically in a terminal and a
pipe, which is also what made it testable from the shell.

### Company discovery aimed at his OWN alerts (2026-09-10)

Previous discovery passes searched generically (`site:boards.greenhouse.io` +
role keywords). This pass instead took the 398 companies that actually appear
in Andres's LinkedIn alerts and probed the top 30 against six public ATS APIs
(Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable) with
generated slug variants. Far better hit rate, because these are companies
already hiring for his roles in his country.

Verified real, added:
- **Wizeline** (greenhouse, 31 jobs, 7 in Colombia) — including the
  `Data Analyst (SQL) | Colombia` posting that was his #1 unreviewed lead and
  arrived from the alert with NO description. Now carries 3,010 chars.
- **Nubank** (ashby, 122 jobs) — required adding an Ashby fetcher.

Rejected in the same pass, all returning HTTP 200: Accenture and EY on
Recruitee (both trial accounts containing the same "Senior Marketer (Sample)"
placeholder — exactly the signature recorded on 2026-09-08), AgileEngine on
SmartRecruiters and Bold on Greenhouse (wrong boards, one unrelated US job
each). A 200 is not a real board; always read the titles.

Ashby added as a third platform in company_boards_source. Its posting API
returns `descriptionPlain`, so postings arrive as clean text.

Store grew 2,950 -> 3,108.

### A bug that measured out to nothing

Greenhouse stores `content` HTML-escaped (`&lt;p&gt;`), so descriptions sit in
the database as entity soup, and skill matching reads them raw. Looked like a
real defect across 1,874 jobs. Measured before fixing: decoding the HTML first
changes the matched skills on **1 job out of 2,391**, because `\bpython\b`
matches inside `&gt;Python&lt;` perfectly well. Left alone.

Recording this deliberately as a negative result. The same instinct that
produced the single-sample Lemon.io diagnosis produced this one; the
difference is that this time the measurement happened before the change.

### read-postings reads the clipboard

`wl-paste` is present (Wayland), so the flow is now: tab opens, Ctrl+A /
Ctrl+C on the page, press Enter in the terminal. No pasting into the shell.
Falls back to `--paste` with the END sentinel where no clipboard tool exists
(`xclip` and `xsel` are also tried).

Guard worth keeping: if the clipboard is byte-identical to the previous job's,
the entry is skipped rather than saved. Forgetting to copy would otherwise
file the previous posting's text under this job's name — silently wrong, and
wrong in the direction that puts the wrong role's keywords on a resume.
Anything under 200 chars is refused too.

## 2026-09-10 (Phase 5: application tracking + answer bank, and the ATS probe)

Context for both: Andres pulled the project back to its actual goal, which is
not "a better ranked list" — it is that he does as little as possible, up to
clicking Submit himself. Workday is explicitly non-negotiable (most postings
route there to apply), and "Workday is a nightmare" was the wrong framing:
Workday is ONE product with `data-automation-id` attributes in its DOM,
which makes it more automatable than a bespoke careers page, not less.

### `discover-companies` — the probe

Earlier discovery searched the open web and guessed company names. This works
the other way round: the LinkedIn alerts already name 542 companies hiring his
roles in his country, so probe THOSE against the six documented public board
APIs. Relevance is established before the first request.

Live result: 21 of 150 probed run a real public board (~14%, double the 7%
estimated from the first hand-run sample of 30).

**Two false-positive classes found on live data, both now handled:**

1. *Trial accounts.* Accenture and EY both answer 200 on Recruitee with the
   identical "Senior Marketer (Sample)" placeholder. `looks_real` requires 4+
   jobs and no placeholder markers.
2. *Truncated slugs.* The `words[0]` fallback matched "Inter Rapidisimo"
   (Bogota logistics) to **Inter**, a Brazilian bank with 136 Portuguese jobs
   and none in Colombia; "Ultimate Jet Vacations" to a US HVAC contractor;
   "Mas Empleo ANDI" to the same HVAC board; "Automation Anywhere" to a Dutch
   Recruitee account. Five of the 21 hits were wrong — a 24% error rate that
   would have flooded the bank with HVAC and Dutch sales-admin jobs.
   Fix: the first-word slug now requires **location corroboration** — the
   board must post somewhere we have actually seen that company hire. Verified
   on live data: all five rejected, Experian (5 real Colombia openings),
   Skydropx, Twilio, Blend, PayJoy and Factored all still found. Esri Colombia
   is also rejected, correctly — Esri's global board has 0 Colombia jobs, so
   it was never going to help.

Also: Workable rate-limited (429) a 120-company run into uselessness. The
probe now backs off after 3 rate-limit responses and drops that platform for
the run. These are free endpoints run for employers' benefit, not ours.

### LinkedIn alert parser: two email variants shifted every field

"Your job alert has been created: X in Colombia." and "A new job matches your
preferences." were unrecognised chrome. The parser reads title/company/
location positionally, so one unrecognised leading line shifts everything: six
stored jobs had "You'll receive notifications when new jobs are posted..." as
their EMPLOYER, with the real job title in the location column. Now filtered
by `_NOISE_LINE` (note U+2019, the emails use a curly apostrophe). A re-fetch
repairs the affected rows because source_job_id was never wrong.

### Phase 5 tables

`Application` (one per posting actually applied to) and `ApplicationAnswer`
(the answer bank), both new tables rather than columns, for the same reason
JobReview is: create_all can add a table but cannot ALTER one, and these are
different facts with different lifetimes — a verdict is written once, a status
changes for months.

`applied_via` is deliberately separate from `source`. Where a job is LISTED
and where you APPLY are different systems: a Greenhouse listing routinely
hands you to Workday. Recording which is what makes Phase 7 targetable.

### The answer bank is the point, and it is late rather than early

Andres's own framing, and it is right: the Selenium half of Phase 7 is
mechanical; knowing WHAT to type is the actual intelligence, and it cannot be
invented — it only accumulates from real questions really answered. He has
applied to ~360 jobs and none of that is recovered. What is recoverable is the
next ten.

`normalise_question` collapses phrasings so "How many years of experience do
you have with Python?" and "Years of Python experience?" hit one banked
answer (filler words dropped, remainder sorted).

**Demographic and EEO questions are refused outright**, not merely
un-auto-answered. CLAUDE.md forbids auto-answering them, so the bank declines
to hold them at all — an empty table cannot tempt a future form-filler.
Bug caught by its own test: `\bdisab\b` cannot match "disability", because
the trailing word boundary fails mid-word. Every EEO question was passing
through. These are prefix patterns now, with no trailing \b.

## Backlog — agreed, not built

Kept here rather than in chat so it survives a new session. Ordered by the
project's actual goal: Andres does as little as possible, up to clicking
Submit himself.

1. **Workday form-filling (Phase 7).** Non-negotiable — most postings route
   there to apply. Workday is ONE product with `data-automation-id`
   attributes in its DOM, so it is more automatable than a bespoke careers
   page, not less. Blocked on: a real mapped form (a spike, not a build) and
   an answer bank worth drawing on. Never auto-submit; pause at CAPTCHA/MFA.
2. **Answer bank, static tier.** Name, Bogota address, phone, email, login
   password (via .env, never chat), education, employers, titles, dates,
   resume bullets. ~80% of any application and buildable today from
   profile.yaml + candidate_profile.md — no forms needed.
3. **Years-per-skill in profile.yaml.** Currently 65 skills as a flat list
   with no years attached. "How many years of X" is the single most common
   variable question on a form; a years+confidence column answers most of
   them automatically instead of asking him each time.
4. **Dashboard (deferred by Andres 2026-09-10, wants it eventually).** A
   published Artifact: applications and their statuses, the ranked shortlist,
   the answer bank. The tracker is FOR him — `jobagent applications` printing
   text is a poor way to see what has stalled across 50 applications. Claude
   does not need it; it can read the DB.
5. **`jobagent today`.** One command that says what to do now, instead of him
   remembering a five-step sequence.
6. **Run the probe over the remaining ~390 companies**, and re-run it after
   each fetch as new companies appear in the alerts.
7. **Bullet reordering** (same safe "same words, different order" property as
   the skills line). Bullet *rewording* stays with the LLM pass, gated on his
   approval per bullet.
8. **Seniority as a hard gate, not a scored category (Andres's idea, v2).**
   His argument: seniority is disqualifying rather than merely costly, so it
   belongs with the early-return filters (work auth, internship, language,
   salary floor) instead of contributing points that skills can outweigh.
   Measured against the 440 verdicts on 2026-09-12 — what each candidate rule
   would throw away:

   | rule | excluded | not_a_fit | unsure | **wanted** |
   |---|---|---|---|---|
   | senior TITLE | 52 | 47 | 5 | **0** |
   | years > max_years (3) | 30 | 29 | 1 | **0** |
   | senior title OR years > 5 | 53 | 47 | 6 | **0** |
   | detect_seniority (reads prose) | 59 | 50 | 8 | **1** |

   A senior-title gate costs nothing he wanted. Only the prose-based detector
   costs a real job, and the damper already stopped using it. Left as v2 at
   his call, not because the evidence is thin. If built: exclude on
   `has_senior_title(job) or years_required > max_years_experience`, and give
   `rank` a way to show what was gated, the way `--all` reveals not_a_fit.

Deliberately NOT on this list: scraping LinkedIn/Indeed/Glassdoor, and
Workday's undocumented `/wday/cxs/` endpoint for FETCHING. Applying through
Workday's own form as a genuine applicant is a different question from
scraping their job data, and is item 1.

Also worth knowing: `fetch` reads LinkedIn alert emails over IMAP as one of
its sources — there is no separate command. The window is the last 30 days
(`since_days`), so a six-week gap between fetches would miss alerts.

## 2026-09-10 (second review batch — and two workflow bugs it exposed)

140 verdicts now recorded (40 + 100). Second batch: 42 worth_applying,
44 unsure, 14 not_a_fit.

### `review-queue` destroyed a completed review pass

Running `review-queue` overwrites `data/to_review.json` unconditionally. A
re-export during this session wiped a finished 100-job pass whose verdicts had
never been imported. They survived only because the reviewing session still
had them in its scratchpad — pure luck, not design.

`review-queue` now counts verdicts in the target file that are absent from the
database and refuses to write, naming both ways out (`import-reviews`, or
`--force` to discard). Verified live: the guard fires and the file is left
byte-for-byte intact.

Sharpest lesson of the day, and it generalises: a command that overwrites a
file the user has spent effort filling in must check before clobbering. The
review loop deliberately spans two sessions, so the file IS the handoff.

### A verdict is about a job, not about a row

Twilio's BI Analyst 2 exists twice — `linkedin_alerts:2811` and
`greenhouse:3127` — because the same posting reached us from two sources with
different source_job_ids. Verdicts key on (source, source_job_id), so judging
one left the other in the queue. Real scale: **35 groups spanning more than
one source, 13 of them already half-judged**, and it grows as more boards come
online.

`posting_identity(company, title)` (in dedupe.py, coarser than `fuzzy_key` —
no location) now excludes any posting whose sibling row has a verdict, in both
`review-queue` and the `import-reviews` remaining count. Deliberately a
read-time rule: it does NOT write verdict rows for jobs nobody reviewed.

### Description coverage drives review quality — measured

Four verdicts changed once real JD text arrived, all on the same postings:

| Job | Was | Now | Why |
|---|---|---|---|
| N-iX Data Engineer (Snowflake) | unsure | worth_applying | JD asks 1-3+ yrs SQL/Python/Airflow |
| PALO IT Analista BI | worth_applying | unsure | actually "Semi Senior", ~182 recurring reports |
| Goodway Global Data Engineer | unsure | not_a_fit | body describes a Senior DE who mentors |

This is the clearest evidence yet for the ATS probe: the LinkedIn alert rows
produced `unsure`; the same companies' own boards produced confident calls in
both directions. Twilio's BI Analyst 2 came through the alert as a bare title
and through Greenhouse as a 10,262-character JD scoring 95.

Two hard gates worth remembering, both found only in JD bodies: Skydropx
RevOps Data Analyst requires "Portugues C1 o superior", and N-iX DataOps wants
3+ years of Terraform, dbt and Snowflake.

## 2026-09-12 — the scorer validated against 440 real verdicts

The review session flagged that scores looked capped and that
description-rich mismatches outranked description-less good matches. Both
observations were right; the diagnosis was not, and checking properly turned
up something worse.

### The measurement that mattered

With 440 verdicts on disk there is finally ground truth to test against.
Baseline:

```
worth_applying  n=173  median 65.0
unsure          n=162  median 63.0
not_a_fit       n=105  median 57.0
separation gap +8.0 | not_a_fit above the WA median: 16/105 | top-100 precision 53%
```

An 8-point gap. The rubric tuned all through 2026-09-10 barely distinguished
jobs Andres would apply to from ones he rejected outright, and only half the
top 100 were jobs he wanted. Every previous scoring change had been judged by
eyeballing the top of the list; none had ever been measured.

A harness now lives in the scratchpad (not committed — it depends on the
private DB). Re-run it after ANY scoring change.

### Four causes, each measured separately

1. **Senior titles were underpunished.** Capping seniority at 4/20 costs 16
   points; a full skills score gives 30. "Senior Analytics Engineer" scored
   79, above a well-matched Bogota BI Analyst at 75. Senior now damps the
   whole score (0.65), as do postings wanting `max_years + 2` or more years
   whatever the title says. Evidence it is safe: of jobs with a senior title,
   the verdicts were 50 not_a_fit / 8 unsure / **1** worth_applying.
2. **Senior detection read the description.** `detect_seniority` falls back to
   the body, where "work with senior stakeholders" is not evidence. The single
   worth_applying casualty was N-iX's "Data Engineer (Snowflake)" — senior
   only by prose. The damper uses `has_senior_title` (title only); the points
   still use the old function.
3. **The off-role skill override rescued every tech job.** Added on 09-10 to
   save "Dev Python (PySpark/Airflow/PostgreSQL) - Remoto", it counted skills
   anywhere — so UX Researcher, Total Rewards Analyst, Controllership
   Specialist and DevOps Engineer all scored 65-75 with role=0, because their
   bodies mention Python. It now counts only skills named in the TITLE, which
   is exactly what distinguished the case it was built for. **This was the
   single biggest fix.**
4. **No language-requirement detection.** Skydropx RevOps Data Analyst scored
   80 and is a flat no: "Indispensable: Portugues C1 o superior". Now a hard
   exclusion, with an optional marker ("Deseable: Portugues avanzado") in the
   surrounding window overriding it. First attempt used `portugu[eê]s` and
   silently never matched the accented "Portugues" — the kind of bug that
   passes every test you think to write.

### Result

```
separation gap +8.0 -> +26.0
not_a_fit above the WA median 16/105 -> 2/105
top-100 precision 53% -> 74%
```

The worth_applying median did not move (65.0). The gain is entirely from
pushing bad matches down, not from inflating good ones.

### Lesson

Every scoring change before today was justified by reading the top of a list
and judging it sensible. That method produced a rubric with an 8-point
separation. Verdicts are the only real feedback this system gets — score
against them, and never tune a scorer by eye again.

### Also fixed

The LinkedIn digest footer ("New jobs from your other alerts" / "See all jobs
on LinkedIn") parsed as a posting, with raw `<strong class="font-bold"...>`
markup landing in the location field. Two stored rows. Some digests embed HTML
inside the text/plain part, so fields are now tag-stripped defensively.

### The probe could write platforms the fetcher could not read (2026-09-12)

`discover-companies` probes six ATS platforms; `CompanyBoardsSource` only
fetched three. So it happily wrote `smartrecruiters` and `recruitee` entries
into companies.yaml that `_FETCHERS.get(platform)` returned None for — and
the miss was a bare `continue` with a reassuring comment. Four companies sat
in the config fetching nothing: Experian (100 openings, 4 in Bogota), QIMA
(100), Keyrus (6), GEODIS (19). Their only rows in the bank came from
LinkedIn alerts, with no descriptions — which is exactly the problem the
probe exists to solve.

Found by asking a plain question — "have we actually got descriptions for
those companies?" — and looking per company instead of at the 97% average.
The four zeroes were invisible in the aggregate.

Fixed three ways:
- `_fetch_recruitee`: description and requirements are both in the list
  response, so one request covers a board.
- `_fetch_smartrecruiters`: its list response carries NO description, unlike
  every other platform here. The body needs a per-posting detail call, so
  this costs one request per job and is capped at one 100-job page.
- The unknown-platform branch now logs `unknown_board_platform` with the
  platforms it does know. A silent skip is how this survived.

Also: `_parse_iso_date` now returns None instead of raising. Recruitee writes
"2026-09-10 09:36:16 UTC", which `fromisoformat` rejects — and because the
per-company handler catches ValueError, a whole board would have been dropped
over a date field nothing depends on.

## 2026-09-12 — answer bank, resolver side (Phase 5 -> Phase 7 bridge)

`remember`/`answers` stored what Andres had answered. This is the lookup half:
given a form question, say what the answer is and where it came from, or say
honestly that it is not known. Three sources in order of authority — the bank
(something he really answered), the profile (years per technology, work
authorization, salary), then nothing.

`Profile.skill_years` is new: a lowercased technology -> years map.
"How many years of X?" is the most common variable question on any form and
the only one the bank cannot derive from something else.

Design decisions worth keeping:

- **Absent means "not stated", never zero.** A skill in `skills` without an
  entry in `skill_years` returns "years not recorded" at low confidence. He
  HAS Power BI; answering 0 would be a lie and guessing would be worse.
- **Longest matching skill wins.** With 65 overlapping names, "Microsoft SQL
  Server" must not be answered with the years recorded for plain "SQL".
- **Sponsorship is answered conditionally**, because the true answer differs
  by role location: none needed for Colombia, required for the US.
- **Sensitive questions are refused by the resolver too**, not only by the
  bank. A resolver that declined to STORE them but happily ANSWERED them
  would defeat the point.
- Unknown questions print the exact `remember` command to bank the answer, so
  using the tool is what fills the bank.

### The years table itself is NOT yet in profile.yaml

Only three durations are stated anywhere in candidate_profile.md: python 3,
sql 3, airflow 1. A draft for the other ~50 was derived from documented work
dates (Toyota Mississippi Sep-Dec 2024; Mazda Toyota May-Aug 2025; the
portfolio project) and handed to Andres to CORRECT before pasting. Deriving is
not stating, and a wrong number here goes straight onto an application form —
this is the "never fabricate experience" rule at its most literal.

## 2026-09-12 — the wide probe, and the performance it exposed

### The wide probe was worth it, despite looking like noise

Probing all 496 remaining companies (not just those with a 40+ job) found 64
boards; companies.yaml 41 -> 105; the bank went 3,985 -> **10,774** jobs.
Most of the additions ARE noise — Zscaler 371 openings, Veeam 242, Elevenlabs
246, overwhelmingly US sales roles, because those companies entered the bank
via Jobicy/Adzuna rather than via his alerts.

The worry was that noise would swamp the top of the ranked list. Measured:

```
top-100 locations: Colombia 91, LATAM 4, other 5
```

The scorer buried all of it. And the wide net found employers the narrow one
would have missed — **Cuesta Partners** (4 Bogota/LATAM data roles in the top
20) and **Clara** (Data Scientist, Bogota, 95). Both are exactly the kind of
company this project exists to find.

Lesson: judge a source by what reaches the TOP of the list, not by how much
it adds to the pile. Filtering probe candidates by their current job's score
was also wrong-headed — Wizeline's alert job scored 70 while its board held a
95. The board is the point, not the alert.

### 10,774 jobs made the scorer too slow to use

`rank` and `review-queue` re-score everything on every call; at 10k jobs that
passed two minutes. Profiled: `matched_skills` was 59% of all scoring time,
178,750 regex searches for 1,500 jobs — 65 skills tested individually against
every description.

Replaced with ONE combined pattern. Two subtleties, both caught by diffing
old against new across all 10,774 jobs rather than trusting the change:

1. **Alternation consumes its match**, so "data quality analysis" credited
   "Data Quality" and silently lost "Quality Analysis". Fixed with a
   zero-width lookahead, which lets overlapping skills both match. Two real
   jobs differed on exactly this.
2. **Leftmost-longest ordering** would stop "Microsoft SQL Server" from also
   crediting "SQL", which the per-skill loop did. A nesting map computed once
   per profile restores it.

Result: **3.0x faster, 0 of 10,774 jobs scoring differently.** The diff was
the whole point — a 3x speedup that quietly changed 2 scores would have been
a bad trade, and there was no way to know without checking.

### Airflow and GCP removed — he has not used either (2026-09-12)

Andres corrected this directly. Both were listed in `candidate_profile.md`
("Airflow: 1 year", GCP under Cloud/DevOps with a named GCP project) and both
were in `config/profile.yaml`. Removed from both, and from the long-term
memory note that repeated the claim.

**Still present on the D_Eng master resume**, in the Technical line:
"... Docker, Airflow, BigQuery, GCP, Git ...". Deliberately NOT edited — that
is his document and his call. He has been told.

Consequences worth knowing: any earlier gap analysis that reported airflow or
gcp as "already covered" was wrong, and matched_skills no longer credits them.
Real effect measured on N-iX's Data Engineer (Snowflake): still 79, still ten
matched skills, just without those two.

This is the "never fabricate" rule working in the direction that matters —
the source documents were wrong and the person is the authority, not the file.

### `remove_skills` — the one resume edit made eagerly (2026-09-12)

Every other resume change this project makes only reorders terms that are
already there; `remove_skills` deletes named ones. That asymmetry is
deliberate: adding or reordering can mislead, but removing an untrue claim
can only make a resume more honest.

Used to strip Airflow and GCP from the D_Eng master resume at Andres's
request. Verified: 34 lines before, 34 after, exactly one changed; category
separators intact; still one page. A backup sits at
`private/resumes/.backup_D_Eng_before_removal.docx`. The other three resumes
never mentioned either.
