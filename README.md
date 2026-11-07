# CareerOS standalone crawler

Backend integration is still preparation work. See [CRAWLER_INTEGRATION.md](../specs-careeros/CRAWLER_INTEGRATION.md) and [the proposed service contract](../specs-careeros/contracts/crawler-service.openapi.json) for the agreed service boundary and draft API. No crawler HTTP service, durable queue or scheduler is implemented by those documents.

Two search strategies, independent of the CareerOS backend:

- `browser-use` (default): Google keyword discovery, then agent-driven exploration of discovered sources. Existing prompts, validation, limits, and output files are retained.
- `selenium`: direct keyword search on explicitly selected portals, using source-specific adapters. No LLM calls or API keys are required.

## Setup

Python 3.12 or 3.13 and Google Chrome are required. From this directory:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Or use `uv sync --extra test --python 3.12`. For Browser Use, also run `uvx browser-use install` and configure the selected LLM key in `.env`.

Selenium Manager obtains a matching ChromeDriver on first execution; that step needs network access. Optionally set `SE_CACHE_PATH` to a writable driver-cache directory. See [Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/).

## Run

For the integrated manual UI flow, see [Phase A backend/worker runbook](../specs-careeros/CRAWLER_PHASE_A.md). The existing CareerOS FastAPI backend owns the PostgreSQL queue and migrations; `python -m app.crawler.worker` runs separately in the backend environment and invokes this repository's private Selenium-only JSONL entry point. No crawler HTTP service or server Browser Use is started. Page/day/job limits are configured from the Job Crawler UI; the CLI workflows below remain available independently.

Existing Browser Use workflow (uses the existing `.env` settings):

```powershell
.venv/Scripts/python.exe main.py
.venv/Scripts/python.exe main.py --mode browser-use --keyword "AI Engineer loker"
```

Direct deterministic search:

```powershell
.venv/Scripts/python.exe main.py --mode selenium --portals linkedin jobstreet --keyword "AI Engineer" --days 7 --max-pages 2 --max-jobs 20
.venv/Scripts/python.exe main.py --mode selenium --portals jobstreet --keyword "Data Analyst" --headed
.venv/Scripts/python.exe main.py --mode selenium --portals glints indeed --keyword "AI Engineer" --max-jobs 10
```

Omitting `--portals` in Selenium mode selects all seven supported portals. Keyword defaults to `SEARCH_KEYWORD` or `AI Engineer`. Run `main.py --help` for options.

New adapters can be tested individually on Linux:

```bash
python main.py --mode selenium --portals kalibrr --keyword "AI Engineer" --max-pages 1 --max-jobs 3
python main.py --mode selenium --portals techinasia --keyword "data engineer" --max-pages 1 --max-jobs 3
xvfb-run -a -s "-screen 0 1440x1000x24" python main.py --mode selenium --portals dealls --keyword "data engineer" --headed --max-pages 1 --max-jobs 3
```

Deployment direction: scheduled server crawling uses Selenium adapters. Browser Use remains in this repository for local, optional crawling. The planned local workflow is Browser Use -> CSV export -> dashboard Jobs upload. CSV export/import and dashboard integration are separate follow-up work and are not implemented by these adapters; current crawl artifacts remain JSON.

| Portal | Default browser | Date behavior |
| --- | --- | --- |
| LinkedIn | Headless | `f_TPR` requests the selected number of days |
| JobStreet | Visible | `daterange` requests the selected number of days |
| Glints | Visible | `sortBy=LATEST`; **no age cutoff** is requested or enforced |
| Indeed | Headless | `fromage` requests the selected number of days |
| Dealls | Visible | Portal default relevance ordering; **no age cutoff** |
| Kalibrr | Headless | `sort=Freshness`; **no age cutoff** |
| Tech in Asia | Headless | Indonesia search filter; **no age cutoff** |

Defaults are adapter-specific: JobStreet, Glints and Dealls use a visible browser because headed access succeeded where headless access was challenged or blocked. `--headed` forces visible browsers for every selected portal; `--headless` explicitly forces headless for every portal. These flags are mutually exclusive. The effective setting is recorded as `sources[].headless`; `request.headless=null` means automatic per-portal selection. Visible mode does not guarantee portal access.

