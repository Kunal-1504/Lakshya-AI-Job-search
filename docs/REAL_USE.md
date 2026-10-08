# Use Lakshya for your job search

Open https://lakshya-job-search.vercel.app. It runs in the cloud even when your computer is off. Accounts on the cloud site are separate from localhost.

1. Click **Sign up**, enter your name, email and a password of at least 12 characters.
2. In **My preferences**, upload your real PDF, DOCX or text resume (up to 4 MB).
3. Check job titles and cities. The default targets are your AI/ML/Data roles,
   Indian cities and remote options, with up to two required years of experience.
4. Choose **Prepare and review** or **Apply automatically**. Set your daily limit
   and click **Save and start my search**.
5. Use **Find jobs** to view results and **Tailor my resume** to prepare a specific
   recent job. **Applications** tracks confirmed submissions; **Needs your help**
   shows forms requiring your input.

Each account has separate jobs, resume evidence, documents, answers and history.
Your old operator workspace and its credentials remain separate. New accounts
start with local processing and no inherited Gemini credential. You do not need
an API key to sign in. The old rejected dashboard-key screen is gone.

## What automatic mode does

For eligible jobs on supported hosted Greenhouse, Lever or Ashby forms, the app
creates a resume from your uploaded evidence, checks the documents, fills known
answers and submits in headless Chromium. It requires a score of at least 80 and
a known posting date within 24 hours, enforces daily limits and reserves each
submission to prevent duplicates. Confirmation must come from the employer form.

Some forms need you: employer login, CAPTCHA, privacy/legal consent, missing
screening answers and unsupported sites pause for help. LinkedIn and Naukri
remain manual. An uncertain submission is never retried automatically. No real
employer submission was performed during development verification.

A search can return no eligible jobs. Free feeds have incomplete coverage and
refresh on their own schedules. Older unscored listings can still be browsed;
the matching/preparation workflow enforces your freshness and experience limits.

## Optional settings

Open **Advanced settings** to inspect extracted resume evidence, add exact
screening answers (notice period, salary, work authorization, relocation), choose
AI processing and configure additional sources.

Local processing needs no paid key and uses local matching, evidence extraction
and factual checks. Add your own Gemini key in your account if you want remote
AI reasoning. Do not paste credentials into chat or share them with other users.
The existing owner credential from `.env` does not belong to new accounts.

Google free quotas vary. Check your project in Google AI Studio and its billing
settings. The app's free-tier cost setting cannot control provider billing. Remote
calls stop on quota/auth/service failure without paid-provider fallback. Google's
free tier may use submitted content to improve its products; local mode keeps
resume processing in your deployment.

Optional Adzuna app ID/key and employer board slugs improve job-source coverage.
Account Gmail integration is currently unavailable; it cannot read the operator's
personal OAuth token. Follow-up drafts never send email automatically.

## Cloud deployment

The public deployment is already configured. No `.env` changes are required.
Cloud searches prepare up to two matching resumes per run, with a 100 MB account
storage limit and free hosting quotas. See [VERCEL.md](VERCEL.md) for operations
and limitations. Built-in cloud processing uses lexical matching and factual
tailoring; it needs no paid API key.

## Optional: run this on your VPS

Follow [DEPLOYMENT.md](DEPLOYMENT.md). You need your VPS hostname/access, Docker
Compose, a domain pointing to the server, and open ports 80/443. The supplied
production override configures Caddy HTTPS and Secure session cookies.

Users sign up themselves. No email verification or self-service password reset
is included in this release. Back up persistent volumes before updating.

```bash
docker compose up -d --wait
docker compose ps
docker compose logs --tail=100 backend
```

Account changes save immediately. Environment changes need container recreation.
Disable automatic mode to stop future automatic submissions; disable automatic
searches in Advanced settings to pause scheduled discovery. Do not remove volumes
unless you intend to erase the accounts and their personal data.

Provider references: [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
and [Gemini quotas](https://ai.google.dev/gemini-api/docs/rate-limits).
