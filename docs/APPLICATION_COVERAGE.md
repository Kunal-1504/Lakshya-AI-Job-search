# Application coverage — 7 October 2026

Follow-up: [Recruitee expansion](RECRUITEE_SUPPORT.md) adds a fourth hosted platform
and improves grouped answers and upload handling. Counts and deployment IDs below
record the previous release, before that expansion.

The user requested coverage across job websites while keeping existing roles,
Indian cities/remote eligibility and a maximum of two years' required experience.
This update improves supported employer feeds and makes application handoffs
visible. It does not provide universal unattended submission.

## Changes

- Empty employer-board lists use verified public starter boards: Greenhouse
  Jumio/Glean, Lever Netomi, and Ashby Ema/Emergence. Custom nonempty lists replace
  starters. Disable a source to stop collecting it. Preferences now expose simple
  company-board fields instead of requiring JSON for this configuration.
- Greenhouse retains `first_published` and uses its exact hosted board/job form.
  Ashby/Lever handle nullable workplace types; Ashby handles null compensation.
  Lever creation timestamps remain unknown publication dates.
- Source limits prioritize jobs fitting role/location/experience preferences
  across the returned feed. Cloud rendering remains bounded to two resumes per
  search, with selection after matching, prioritizing eligible employer forms.
- Every application response includes `auto_apply` eligibility, reasons and
  platform. Cards, tables and details explain unsupported websites, low fit,
  unknown/old dates and unfinished document checks. Browser pauses are shown too.
- Unsupported prepared applications count as needing help, rather than reporting
  zero applied and zero needing help. Submission reservations still prevent retries.
- Regeneration targets the selected job. Experience filtering recognizes
  commercial, hands-on, engineering and combined professional wording. Automatic
  submission rechecks current role, location and experience preferences just before arming.

## Current verified coverage

All five starter feeds responded successfully. They contained 238 normalized
listings: 159 Greenhouse, 23 Lever and 56 Ashby. Three matched the default role,
location and experience gates; none also met the 24-hour freshness rule at the
time of verification. This does not promise an eligible opening every day.
See [live source evidence](LIVE_EMPLOYER_FEEDS.json).

Automatic submission remains restricted to tested Greenhouse, Lever and Ashby
form handling, a fit score of at least 80, a reliable recent date, checked factual
documents and the daily cap. Other websites use the tailored documents and an
explicit external application handoff. A job marked applied requires an actual
submission confirmation or the user's explicit manual confirmation.

Himalayas' official API exposes its own listing link. A sampled public listing
refused automated reads with HTTP 403; no access restriction was bypassed, and no
employer URL was guessed. LinkedIn/Naukri/Workday and other unimplemented sites
are not represented as autonomous adapters. Login, CAPTCHA, legal consent and
unknown answers require user input. No real employer application was sent in QA.

References: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html),
[Lever public postings API](https://github.com/lever/postings-api),
[Himalayas job API](https://himalayas.app/docs/remote-jobs-api).

## Final production verification

Deployment `dpl_GundtMvPdFpC7dWorJbYdrhv9ufn` is READY on the public production alias. All 40 backend tests and eight frontend tests passed; the frontend build and Ruff checks passed. All 38 recorded public production checks passed on the final release. A disposable account verified the live company-board controls and per-application explanations visually. Test accounts were removed.

The existing enabled account schedule was moved to the new deployment by changing its generation under the account lock, preserving its preferences and invalidating old ticks. An actual scheduled cycle completed without an error: RemoteOK, WWR, Himalayas, Greenhouse and Ashby each returned 40 normalized rows; Lever returned 23. Its submission result was zero applied and one needing help. These source counts precede deduplication and eligibility filtering. No actual employer submission was attempted by QA. See [verification evidence](APPLICATION_COVERAGE_VERIFICATION.json) and [background-cycle evidence](APPLICATION_BACKGROUND_VERIFICATION.json).
