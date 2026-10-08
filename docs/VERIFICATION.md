# Verification — 6 October 2026

Production: https://lakshya-job-search.vercel.app

| Check | Actual result |
| --- | --- |
| Full standard Python suite | 52 passed; 3 opt-in PostgreSQL tests skipped |
| Cloud suite with actual Neon PostgreSQL | 4 passed, including the 3 opt-in tests |
| Strict mypy | Passed; 59 source files |
| Ruff lint/format | Passed; 91 files formatted |
| Frontend Vitest | 8 passed |
| Gateway Node tests | 4 passed |
| TypeScript and Vite production build | Passed; bundle-size warning only |
| Local Docker frontend/backend | Rebuilt; healthy with existing volumes retained |
| Public cloud account flow | Signup 201, sign-in 200, authenticated routes 200, Secure HttpOnly cookies |
| Public cloud resume upload | Imported synthetic text resume; evidence survived fresh requests |
| Public cloud real discovery | Queue-completed run; 6 real current-role postings visible, no demo rows |
| Public cloud tailoring | Controlled non-submitting job; critic passed; paused for manual approval |
| Public cloud artifacts | PDF 200 with PDF signature; DOCX 200 with valid ZIP structure |
| Public cloud scheduling | Delayed queue tick started a scheduled run; run completed; next hourly tick persisted |
| Public cloud logout | Session revoked; subsequent authenticated identity request 401 |
| Browser UI | Public sign-in and simple three-step preferences verified |

The cloud integration tests verify encrypted account storage, separate profiles
and credentials, session revocation, cold restore, checkpoint continuation across
every stage, atomic command outbox, idempotent queue redelivery, busy-run exclusion,
queued stop, cache-age persistence (including identical refreshed bytes), and
submission reservation persistence after worker failure.

Controlled Chromium form regression tests in the standard suite cover confirmed
PDF submission, duplicate prevention, unknown-answer pause, consent pause even
with a stored answer, and disabling automatic application in manual mode.
Worker tests prevent submission after paused/stopped/manual/dry runs. Chromium
was also launched successfully inside the local deployed backend container.
No real employer applications or emails were sent in these checks.

The public production verification used a disposable synthetic account and a
controlled job whose application URL is `example.invalid`. It did not copy the
user's local account, personal resume, job history or Gemini key to the cloud.
The verification scheduler was disabled afterward and its disposable cloud
account, sessions, files and commands were removed. The user's own personalized
job applications begin only after they upload their real resume and save their
application preferences in their cloud account.

Cloud storage and background work use Neon and Vercel Queues, independent of
localhost. Deployment status alone was not used as proof: the actual public API,
queue progression, saved evidence, scheduled run and document downloads were
checked. Earlier frontend-only deployment previews were superseded.

Screenshots: [Cloud setup](cloud-setup-preview.png),
[Cloud sign-up](cloud-signup-preview.png).

See [VERCEL.md](VERCEL.md) for free hosting/runtime limits, supported application
forms, deployment updates, and backup requirements. Email verification and
self-service password reset remain outside the implemented account flow.

Final production update: `dpl_kHu7QD8wdA8Wy1iqNsAtNRCqSncd`.
Sign-in, restored profile, persisted PDF download and HTTPS security headers
were verified again after the new container replaced the previous deployment.
