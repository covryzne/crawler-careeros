# Crawler worker staging on Azure VM

The worker coordinator lives in the backend repository, while the browser engine lives here. The worker image copies both repos at build time and uses separate Python environments. Checkout/synchronize both staging branches before rebuilding; updating only crawler code does not update the backend coordinator in the image.

Expected server layout:

```text
/home/azureuser/careeros-job-tracker/
  backend-careeros/
    .env.staging
  crawler-careeros/
  frontend-careeros/
```

## 1. Configuration

The only source of DB credentials is the selected backend `.env.staging`, pointing to the same Supabase staging database as the API. Set there:

```dotenv
APP_ENV=staging
CRAWLER_BROWSER_MODE=headed
CRAWLER_RUN_TIMEOUT_SECONDS=3600
CRAWLER_LEASE_SECONDS=30
```

Use headless instead of headed if desired. Staging Compose substitutes that variable explicitly. Browser mode must be headed/headless/auto; no other value is accepted. Credentials in DATABASE_URL must be URL-encoded where necessary for dotenv/URL parsing. Do not send keys or the DSN to chat/logs.

Compose supplies APP_ENV=staging, ALLOW_LOCAL_IDENTITY=false, AGENT_WORKER_EMBEDDED=false and disables agent execution. It passes only DB URL and worker settings; Supabase API keys, provider keys and Fernet key are not needed by this crawler coordinator. Host venv paths are replaced with CRAWLER_ROOT=/app/crawler and CRAWLER_PYTHON=/opt/crawler/bin/python. No crawler env file, new network join, public port or Nginx route is needed. Work is claimed from PostgreSQL and results are ingested by shared backend services.

The updated backend worker accepts development/test/staging; production remains rejected. This standalone worker currently requires AGENT_WORKER_EMBEDDED=false even when run manually; Compose already supplies it. It does not run the API's authentication startup path, because jobs already carry their owner from the authenticated API. Do not change APP_ENV to development as a workaround.

## 2. Validate and build

From the server crawler repo:

```bash
cd /home/azureuser/careeros-job-tracker/crawler-careeros
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml config --quiet
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml build crawler-worker
```

The backend checkout is the named build context `../backend-careeros`. Rebuild the worker whenever relevant backend coordinator code/dependencies change, even if the API image was already rebuilt. All dependencies and Chromium/ChromeDriver/Xvfb are installed in the image; conda/venv on the VM are not used.

## 3. Test browser/display before polling jobs

The following replaces the worker command with a local data-URL browser test. It does not claim a job, contact a portal, or need a seeded profile:

```bash
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml run --rm --no-deps crawler-worker /opt/crawler/bin/python /opt/careeros/browser_smoke.py
```

For headed expect `browser_mode=headed display_ready=True`, then `Browser smoke passed: mode=headed, headless=False`. Headless should report headless=True. Auto starts a display so adapters can choose their normal mode; the smoke itself uses a headless page for auto.

Xvfb starts on an allocated display, waits for readiness and disables its TCP listener. Headed here means a browser on a virtual display, not a visible VM desktop. VNC/noVNC is not installed. This configuration does not guarantee portal acceptance or remove blocks/challenges. Chromium still runs as the image's non-root user with the existing container no-sandbox wrapper; Docker privileged mode is not used.

Optional worker configuration check, also without polling/claiming:

```bash
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml run --rm --no-deps crawler-worker /opt/backend/bin/python -c "from app.crawler.worker import validate_worker_settings; validate_worker_settings(); print('Worker staging settings valid')"
```

Do not use `--once` as a no-side-effects smoke test: it can claim and execute a queued run.

## 4. Serve

Apply backend Alembic migrations to the staging database first. Stop any old tmux/host worker for the same environment and let its active work stop cleanly before switching.

```bash
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml up -d crawler-worker
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml ps -a
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml logs --tail=100 crawler-worker
```

