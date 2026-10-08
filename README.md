# Lakshya

A job-search app with email/password accounts, real job discovery, resumes tailored
to each job description, optional automatic applications and application tracking.
Each account has a separate workspace. Production uses real sources and never
seeds or falls back to demo data.

Use the deployed app at **https://lakshya-job-search.vercel.app**. Sign up, upload
your own resume, check **My preferences**, and save your search. It works while
your computer is off. No `.env` edits or paid AI key are needed for the cloud app.
See [cloud deployment](docs/VERCEL.md) and [real-use setup](docs/REAL_USE.md).

The local Docker installation remains available at http://localhost:18080.
Cloud and local accounts are separate. [VPS deployment](docs/DEPLOYMENT.md) is an
optional alternative.

## Start a fresh installation

```bash
python3 scripts/setup_env.py                 # generates a private access key; preserves credentials
# Edit .env: optionally add GEMINI_API_KEY. No paid key is required for local processing.
docker compose up --build -d --wait
```

Default fresh-install ports are 8000 for the API and 8080 for the dashboard. This
workspace uses 18000 and 18080 in `.env`. Users sign up/sign in with email and
password; the browser uses an HttpOnly session cookie. **LAKSHYA_API_KEY** remains
a private operator credential for the existing owner workspace and CLI integrations.
Do not share it with users. For a VPS, set your domain and use the production
override described in [DEPLOYMENT.md](docs/DEPLOYMENT.md).

The Docker backend includes CPU PyTorch, sentence-transformers, Pango, fonts and
headless Chromium for automatic applications.
The first semantic run downloads MiniLM; its cache persists on the live data
volume. Set `LAKSHYA_INSTALL_ML=false` only for a compact deployment and select
lexical matching in Settings. The Docker image build defaults to real MiniLM.

The live data, configuration and output volumes are independent of the old demo
volumes. Do not run `docker compose down -v` unless you want to erase live data.

## Configure your real search

1. Import your actual PDF, DOCX or text resume in My preferences. Scanned PDFs require
   OCR. Inspect the extracted name, skills and evidence before using them.
2. Confirm roles, cities, remote options and match threshold. The current target
   is AI Engineer, ML Engineer, Software Engineer with AI/ML, or Data Analyst,
   up to two years of required experience. Matching requires a known posting
   date within 24 hours. Discovery can show older unscored listings separately.
3. Choose **Local processing** for no API calls, or **Gemini** and save a free-tier
   API key. Docker local mode uses MiniLM and evidence extraction; cloud mode uses lexical matching. Gemini adds model
   reasoning with strict JSON validation. No Anthropic subscription is needed; choose the model available to your Gemini project.
4. Public RemoteOK, We Work Remotely and Himalayas sources work without keys.
   Add Adzuna app ID/key for broader Indian coverage, and employer board slugs
   for Ashby, Greenhouse, Lever or Recruitee. Unconfigured sources are reported and skipped.
5. Save My preferences to enable automatic searches, or choose Search now.
   Before resume import, discovery works. After import, the pipeline matches,
   creates PDF/DOCX documents from your evidence, and runs the critic. Use
   **Tailor my resume** on a fresh job card to prepare a specific job.
6. Choose **Prepare and review** or explicitly enable **Apply automatically**.
   Auto mode submits supported hosted Greenhouse/Lever/Ashby/Recruitee forms scoring at
   least 80, within your daily cap. Login, CAPTCHA, consent and missing answers
   go to Needs your help. Inspect documents and complete those forms yourself.
   Only confirmed employer responses count as applied.

Automatic submission requires a supported form; coverage does not include every
job website. See [application coverage](docs/APPLICATION_COVERAGE.md) and
[Recruitee support](docs/RECRUITEE_SUPPORT.md) for verification and limitations.

No generated candidate facts, fabricated employer postings, silent demo fallback
or automatic paid-provider fallback are used in production. A legitimate search
can return zero eligible roles. Free public feeds have incomplete coverage and
publish on their own schedule: hourly polling does not make a daily feed instant.
Remotive's public feed is delayed, so it is disabled by default and cached for six
hours if enabled. Himalayas public results are cached for 24 hours; other sources
for 30 minutes. The role/location/freshness gates are reevaluated every run.

## Environment variables and free AI

```dotenv
LAKSHYA_API_KEY=generated-private-local-access-key
GEMINI_API_KEY=your-own-google-ai-studio-key
LAKSHYA_AI_PROVIDER=
LAKSHYA_API_PORT=18000
LAKSHYA_WEB_PORT=18080
LAKSHYA_INSTALL_ML=true
# Optional:
ANTHROPIC_API_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
GMAIL_ACCESS_TOKEN=
```

Leave `LAKSHYA_AI_PROVIDER` empty to manage the provider through Settings, or
explicitly override it with `local`, `gemini` or `anthropic`. Provider credentials
from `.env` take priority on restart. After an environment change, run
`docker compose up -d --force-recreate --wait`. Do not put secrets in YAML or commit
`.env`. The setup script protects `.env` with mode 0600. Settings stores private
credentials with mode 0600 on the data volume and never returns their values.

The default Gemini configuration uses `gemini-3.5-flash-lite` for JD analysis,
matching, tailoring and criticism. Defaults cap remote calls at 16 per run and
20 per local day and pace calls 20 seconds apart. Set them to your actual free
quota. HTTP 429/authentication/model/service failures stop more remote model
calls in the current run. Conservative failed reservations remain accounted for.