- `--max-jobs`: cap on distinct detail attempts **per portal**, not a guarantee of accepted jobs.
- `--max-pages`: listing pages for JobStreet; initial listing plus additional load-more batches for LinkedIn; observed next-page controls or scroll batches for Glints and Indeed.
- `--timeout`: navigation / explicit wait timeout, in seconds.
- `--delay`: pacing between browser operations, default two seconds.
- `--auto-verify`: on JobStreet/Indeed only, try exposed unchecked checkboxes inside a Cloudflare challenge iframe, then wait for the challenge page to clear. Normal listing/detail validation still determines success. Disabled by default; other portals keep their existing access handling.
- `--verification-max-clicks`: maximum successful click commands per verification stage, default 1, range 1-20. Set 5 to permit up to five total clicks (not five extra retries). Retry only while the challenge remains and an enabled, unchecked control is available, at least five seconds after the previous click. Checked controls are never toggled off. Once the cap is reached, keep waiting for the last click's result until the verification deadline.
- `--verification-timeout`: verification-stage deadline with `--auto-verify`, default 60 seconds, maximum 300. An unavailable checkbox, inaccessible shadow DOM, or unsuccessful verification remains `challenge_blocked`. This option does not guarantee access or solve other verification tasks.
- `--location`: Indonesia by default. JobStreet, Glints, Dealls, Kalibrr and Tech in Asia currently support Indonesia only. Indeed uses an empty `l` for nationwide Indonesia or the supplied city. For another LinkedIn location, also supply its matching `--linkedin-geo-id`.
- `--output-dir`: output parent for either strategy, default `output/runs`.
- `--indeed-user-data-dir`: dedicated Chrome user-data directory reused only for Indeed. The directory is created if missing; the resolved path is recorded in the request, and Indeed's source records `browser_profile=persistent`. Other portals use their existing temporary profiles. Requires Indeed in `--portals`.

Portal/date/browser CLI options apply only to Selenium and are rejected in Browser Use mode. Browser Use retains its `.env` limits (`MAX_SEARCH_PAGES`, `MAX_SOURCES`, `MAX_JOBS_PER_SOURCE`, `DISCOVERY_STEPS`, `EXPLORER_STEPS`).

For a bounded JobStreet/Indeed verification attempt on a server:

```bash
xvfb-run -a python main.py --mode selenium --portals jobstreet indeed --keyword "AI Engineer" --max-pages 1 --max-jobs 3 --headed --auto-verify --verification-max-clicks 5 --verification-timeout 60
```

Each challenge stage logs its outcome to `sources[].verification_attempts` in the run manifest, including `checkbox_clicked`, `click_count`, and `max_clicks`. `--verification-timeout` is the total deadline for the stage, shared by all retries, not a new timeout per click. The crawler stops clicking when the challenge clears and validates the portal's listing/detail content before collecting jobs. A cleared challenge is not proof that jobs were extracted. The checkbox interaction is fixture-tested; live Cloudflare behavior may differ.

Widget discovery uses native WebDriver shadow-root traversal, including closed roots exposed by Chrome, both around the iframe and inside it. Ordinary JavaScript `element.shadowRoot` discovery misses closed widgets even when the checkbox is visibly rendered.
If CSS hides the input, the crawler can click its visible associated label. The label must belong to the discovered checkbox inside the Cloudflare frame.

Azure live check on 2026-11-06: run `20261106T163131Z-62c0cc` extracted one JobStreet job without a challenge on that attempt. Indeed recorded `checkbox_clicked=true`, but its challenge did not clear within the 30-second verification deadline. Clicking the widget is verified; successful Indeed clearance is not. The complete suite passed 152 tests, including open/closed shadow roots and hidden-input label interactions in local Chrome fixtures.

### Indeed persistent-profile experiment

No Google account or Indeed login is required to create this profile. In the crawler directory, from an SSH session with working X11 forwarding (`echo "$DISPLAY"` is non-empty), open ordinary Chrome with a dedicated profile:

```bash
google-chrome --user-data-dir="$PWD/.browser-profiles/indeed" 'https://id.indeed.com/jobs?q=AI+Engineer&l=&fromage=7'
```

Complete verification manually until listings appear, then close every Chrome window using that dedicated profile and wait for Chrome to exit. Reuse the exact same directory, Linux user, and server for the crawler:

```bash
python main.py --mode selenium --portals indeed --keyword "AI Engineer" --max-pages 1 --max-jobs 3 --headed --indeed-user-data-dir "$PWD/.browser-profiles/indeed" --auto-verify --verification-max-clicks 1 --verification-timeout 120
```

