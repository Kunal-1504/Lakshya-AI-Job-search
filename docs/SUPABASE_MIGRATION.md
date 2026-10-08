# Supabase migration

Fresh production cutover completed 7 October 2026. Production URL: https://lakshya-job-search.vercel.app

## Current status

- Created the `lakshya` project (`xorharyswtgehzbcsgkh`) in the user-selected Supabase organization, on its verified **$0/month Free plan**, in Singapore.
- Verified the IPv4 session pooler connection and a session advisory lock.
- Created the dedicated `lakshya_app` login and `lakshya_private` schema with the five cloud tables.
- Confirmed anonymous and authenticated Supabase API roles cannot read those tables. RLS is enabled; no client-facing policies are intended because the authenticated Lakshya backend owns access.
- Preserved the existing encryption and internal service secrets privately. No keys were rotated.
- **The old data has not been copied.** Neon still refuses the export with its quota error. An incomplete export attempt has no manifest and cannot be restored.
- **Production is running on Supabase.** The user explicitly authorized “Start fresh” on 7 October 2026. Deployment `dpl_39aCr32uaHe65LrYDTGquchrtS8S` is READY and serves the public alias. Users must sign up and upload their resume again. Neon was left untouched; historical data has not been migrated.
- The production database URL and private schema were configured as server-only variables. Existing encryption, service and cron secrets were preserved. The legacy Neon integration variables remain available for recovery; the explicit Lakshya URL takes precedence.
- A separate [protected Vercel preview](https://lakshya-job-search-dur1rootu-kunal-deshmukh.vercel.app) has been deployed with the Supabase connection. Actual deployed checks passed for sign-up, password sign-in, session revocation, resume import/persistence, preferences, workbook export and a discovery-only search completed by Vercel Queues. [Sanitized verification results](SUPABASE_PREVIEW_VERIFICATION.json) record these checks. The disposable preview account was removed after its worker finished; no employer submission was attempted.

## Connection configuration

The backend prefers the server-only `LAKSHYA_POSTGRES_URL` over the previous Neon-managed variable. This prevents an integration refresh from silently replacing the new provider URL. `LAKSHYA_POSTGRES_SCHEMA=lakshya_private` selects the private schema. A missing schema fails rather than creating account tables in `public`.

Use Supabase's **Session pooler on port 5432**, which supports the application's session advisory locks. Transaction pooling is unsuitable for those locks. Database credentials stay on the server; neither a frontend database URL nor a Supabase browser API key is needed for the existing account system.

Private connection settings are stored in `data/migration/supabase.env` (mode 0600). Keep `LAKSHYA_STORAGE_KEY`, `LAKSHYA_SERVICE_KEY` and `CRON_SECRET` unchanged. Never publish the `data` directory or attach its secret files to reports.

## Recovery and transfer procedure

Once Neon is readable, prevent source writes for the final consistent export. Existing queue deliveries are pinned to the old deployment: finish/cancel old work and disable old schedules before cutover, then explicitly re-establish pending work on the new deployment. Do not let both databases run independent schedules or submit applications concurrently.

The prepared helper handles only Lakshya's five application tables: `users`, `sessions`, `attempts`, `cloud_files` and `cloud_commands`. It preserves password hashes, token hashes, encrypted bytes, modification times and queue payloads. It does not replace Supabase's own Auth or Storage schemas.

```bash
.venv/bin/python scripts/migrate_cloud_database.py backup \
  --env-file data/vercel-cloud.env \
  --directory data/migration/neon-final-backup

.venv/bin/python scripts/migrate_cloud_database.py restore \
  --env-file data/migration/supabase.env \
  --directory data/migration/neon-final-backup

.venv/bin/python scripts/migrate_cloud_database.py verify \
  --env-file data/migration/supabase.env \
  --directory data/migration/neon-final-backup
```

Backups are private and include sensitive authentication material. Each table has a row count and SHA-256 checksum; restore checks files before writing and verifies the resulting contents inside the restore transaction. Restore refuses a nonempty destination. If fresh accounts are authorized first, do not run restore into the live schema later: recover into another private schema and plan an explicit merge, including duplicate-email resolution and queue handling.

For any future recovery, test the recovered accounts and documents in isolation before merging into production. The authorized fresh cutover configured the new server variables and deployed the backend changes; production verification results are recorded below. Keep the old database and encryption key available for recovery. A fresh start is not a completed historical-data migration.

## Transfer reduction

Warm containers now cache encrypted snapshot blobs. Every restore still reads authoritative database metadata under the account lock, but unchanged blobs can be decrypted from the private local cache. Changed or corrupted blobs are fetched again. The working directory is recreated each time, so unsaved SQLite/WAL changes cannot become committed state through caching. Deleted remote files are removed from both workspace and cache.

This reduces redundant database transfer; cold containers still fetch necessary blobs, and free-provider limits remain applicable.

## Verification

Eight isolated PostgreSQL migration checks passed, including exact round-trip contents across all five tables, binary/Unicode preservation, refusal to overwrite, tamper rejection, transactional rollback, provider selection and private-schema isolation. New cache tests cover current metadata, dirty disk/WAL rollback, changed snapshots, damaged ciphertext, deleted files and path traversal.

Local evidence is in `data/migration/local-verification.json`; Supabase integration test results are recorded separately in `data/migration/supabase-cloud-tests.log`.

The actual Supabase run passed all 10 cloud/cache tests (including three PostgreSQL integration tests); the account/cache run passed 11 tests. These runs overlap on the six cache cases. Disposable Supabase test accounts, files, sessions, commands and rate-limit records were cleaned up before cutover. No public deployment was changed during preparation. The later fresh production cutover is described above.

References: [Supabase Neon migration guide](https://supabase.com/docs/guides/platform/migrating-to-supabase/neon), [database connections](https://supabase.com/docs/guides/database/connecting-to-postgres), [custom schemas](https://supabase.com/docs/guides/api/using-custom-schemas), [RLS with no client policy](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

## Fresh production verification — 7 October 2026

All 34 recorded checks passed against the actual public production URL: frontend, clear unauthenticated responses, sign-up, identity, resume import and persistence, preferences, tracker, Excel export, account isolation, background discovery through Vercel Queues, password sign-in, wrong-password rejection and session revocation. Disposable accounts and their snapshots/commands/sessions were removed after the worker completed; real accounts were preserved. No employer applications were submitted. Browser control timed out, so visual verification was unavailable; these results are actual public HTTP and worker checks. See [sanitized production results](SUPABASE_PRODUCTION_VERIFICATION.json).