Look for the safe environment/browser/timeout summary, installed adapter check, worker ready, and `Idle: waiting for a queued run...`. Ready alone confirms adapter probing, not database polling. Failures now include phase, exception type, underlying driver exception type, SQLSTATE, connection invalidation and an explicit lease-loss code where known; SQL/parameters, DSNs, passwords and page content are not logged. Older images print only `Crawler polling unavailable`. Polling errors happen before a new execution starts; they alone do not prove a portal/browser failure. Inspect target DB connectivity and migration state. Unexpected exit/restart requires checking logs before triggering work.

Once API and frontend are running, sign in and use Start Crawl Now with one portal, one keyword and small limits. Follow the same run ID in UI and worker logs. A ready worker does not imply a schedule is enabled; the current flow is manual.

If old logs show SQLSTATE 26000 / InvalidSqlStatementName, synchronize the backend prepared-statement fix and rebuild both API and worker images. Shared application and Alembic psycopg connections now use prepare_threshold=None. This is unrelated to headed mode or IP blocking; no database reset is needed. Verify new connections from the running worker without claiming a job:

```bash
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml exec -T crawler-worker /opt/backend/bin/python -c "from app.db.session import engine; c=engine.raw_connection(); print('prepare_threshold=', c.driver_connection.prepare_threshold); c.close()"
```

Expected: `prepare_threshold= None`. This confirms the driver setting, not completion of a real portal crawl; monitor polling/heartbeat and perform a small manual run next.

Stop gracefully:

```bash
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml stop --timeout 60 crawler-worker
```

Docker init forwards SIGTERM to the worker; the worker cancels active work through the existing browser and lease cleanup path. Cancellation behavior is unit-tested; an actual browser shutdown in the target container still needs verification. If a slot is retained after interruption, follow the existing operator recovery procedure and confirm old browser processes have stopped; do not clear queue state blindly. Keep named artifact/cache volumes; do not use `down -v` to restart.

## Failure evidence

Listing and detail failures now attempt to capture a viewport PNG and JSON metadata before browser cleanup. This includes `challenge_blocked`. The manifest's `failure_artifacts` entry references these files relative to that CLI run's output directory. Capture happens when the failure is reported, after any verification timeout; it is not a recording of the first moment a challenge appeared.

Metadata includes UTC `detected_at` and `captured_at`, portal, phase, page, browser mode, current page title, URL without query/fragment/credentials, and the internal CLI run ID. Screenshot or storage failure does not replace the original crawl outcome. A dead browser can leave metadata without a screenshot. No HTML or cookie dump is added.

For queued worker runs, the existing private artifact volume contains:

```text
/app/crawler/output/service-runs/<backend-run-id>/<portal>/<keyword-index>/<cli-run-id>/
  manifest.json
  artifacts/
    <portal>-<phase>-<unique-id>.png
    <portal>-<phase>-<unique-id>.json
```

Stop the laptop worker before switching back to the Azure worker. After synchronizing this crawler change, rebuild and start it:

```bash
sudo docker compose --env-file ../backend-careeros/.env.staging -f compose.staging.yml up -d --build crawler-worker
```

Trigger a new, small manual run from the web. Existing failed runs cannot acquire screenshots retroactively. Copy its directory from the running worker, replacing `REPLACE_WITH_BACKEND_RUN_ID` with the ID shown in worker logs:

```bash
mkdir -p output/artifacts-review
sudo docker cp careeros-crawler-staging-crawler-worker-1:/app/crawler/output/service-runs/REPLACE_WITH_BACKEND_RUN_ID ./output/artifacts-review/
```

These files persist across container replacement through the existing named volume. Do not use `down -v` when restarting. Screenshots remain private operator evidence: no public route or frontend download button is added. Retention is currently manual, so monitor volume usage. This capture helps diagnose a block; it does not clear the portal's challenge.

## Verification performed locally

Crawler suite: 94 passed, 26 skipped (including opt-in browser tests). Backend worker/crawler tests: 43 passed. Tests cover display readiness/timeout cleanup, mode-dependent exec, staging settings and SIGTERM cancellation. Compose staging validates in both headed and headless modes. Docker daemon is unavailable locally, so the actual image build, Xvfb/Chromium launch, live Supabase queue polling and portal behavior are not claimed tested. Run the container browser smoke above on Azure before the first job.
