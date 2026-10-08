# Limits and operational notes

- The live deployment uses real public sources and a supplied Gemini key. No personal resume
  has been uploaded yet. No employer submissions or messages occurred during verification.
- Public feeds may omit reliable original posting times, location eligibility or
  full JDs. Strict 24h mode rejects unknown dates. Greenhouse/Lever public board
  feeds commonly expose updates or no reliable original date; their collectors
  return unknown rather than treating a refresh as a new posting. Ashby dates
  represent last publication. Remotive's public feed delay can leave no eligible
  jobs in a strict 24h window. Zero results are a valid outcome.
- Public browser sources are opt-in, robots aware and stop on authentication,
  CAPTCHA, refusal and challenge pages. They offer no promise of broad access to
  LinkedIn/Naukri/Indeed. Check source terms and attribution before enabling a
  feed for redistribution. Account deployment is supported on one VPS; source redistribution permissions
  still depend on the original provider.
- Every ATS form differs. Custom widgets, conditional questions, client-side
  resume uploads and exact submit controls may require manual completion. The
  pre-approval read-only request gate can prevent a provider's staged upload;
  use manual application when its form needs that step. Auto mode stops at
  unresolved controls; it cannot guarantee employer acceptance.
- A browser success message is a best-effort confirmation. A missing or ambiguous
  outcome stays reserved/uncertain and requires user reconciliation. Never clear
  an uncertain reservation simply to retry a click.
- The PDF is verified as one page and compared to DOCX text. Word/LibreOffice
  pagination can vary with installed fonts. Inspect the editable DOCX before
  sending it instead of the reviewed PDF. Long resumes can require removing whole
  facts for fit; omissions are included in the changes report. Complex layouts,
  scanned PDFs and ambiguous multi-column reading order require manual cleanup.
- Budget reservations conservatively use UTF-8 input bytes plus an overhead and
  a maximum output allowance. Failed/ambiguous calls retain this estimate. Costs
  depend on the configured prices; keep them current. The app sends resume/job
  data to the selected Gemini or Anthropic provider in remote processing mode.
  Free-tier cost estimates do not control provider billing; free Gemini content
  may be used to improve Google products. Local processing makes no remote LLM calls. It does not store hidden reasoning.
- Business requests use isolated account sessions; the operator API uses its
  private key. Keep backend/frontend ports bound to loopback, and expose only
  the HTTPS proxy on the VPS. Public hosting needs protected backups and resource
  monitoring. Email verification and password reset are not included.
  Credentials, resumes, browser profiles,
  log files and artifacts are sensitive local data; they are excluded from the ZIP.
- Pipeline execution is single-worker within the API; concurrent independent CLI
  processes are not supported against the same output/checkpoint directory.
  PostgreSQL schema compatibility is designed but was not integration-tested.
- Pause/stop take effect between safe stages, not midway through a remote call.
  Source errors and per-job failures appear in activity even when the remaining
  run completes. Resume can repeat a read-only request after an interrupted stage.
- Optional Gmail uses a user-provided expiring OAuth token with read-only scope.
  Matching is heuristic, unconfirmed and limited to uniquely matched tracked
  companies. Refresh/login is external. It never updates status or sends mail
  automatically. Follow-up drafts likewise require the user to send them.

Primary references:
[Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html),
[Lever Postings API](https://github.com/lever/postings-api),
[Ashby Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api),
[Remotive API](https://github.com/remotive-com/remote-jobs-api),
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).