Manual Chrome and Selenium cannot use this directory concurrently; parallel crawler runs also need separate profiles. If Chrome reports a profile-in-use/startup failure, close its owning browser before retrying; do not delete profile lock files while it is running. `.browser-profiles/` is Git-ignored because it contains browser session data. Without this flag, the current temporary-profile behavior is preserved. Reusing browser state is an experiment, not proof that Cloudflare will accept Selenium. The feature's local tests verify persistence and portal isolation, not live Indeed clearance.

## Structure

```text
src/browser_lab/          Existing Google discovery / Browser Use exploration
src/crawler/cli.py       Strategy selection, no backend integration
src/crawler/models.py    Validated request, portal identity, normalized job
src/crawler/runner.py    Selenium lifecycle, bounded collection, checkpoints
src/crawler/adapters/    Portal-specific URLs, discovery, waits, extraction
```

Each portal adapter implements `search_url`, `reference`, and `card_links`; it configures detail selectors and optionally overrides `advance`. Register a new adapter in `ADAPTERS` and add its name to `PORTALS`. Keep portal selectors and pagination rules out of the runner.

Dealls discovers indexed `/en/loker/<job>~<company>` cards and follows the observed See More button. Its `external_id` is the complete route slug (including company), because the listing does not expose the native detail-only ID. Locale and tracking parameters do not change this identity; a portal slug change can change identity. Kalibrr uses the numeric `/c/<company>/jobs/<id>/<slug>` ID and the observed Load more jobs button. Tech in Asia uses `/jobs/<UUID>` and title anchors, excluding employers/search/apply routes. All three follow observed pagination controls or newly loaded scroll results; absent pagination is reported as unavailable rather than silently treated as end of results.

Descriptions are read from the observed job sections, excluding company profiles and recommendations. Dealls retains Job Description, Requirements and Benefits; Kalibrr retains description, qualifications and job benefits; Tech in Asia retains the combined description/requirements and Required skills. Explicit standalone requirements populate `requirements` for Dealls and Kalibrr. Matching page JobPosting metadata supplements posting dates/location for Dealls and Tech in Asia. Kalibrr preserves the page's own `datePosted`; recruiter activity and Dealls' Actively hiring text are not treated as posting dates. `--days` is not enforced for these three adapters, as recorded in their `date_filter` manifest fields.

The runner collects and checkpoints observed card IDs **for one listing page/batch**, then extracts and checkpoints that batch's details before advancing to the next page/batch. Identity is `(portal, external_id)`, independent of keyword, pagination, and tracking parameters. Each detail must have the requested ID in its final URL plus a visible title and description. Explicit waits coordinate page readiness; see [Selenium waits](https://www.selenium.dev/documentation/webdriver/waits/).

LinkedIn uses guest listing scroll / Show more rather than interpreting selected-card `position` or `pageNum` as page-navigation commands. JobStreet uses `daterange` and `page`. Glints and Indeed follow observed next controls without inventing page sizes or offsets. Unrecognized pagination is recorded as `pagination_unavailable`, rather than assumed to be the last page. An explicit disabled next control ends collection.

Glints identifies jobs by the UUID in the observed detail URL; Indeed uses `jk`/`vjk`, independent of tracking parameters. Glints detail selectors use observed accessibility labels and scoped company/salary elements. Its own matching JobPosting JSON-LD supplements location and posting date. Related-job cards are not used for detail fields. `identifier.value` in Glints JSON-LD can identify the company and is not treated as a job ID.

The date filter is requested from each portal where supported; relative posting text is preserved, not converted to an independently verified posting date. Glints records `date_filter=latest_sort_only_no_age_filter` in its source manifest: `--days` does not filter Glints results. A posting date may be available in `posted_at_raw`, including dates older than the requested range.

If Glints asks guests to log in for further results, pagination stops with `pagination_login_required`; the runner still extracts public detail URLs already discovered and marks the source partial. It does not click login or navigate around the guest limit.

## Output and failure behavior

Each run creates `output/runs/<run-id>/manifest.json` and `jobs.json`. Selenium additionally writes `<portal>-<job-id>.json` for each accepted job. Both strategies expose the existing job fields (`title`, `job_url`, `company`, `location`, `description`, `requirements`, `salary`, `application_url`) and search provenance. Selenium adds `portal`, `external_id`, `extraction_method`, `raw_description`, `posted_at_raw`, `observed_url`, and `crawled_at`.

