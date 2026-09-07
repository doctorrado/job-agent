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
