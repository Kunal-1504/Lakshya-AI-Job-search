# Lakshya live feature test report

Tested 7 October 2026 (Asia/Kolkata) against [the deployed website](https://lakshya-job-search.vercel.app).

**Verdict: account setup, real job discovery, resume preparation and tracking work. The current deployment is not ready for reliable unattended auto-apply.** Source parsing, eligibility and regeneration defects need attention first. No product code was changed or redeployed during this test.

## Scope and evidence

- Used the public Vercel site in the browser and its authenticated public API, with two disposable accounts and a synthetic resume.
- Exercised real remote job feeds and actual cloud queue workers. An hourly schedule triggered a cloud run without a browser action.
- Used clearly marked controlled jobs with `example.invalid` application links for resume, approval and tracker mutations. No real employer received an application or email. The test tracker's applied/interview/offer statuses were simulated.
- Checked **113 recorded live API checks: 109 passed, 4 failed**. Those four failures represent two distinct problems: invalid resume error handling (PDF twice, DOCX once), and selected-application regeneration.
- Three additional current-feed contract checks failed. A separate eligibility reproduction also failed. These are separate from the 113 API checks.
- **67 automated regression tests passed:** 52 standard Python tests, 3 opt-in PostgreSQL integration tests, 8 frontend tests and 4 gateway tests. The standard run skipped the three opt-in tests; those were subsequently run against Neon and passed. Passing regression tests do not cover the newly discovered defects.
- API evidence is in [the sanitized check results](realtime-test-results.json). Screenshots below show the actual public application. Private raw logs and synthetic artifacts remain under `data/realtime`; credentials are excluded from the shareable results.

## Feature-by-feature results

| Feature | Result | Observed behavior |
|---|---|---|
| Public deployment | Pass | Public HTTPS site, static frontend, authenticated API and cloud workers responded. |
| Sign-up and sign-in | Pass | Browser sign-up worked; duplicate email, weak password and wrong password were rejected. |
| Sessions and sign-out | Pass | Secure HttpOnly cookie; sign-out revoked API sessions. Browser returned to sign-in. |
| Account privacy | Pass for tested cases | Second account did not inherit profile, credentials or answers; cross-account job/artifact requests returned 404. |
| Request protections | Pass for tested cases | Unauthorized access returned 401; foreign-origin writes returned 403; operator-only changes were rejected. This was not a full security audit. |
| Three-step setup | Pass | Uploaded resume and saved role/location preferences, application cap and manual assistance mode. |
| TXT, PDF and DOCX import | Pass for valid files | All three formats imported; unsupported extensions and oversized files were rejected. |
| Damaged resume import | **Fail** | Invalid PDF and DOCX returned misleading 503 workspace-busy messages instead of actionable validation errors. Existing valid profile survived. |
| Settings persistence | Pass | Profile, location preferences, mode and saved answers survived fresh requests. |
| Screening answers | Pass | Save, update and exact readback worked. |
| Provider-key storage | Pass for storage only | Synthetic Gemini credential was saved and masked. A real Gemini/Anthropic generation request was not tested. |
| Real job discovery | Pass with coverage limits | RemoteOK, We Work Remotely and Himalayas each normalized 40 feed rows; filtering/deduplication retained 7 real role listings. All retained links were Himalayas aggregator links. |
| Greenhouse discovery | **Partial / freshness defect** | Current GitLab feed normalized jobs but lost all publication dates; this prevents reliable freshness eligibility. |
| Lever discovery | **Partial / freshness gap** | Current Zoox samples did not provide the adapter's expected publication field. Normalized posting dates were unknown. |
| Ashby discovery | **Fail** | Current OpenAI feed had 824 postings; a nullable field caused normalization failure. The cloud run completed with zero Ashby jobs. |
| Search and job details | Pass | Text/source/fit/freshness filters and detail routes responded; missing identifiers returned 404. |
| Up-to-two-years eligibility | **Fail for some wording** | A role requiring “6+ years of commercial experience” passed shortlisting with the maximum set to two years. |
| Resume tailoring | Pass with local provider | “Tailor my resume” produced a bundle through the deployed queue. The critic passed; the controlled job match score was 86. Factual content remained grounded in the short synthetic input. |
| Resume artifacts | Pass via API | PDF, DOCX, cover letter and change report downloaded. PDF was one A4 page, readable without clipping; DOCX/PDF text contained the source facts. |
| Browser download completion | Inconclusive | The in-app browser download-event wait timed out. API downloads and artifact contents passed; this does not establish a product download defect. Verify normal Chrome download completion separately. |
| Regenerate selected resume | **Fail** | Request queued successfully, but the selected application was not regenerated and remained in human-review state with critic failure. |
| Resume review and approval | Pass | Original/tailored content displayed; approval persisted. Unreviewed submission was blocked. |
| Automatic mode and cap | Partial | Policy and cap saved. An unsupported controlled site remained unsubmitted for review. This does not prove real employer auto-apply works. |
| Actual employer submission | Not live-tested | Controlled local Chromium regression tests passed for PDF submission, duplicate prevention and pauses for unknown required answers/legal consent. No employer-side submission was attempted. |
| Application tracking | Pass | Browser board drag persisted; notes, rejection, simulated manual confirmation, follow-up draft/approval and response status transitions worked. Stale status updates were rejected. |
| Dashboard and exports | Pass | Summary metrics, history, activity, board/table views and Excel export worked. Export opened with valid workbook content. Test metrics included simulated application outcomes. |
| Pause, resume and stop | Pass at API | Pause/resume continued a real scout run; stop persisted; resuming stopped/completed runs was rejected. Some irrelevant UI action buttons remain enabled. |
| Concurrent runs and events | Pass | Overlapping run returned 409; event-stream endpoint and activity history worked. |
| Cloud scheduling | Pass for one observed cycle | Saved hourly schedule dispatched and completed a scheduled run; next-run time persisted. Schedule was disabled after testing. This is not an uptime soak test. |
| Gmail | Unavailable for account | Suggestions endpoint returned 409 because the account was not connected. Sending/inbox sync was not verified. |
| Adzuna | Not configured/tested | Requires its own application ID/key. |
| LinkedIn and Naukri | Manual workflow | Automatic submission was not verified or represented as supported. |
| Password recovery and verification | Missing | Self-service password reset and email verification are not implemented in the tested interface. |
| Light/dark and mobile layout | Pass for observed viewports | Theme switching worked; 375×812 mobile view had no horizontal overflow. Desktop viewport and light theme were restored. |
| Beginner-friendly guidance | Needs improvement | Advanced screens expose JSON/hashes and contain incorrect local-computer instructions for a cloud deployment. |

## Defects and suggested priorities

### 1. High: Ashby can silently drop an entire live board

In `backend/lakshya/scrapers/ashby.py:31`, `workplaceType` is converted with `.lower()` without handling an explicit null. The live [OpenAI Ashby feed](https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true) returned `workplaceType: null`, producing `AttributeError`. The outer collector returned an empty result, while the cloud scout appeared completed/ready.

Handle nullable fields, isolate malformed rows and expose source failure separately from a healthy empty feed. Re-test a mixed valid/null feed and the real board.

### 2. High: posting dates do not survive current ATS feeds

`backend/lakshya/scrapers/greenhouse.py:30` expects `first_published_at`; the live [GitLab feed](https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true) used `first_published`. Of 200 normalized rows in the standalone probe, **zero retained a posting date**. One raw date was `2026-10-02T11:31:50-04:00`.

`backend/lakshya/scrapers/lever.py` expects `publishedAt`. Two live [Zoox samples](https://api.lever.co/v0/postings/zoox?mode=json&limit=2) supplied `createdAt` but no `publishedAt`, leaving posting dates unknown. Resolve publication-date provenance before selecting a replacement field; creation and publication are not automatically equivalent.

Unknown dates block the 24-hour freshness requirement. Preserve a reliable publication date and clearly communicate unknown dates.

### 3. High: experience filtering misses “commercial experience”

`backend/lakshya/matcher.py` failed to extract required years from “A minimum of 6+ years of commercial experience is required.” With maximum experience set to two, a controlled Data Analyst role was **shortlisted**, with `min_years: null`, score `77.99` and no exclusion reasons. Similar wording appeared in a real Jumio listing.

Expand extraction and add meaningful eligibility tests for phrasing, degree exceptions and seniority. This reproduction proves incorrect shortlisting; it does not show that an application was submitted.

### 4. High: regenerate does not target the selected application

`backend/lakshya/api/routes.py:461` starts a general tailor run without the selected job ID. `backend/lakshya/pipeline.py` also bounds cloud work to the first two jobs before matching. In the observed regeneration, two other real jobs were analyzed; the selected controlled application was missed and remained `needs_human_review` with `critic_passed: false`.

Scope regeneration to the selected job and apply cloud work limits after selecting eligible work. Directly preparing that same selected job again did succeed.

### 5. Medium: damaged uploads look like a server outage

PDF/DOCX parser exceptions in `backend/lakshya/resume_parser.py` are not converted into client validation errors by the import route. The account gateway maps them to **503 “Your workspace is busy or temporarily unavailable”**. Reproduced twice with invalid PDF and once with corrupt DOCX.

Return a clear 422 error telling the user to export/upload a valid file, preserving the current profile.

### 6. Medium: default discovery does not establish useful auto-apply coverage

The seven retained real jobs used generic aggregator links; default ATS board lists were empty. Unsupported jobs correctly stayed unsubmitted, but the default experience therefore did not demonstrate automatic employer submissions. Combined with the ATS/date defects, “auto-apply” should not yet be treated as a reliable unattended flow.

Validate supported ATS coverage, exact application URLs, freshness, matching and required answers before enabling unattended submissions.

### 7. Low: cloud copy and controls confuse users

`frontend/src/pages.tsx` says the computer/Docker must stay running, describes local-volume credential storage and references MiniLM although this deployment uses cloud storage and lexical matching. Resume review also suggests a local CLI workflow. Advanced JSON, hashes and enabled controls for terminal runs add friction.

Replace these with deployment-aware language, plain status explanations and controls that reflect available actions. Add account recovery before broader public use.

## Performance and limits

Recorded API checks had a median duration of **0.50 seconds**. Initial sign-in took **12.34 seconds** and one overlapping-run rejection took **15.51 seconds**. A scheduled-dispatch observation took roughly 21.5 seconds including waiting for the queue; that is not HTTP response latency. Cold starts and serialized account work can therefore cause noticeable delays.

This test covered the observed deployment, two accounts, short synthetic documents, current sampled feeds and one schedule cycle. It did not establish sustained uptime, load capacity, all job boards, every browser, external AI quality or real employer submission success. The synthetic PDF was intentionally sparse; a longer real resume needs its own layout/quality review.

## Visual evidence

The public resume review screen showed the original evidence, generated content and critic result for a clearly marked controlled job:

![Live public resume review](realtime-resume-review.png)

[Mobile screenshot](realtime-mobile-preview.png) · [Advanced-settings copy screenshot](realtime-advanced-copy.png)

## Cleanup and recommended next step

Both disposable cloud accounts, their sessions, encrypted snapshots and queue commands were removed and verified absent. Test schedules were disabled and all test runs were terminal before cleanup. Browser signed out; real user accounts were not modified. No application or email was sent to an employer.

Fix the source/date, eligibility and regeneration defects first, add regression cases for these exact failures, then repeat supported-form end-to-end testing before turning on unattended auto-apply. The current production deployment still contains the reported defects.