Selenium also checkpoints **`discovered.json`** as soon as cards are collected. Its `jobs` list contains portal ID, canonical URL, exact observed card URL, title, search provenance, and optional card company/location/salary/snippet. These are discovery records, not full descriptions. The same snapshots appear in `manifest.discovered_jobs`. They survive a later login gate, challenge, timeout, or browser failure; `jobs.json` continues to contain only successfully extracted complete details. A source with discovered cards but blocked details is `partial`, with the blocking reason recorded separately. Discovery snapshots obey `--max-jobs` per portal just like detail attempts.

Indeed opens observed cards in their public search-page context and reads the selected detail panel instead of automatically navigating to `/viewjob`. Panel extraction requires matching `vjk` plus a matching panel job marker; without a marker it checks title and, after switching cards, a changed/replaced description panel. This avoids mixing two same-title jobs. Standalone public detail pages can still be parsed, but no alternative authenticated endpoint is tried when access requires login. A dismissible sign-in dialog can be closed once per detail; mandatory sign-in, including `secure.indeed.com/auth` with session path parameters, stops the portal immediately as `login_required`. Account session identifiers are omitted from diagnostic URLs.

All seven adapters schedule details **per listing page/batch** (`sources[].detail_schedule=per_page`): collect and checkpoint page 1 cards, attempt and save their details, then advance to page 2. A later pagination challenge therefore cannot prevent those earlier detail attempts or remove saved jobs. LinkedIn, JobStreet, Glints, Dealls, Kalibrr and Tech in Asia reuse one separate detail tab for the batch, then close it and return to the original listing tab. This preserves the listing's scroll/load-more state without replaying earlier pages. Indeed retains its public selected-panel flow in the listing tab. The total distinct-ID cap and deduplication apply across pages. Mandatory login/challenges stop the portal, including when they occur on a detail; the runner does not advance or retry around the gate. Detail failure diagnostics include description/panel counts and iframe host/path information to distinguish a missing panel from an embedded document or access gate.

JobStreet run `20261103T070521Z-08f5bd` motivated this change: the previous discovery-first schedule collected 90 cards on pages 1–3, then encountered verification on page 4 before any detail attempts. With the per-page schedule, details for each earlier page are attempted and saved before page 4 is requested. This improves retention of completed work; it does not guarantee that detail requests or subsequent pages avoid security challenges. Existing CLI commands and pacing settings remain applicable.

Selenium preserves complete rendered description text. It does not guess requirement sections or application links; those fields remain null when not explicitly extracted. Salary and other missing optional fields remain null. Portal search results are retained without the Browser Use lab's AI-role-specific relevance filter; ranking can happen separately.

Checkpoints retain accepted jobs when a later page/detail fails. Detail failures normally allow the next ID to proceed. Authentication, visible security challenges, and access denial stop that portal. There is no login, application submission, CAPTCHA solving, or automatic Browser Use fallback. The browser closes after each portal. Failure diagnostics include the final URL, page title, and a short visible-body excerpt; no screenshot is saved.

Selenium exits with code 1 if any portal has errors; inspect `sources`, per-detail states, and `errors` in the manifest. Empty results require an explicit empty/end indication; a timeout is recorded as a failure rather than silently reporting zero jobs.

