# Vercel cloud deployment

Production: https://lakshya-job-search.vercel.app

Lakshya runs on the existing `kunal-deshmukh` Hobby team, project
`lakshya-job-search`, with the Supabase Free `lakshya` database in Singapore.
The user's computer and local Docker services are not part of this deployment.
No paid plan was selected. Free service quotas still apply.

## Start using it

1. Open the production site and choose **Sign up**.
2. Upload your own PDF, DOCX or text resume in **My preferences** (4 MB maximum).
3. Check the job titles and cities. AI/ML/Data roles, Indian cities and remote,
   and up to two years of required experience remain the defaults.
4. Choose **Prepare and review** or **Apply automatically**, set a daily limit,
   then choose **Save and start my search**.
5. Use **Find jobs**, **Needs your help**, and **Applications** to see progress.

No `.env` changes or paid AI key are needed to use the public site. Built-in
processing extracts evidence and creates factual resumes without model API calls.
An optional Gemini key belongs in the signed-in account's Advanced settings.
Accounts on localhost and the public site are separate; create a cloud account.

## Runtime and persistence

`vercel.json` defines four Services: static React frontend, public Express API
proxy, private Python container backend, and private Express queue consumer.
Service bindings connect the gateway and worker to the backend. Internal requests
require a separate server-only service secret; browsers never receive it.

Supabase PostgreSQL stores salted password hashes, hashed expiring sessions, an atomic command
outbox, and encrypted account workspace files. SQLite databases and LangGraph
checkpoints are execution formats inside freshly restored `/tmp` workspaces.
Every business request and worker holds an exclusive PostgreSQL session advisory
lock for its account. Successful responses follow the committed snapshot.
Files, resume artifacts, credentials, feed-cache age and checkpoints survive
container replacement. PostgreSQL is authoritative; temporary disk is not.
The Supabase Session pooler on port 5432 supports session locks. Transaction
pooling on port 6543 is unsuitable. The server-only `LAKSHYA_POSTGRES_URL` and
`LAKSHYA_POSTGRES_SCHEMA=lakshya_private` select the dedicated private schema.

Vercel Queues execute one pipeline stage or one application per delivery.
Messages are idempotent and follow-up work is persisted with the snapshot.
Delayed queue messages schedule hourly account searches without an open browser.
A daily authenticated cron drains undispatched work and recovers commands older
than queue retention. Submission reservations are committed to PostgreSQL before any
external submission; uncertain submissions are not retried automatically.

## Limits and operations

- Cloud execution uses lexical matching and built-in factual tailoring by default.
  Each search matches retained jobs before selecting up to two resumes to bound
  document work. Eligible direct-employer forms take priority in automatic mode.
- Uploads are limited to 4 MB; each account's workspace is limited to 100 MB.
- Auto mode requires passing document checks, a match score of at least 80,
  a known posting date within 24 hours, and a supported hosted Greenhouse, Lever
  or Ashby form. Login, CAPTCHA, consent, missing answers and unsupported forms
  need the user's input. LinkedIn/Naukri remain manual.
- Free Vercel/Supabase quotas can suspend or throttle service. This is a working cloud
  deployment, not a promise of unlimited capacity or an uptime SLA.
- Email verification and self-service password reset are not implemented.
- Keep `LAKSHYA_STORAGE_KEY` securely backed up with the database: losing it makes
  encrypted workspaces unreadable. Preserve it across redeploys. Do not rotate it
  without migrating stored ciphertext. Never include deployment secrets in ZIPs.

Deploy from the project root with `npx vercel --prod`. Vercel holds database URLs,
`LAKSHYA_SERVICE_KEY`, `LAKSHYA_STORAGE_KEY`, and `CRON_SECRET` as private production
environment variables. `scripts/configure_vercel.py` configures the linked project;
it does not copy personal local credentials or profiles into cloud accounts.

Queue messages are pinned to their publishing deployment. For future worker
updates, let existing work finish, then disable and re-enable automatic search
for enabled accounts on the new production deployment. Do not remove an old
worker deployment while it still has pending deliveries.

See [verification](VERIFICATION.md) for executed checks and [architecture](ARCHITECTURE.md).
Provider references: [Services](https://vercel.com/docs/services),
[Container images](https://vercel.com/docs/functions/container-images),
[Queues](https://vercel.com/docs/queues),
[Queue concepts](https://vercel.com/docs/queues/concepts),
[Hobby cron limits](https://vercel.com/docs/cron-jobs/usage-and-pricing),
[Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Fresh start on Supabase

The user authorized a fresh start on 7 October 2026. Existing Neon data could not
be exported because Neon rejected connections after a quota limit. That database
remains untouched for possible recovery; its accounts and resumes were not copied.
Create a new cloud account and upload your resume again. Any later recovery must
use a separate private schema and an explicit merge, never overwrite live accounts.
See [migration status and verification](SUPABASE_MIGRATION.md).

See [application coverage](APPLICATION_COVERAGE.md) for verified starter employer
feeds, current auto-apply limits and explanations shown for jobs needing help.
