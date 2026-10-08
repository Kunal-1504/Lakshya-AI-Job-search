# Recruitee expansion — 7 October 2026

Lakshya can discover published Recruitee openings and attempt eligible applications
on hosted company forms, alongside Greenhouse, Lever and Ashby. This expands
coverage; it does not implement automatic submission on every job website.

The default Recruitee board is Metyis (`metyisag`). A custom nonempty board list
replaces that starter. The public XML feed supplies the actual publication date,
all listed locations, job description and requirements. Creation and update dates
are never substituted for publication. Closed offers are excluded. Remote country
restrictions are retained. Custom employer domains remain an external handoff.

Grouped radio questions now use the complete question and an exact saved answer.
A generic saved “Yes” cannot answer unrelated questions. Required unchecked
checkboxes and unanswered radio groups block submission. Cover notes can be
attached where the form accepts plain text; unsupported file formats need help.
React forms have time to mount before inspection.

File selection may upload a resume immediately on some websites. Live submission
therefore defers file selection until questions are checked, the approved
artifacts are reverified and a durable attempt is reserved. Failures after that
point remain uncertain and cannot retry automatically. CAPTCHA/login checks run
again before reservation and after file selection. The daily cap, score of at
least 80, reliable publication within 24 hours, factual resume checks, role,
location and maximum two years of required experience still apply.

Local Chromium tests use controlled application servers, including eager file
uploads, grouped answers, consent, late CAPTCHA, and duplicate prevention. Live
employer verification only reads a public feed and fills synthetic text with all
non-read requests blocked and files deferred. No QA application is sent to an
employer. See [live evidence](RECRUITEE_LIVE_VERIFICATION.json).

Recruitee's Careers Site JSON API introduces mandatory employer tokens on
10 February 2027. Discovery uses the public XML feed, which is excluded from that
token requirement. Submission uses the visible hosted form and does not call the
candidate API directly or omit required questions. Forms requiring authentication,
consent, CAPTCHA or unsupported controls pause for the candidate.

References: [Recruitee API authentication](https://docs.recruitee.com/reference/authentication-1),
[official XML feed FAQ](https://support.recruitee.com/en/articles/8213076-faq-api),
[candidate application behavior](https://docs.recruitee.com/reference/offersoffer_idcandidates).

## Cloud startup reliability

A production log showed the Python container failing to open its port within
Vercel's 24.7-second startup window. Heavy imports, migrations and Supabase
initialization ran eagerly while Uvicorn imported the module. This could delay
queue stages with an HTTP 500 response; it was unrelated to an API-key rejection.

The private ASGI entrypoint now completes its outer startup immediately. The first
authenticated request initializes the actual application once, including its full
startup lifecycle, before dispatch. Concurrent requests share initialization;
unauthenticated requests cannot trigger private database work. Initialization
failure returns a generic retryable 503 and can retry without exposing credentials.
Shutdown still runs the application's cleanup.

A real local Uvicorn process opened its port and rejected an unauthenticated
request in 0.82 seconds with no database URL configured. Three startup regression
tests passed, alongside 14 additional cloud/API checks; three optional integration
tests were skipped. See [startup verification](CLOUD_STARTUP_VERIFICATION.json).


The final release (`dpl_7RVdHprVocD8AEmKPbfcCLbSmEH1`) passed 41 public checks,
and its scheduled full cycle completed with all seven available sources returning
live HTTP results. No application reached the preparation/submission gates.
The real account's roles, locations, experience limit, mode and daily cap were
preserved. Temporary verification accounts were removed.

A separate transient `/internal/step` HTTP 500 occurred after matching. The log
contains no explanatory exception, so its cause remains unconfirmed. The cloud
queue retry resumed processing and completed the cycle. A local replay of the
same saved command returned immediately as a no-op after the cloud worker had
handled it; it did not perform the recovery. This observation means the release
must not be described as having no worker errors. Background retries can add
several minutes. The original port-binding issue and its startup regression test
are distinct from this remaining transient failure.