Browser Use also exits with code 1 for `completed_with_errors`. Source outcomes `partial`, `login_required`, `challenge_blocked`, `access_denied` and `failed` are recorded as structured exploration errors even when the agent returns normally. Source records include `reported_status` and rejection-reason counts. A claimed success with missing/unsafe job URLs is downgraded to partial. Valid accepted jobs remain saved. Genuine no-relevant-job outcomes and jobs rejected solely for relevance/duplication do not by themselves indicate execution failure. This corrects aggregate reporting; it does not repair a site's search controls or the extraction tool's schema compatibility.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest -q
# Optional real Chrome checks against synthetic local fixtures:
$env:CRAWLER_BROWSER_TESTS = '1'
.venv/Scripts/python.exe -m pytest -q
```

Tests cover search filters, identity normalization, foreign-link rejection, invalid inputs, deduplication, partial failures, challenge handling, cleanup, CLI routing, and fixture DOM extraction. Synthetic fixtures do not establish that live portal selectors still work.

Live verification on 2026-11-02: LinkedIn guest search/detail extraction succeeded. JobStreet headless access was challenged; the user subsequently confirmed extraction with a visible browser. Glints headed search and two detail extractions succeeded; headless access was challenged. Indeed headless access returned Request Blocked, and headed access required additional verification; its extraction and pagination are fixture-tested but not live-verified. The adapters record these access conditions without bypassing verification. Browser Use routing is regression-tested without spending LLM tokens.

The user's later headed Indeed run discovered cards but redirected `/viewjob` requests to the account page. Login detection and discovery persistence were fixed, and public-panel support was added with fixture tests. A subsequent live retry was blocked before listing cards loaded, so the new panel flow remains unverified against the live site. Glints without `--headed` still uses the adapter's visible-browser default; inspect `sources[].headless` or explicitly pass `--headless` to test actual headless mode.

Follow-up on 2026-11-03: run `20261102T115443Z-fa530c` timed out at discovery despite visible listing text; the manifest alone cannot distinguish missing selectors, rejected IDs, and transient metadata. Indeed now accepts title links across heading levels and supports validated `data-jk` identity on the trusted listing when `href` is absent. Optional stale metadata no longer discards an already identified card. Listing failures include candidate counts and compact ID/path samples for diagnosis. The next bounded live run discovered and saved two cards, but both public-panel detail attempts timed out; full Indeed detail extraction is still not live-verified.

Run `20261102T214729Z-39ff56` discovered 16 cards but encountered a challenge on `start=10` before any details were attempted under the old discovery-first schedule. The per-page schedule fixes that ordering problem. A bounded live retry after the change was challenged at the initial listing, so successful live panel extraction remains unverified. For a focused manual check use `--headed --max-pages 1 --max-jobs 5`; longer timeouts cannot resolve an explicit access challenge.

Successful panel verification on 2026-11-03: run `20261102T215253Z-96945b` showed complete visible descriptions but zero matches for the old `#jobDescriptionText` selector. Live DOM inspection identified the newer layout's `[data-testid="vj-job-title"]` (an h5) and `.simple-job-description-html`. The adapter now supports both layouts, scopes company links to `company-info-metadata`, and can retain matching card location/salary when the panel omits those fields. A bounded visible description-section fallback handles changed wrappers without reading the whole panel, recommendations, or footer. Hidden/noninteractive title links are excluded from discovery.

After these fixes, live run **`20261102T220312Z-1fd23b` completed with 5 discovered and 5 accepted jobs**, using `--headed --max-pages 1 --max-jobs 5`. Title, company, location and full description were saved in `jobs.json`. The earlier per-page and authentication fixes remain in place. This establishes successful first-page public-panel extraction; headless access and later pages may still encounter portal challenges.

New adapter verification on 2026-11-03 (local Windows Chrome): `20261103T061328Z-856653` saved 2/2 Tech in Asia details headless and 1/2 Kalibrr details headless; the second Kalibrr card redirected to the portal's 404 page. Dealls headless returned a Cloudflare access block. Headed Dealls run `20261103T061522Z-8976d4` saved 2/2 details. These are bounded first-page checks, not Azure verification. Full regression verification after adding the adapters: 104 tests passed, including local Chrome DOM fixtures.

Pagination inspection then exposed transient Kalibrr landing-page cards before keyword-result hydration. The adapter now waits for the card identity list to remain stable for two seconds before checkpointing each batch. After this fix, headless keyword `AI Engineer` run `20261103T061937Z-2b76f6` saved 2/2 details. A listing-only Kalibrr check followed Load more jobs from 15 to 30 cards (15 new IDs). The bounded `data engineer` Dealls and Tech in Asia checks had no observable next control/end indicator and reported `pagination_unavailable`, so complete traversal was not established in those checks. Two additional unit regressions covered Kalibrr hydration and Cloudflare block classification.

### Listing completion (2026-11-07)

`--max-pages` is a ceiling. A confirmed empty/end listing stops successfully with
`stop_reason=listing_exhausted`; the final end probe does not add a processed page.
Missing navigation or a timeout alone still produces an error, preserving partial
results. Other detail failures are not cleared by reaching the end of a listing.

Dealls matches the keyword's public Next.js result identities against rendered
cards and the advertised total, excluding recommendation cards from the end-count
comparison. Tech in Asia compares its visible result total with unique cards.
The shared adapter supports positive end markers, while observed pagination also
recognizes disabled next controls. Portal-specific access checks remain in effect.
Local Chrome fixtures and replay of saved public listing snapshots verify these
paths; they do not establish current live Azure portal access.

Dashboard/API portal availability is controlled by `CRAWLER_ENABLED_PORTALS` in
the **backend** environment, not this CLI. Indeed remains registered here and may
be tested explicitly with `--portals indeed` even when hidden in the dashboard.
