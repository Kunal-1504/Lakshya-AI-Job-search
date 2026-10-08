# Deploy Lakshya on your VPS

You need a VPS with Docker Compose, a domain pointing to the VPS, and ports 80/443 open. Size CPU and RAM for local semantic matching and Chromium; measure usage before inviting many users. This version runs as one backend process with persistent local volumes; do not scale it into multiple backend replicas.

1. Copy the project to your VPS. Keep `.env` private. Run `python3 scripts/setup_env.py` to create the private operator key; normal users never need that key.
2. Add `LAKSHYA_DOMAIN=jobs.your-domain.com` to `.env`. Create its DNS A record pointing to your VPS. Add an AAAA record only if IPv6 reaches the same server.
3. Start the services:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

4. Open `https://jobs.your-domain.com`. Caddy obtains and renews the HTTPS certificate. The production override enables Secure session cookies. Sign up, upload your resume, save your job preferences, and choose whether to apply automatically.

The database, accounts, sessions, personal workspaces, uploaded resumes and output documents persist in Docker volumes. Back up `lakshya_live_data`, `lakshya_live_output`, `lakshya_live_config` and the Caddy volumes before updates. Treat backups as private personal data. Never upload `.env`, data volumes, or private resumes to a public source repository.

## What users see

- Sign up and sign in with email and password. There is no dashboard API-key screen.
- Each account has its own jobs, resume, screening answers, AI credentials, output files and application history. Existing operator workspace data stays separate.
- Sessions use HttpOnly, SameSite cookies, expire after seven days and are revoked on sign-out. Passwords use salted scrypt hashes. Registration/login are rate limited; cookie-authenticated writes enforce same-origin requests.
- Users can start without an AI key using local processing. An optional personal Gemini key can be added under Advanced settings. One user's key is not shared with another account.

## Automatic applications

Users explicitly enable automatic mode under My preferences. For supported Greenhouse, Lever and Ashby forms with a fit score of at least 80, Lakshya creates a resume from the user's real evidence, validates it with the critic, fills known answers and submits in headless Chromium. Daily caps, document hashes and duplicate reservations still apply. Login, CAPTCHA, consent, unprovided questions and unsupported forms require help. LinkedIn/Naukri stay manual. An uncertain result is never automatically retried.

Automatic submission has been tested with a controlled local form in the test suite. Live employer submissions cannot be verified until you provide your actual resume and screening answers and eligible jobs are found. The app does not claim a submission succeeded without an employer confirmation message.

This release has no email verification or self-service password reset. Set up email delivery before adding those flows; do not advertise verified email addresses. This is a single-VPS release, not a distributed SaaS platform. No public deployment is performed from the local workspace; your VPS hostname/domain and access are still needed to carry out the deployment.

Security references: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) and [session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