Google's free tier has variable quotas and may use supplied content to improve
its products. Use a project without enabled billing for free-only usage. Setting
`llm_free_tier: true` makes Lakshya's usage estimate zero; it does not control
Google's billing. Provider prices and model availability can change. See
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[quotas](https://ai.google.dev/gemini-api/docs/rate-limits).

## Local CLI and visible browser assistance

Python 3.11+ and Node 20.19+/22 are supported. On Debian/Ubuntu, PDF generation
requires `libpango-1.0-0`, `libpangoft2-1.0-0` and `fonts-dejavu-core`.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e '.[dev,ml]'
playwright install --with-deps chromium
python scripts/setup_env.py
lakshya init-db
lakshya scout --offline                      # real public discovery without a resume
lakshya import-resume /absolute/path/to/resume.pdf
lakshya run-all --dry-run --offline          # actual resume + real sources, local processing
lakshya run-all --no-dry-run                 # interrupts for human artifact review
lakshya serve --port 18000
```

A missing personal resume is an explicit error for matching/preparation; scout
still works. An explicit `--demo` is available only for development/test settings
and is rejected in production. Tests use isolated temporary databases.

Docker uses headless Chromium for the enabled automatic policy. For a visible
browser assistant, run the CLI in a graphical session against its own local
database. Docker, account and local CLI workspaces are separate; application IDs
are not mirrored. Download reviewed documents for forms that need your help. Do
not run independent CLI workers against Docker checkpoint/output directories.

```bash
lakshya review APPLICATION_ID --approve
lakshya apply APPLICATION_ID --dry-run      # visible form preparation; remote writes blocked
lakshya apply APPLICATION_ID --no-dry-run   # final inspection + terminal SUBMIT confirmation
lakshya export --path output/applications.xlsx
lakshya schedule --offline                 # separate foreground daily 09:00 IST CLI scheduler
```

Known questions use your exact stored answers. Unknown questions, login walls and
CAPTCHAs stop assistance. LinkedIn/Naukri submissions remain manual. Optional
explicit CLI `--auto` accepts only approved, critic-passing hosted Greenhouse/
Lever/Ashby forms scoring at least 80, at most ten per run/day. Verify each target
form before using it. Uncertain submission reservations cannot be automatically
retried. The dashboard and scheduler submit only when automatic mode is enabled
and the checked bundle and supported form pass the application gates.

## API and tracking

Business routes accept an account session cookie or the private operator
`X-API-Key`; the gateway isolates account data. Auth routes are public and rate
limited. `/health` reports infrastructure and production mode. `/docs` on the
backend contains request schemas. Main routes:

- `POST /api/auth/signup`, `/signin`, `/signout`; `GET /api/auth/me`.
- `POST /api/jobs/{id}/prepare`: tailor a specific fresh real job.

- `GET /api/live`: readiness, required user inputs, source configuration, scheduler.
- `GET /api/jobs`, `/api/jobs/{id}`: search, source, score, remote type and freshness.
- `GET /api/applications`, `/api/applications/{id}`: files, original evidence,
  critic report, notes, status history and follow-up draft.
- `POST .../{approve|reject|rerender|confirm-manual|followup}` and typed file downloads.
- `GET /api/stats`, `/export`, `/agents`, `/settings`, `/screening-answers`.
- `PATCH /settings`, `POST /settings/credentials`, `/profile/import`,
  `PUT /screening-answers`.
- `POST /api/runs`; list/detail; pause/resume/stop; authenticated SSE event stream.

Status patches optionally accept `expected_status` to prevent conflicting updates.
Approval is tied to the reviewed file hashes and immutable master resume evidence.
Pause/stop act at safe agent boundaries; active requests complete first. Restarts
mark interrupted workers for explicit resume rather than claiming they succeeded.

Optional Gmail suggestions use your expiring OAuth access token with only
`https://www.googleapis.com/auth/gmail.readonly`. `POST /api/gmail/suggestions`
reads up to 50 recent messages and suggests uniquely matched application status
changes. Confirm them yourself. No email is sent and no status is changed
implicitly. Tokens are refreshed outside Lakshya. Follow-up drafts are due after
seven days and are never automatically sent.

## Verification and delivery

```bash
ruff check backend
ruff format --check backend
mypy
pytest -q
python scripts/eval_critic.py
cd frontend
npm run lint
npm run format:check
npm test
npm run build
```

CI runs Python 3.11/3.12, Node 22 and Docker smoke checks. See
[verification](docs/VERIFICATION.md), [architecture](docs/ARCHITECTURE.md),
[operational limits](docs/RISKS.md) and [personal setup](docs/REAL_USE.md).
`python scripts/build_delivery.py` creates `docs/SOURCE.md` and
`../lakshya-complete.zip` without credentials, personal runtime data or dependencies.

This release has no email verification or self-service password reset. See the
cloud deployment guide for current hosting limits and backup requirements.

Local SQLite uses WAL, foreign keys, a busy timeout and serialized usage
reservations. In cloud mode, Neon stores authentication data and encrypted
per-account workspace snapshots, including SQLite databases and checkpoints.
Distributed locks serialize every account request and queue worker; Vercel Queues
persist background work independently of the user's computer.
