import json
import time
import uuid
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.common.exceptions import NoSuchDriverException, TimeoutException
from selenium.webdriver.common.by import By

from .adapters import ADAPTERS
from .adapters.base import CrawlProblem, access_problem
from .artifacts import capture_failure
from .models import CrawlRequest


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def create_driver(request):
    options = webdriver.ChromeOptions()
    if request.headless is not False:
        options.add_argument('--headless=new')
    options.add_argument('--window-size=1440,1000')
    if request.indeed_user_data_dir:
        profile = Path(request.indeed_user_data_dir)
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        options.add_argument(f'--user-data-dir={profile}')
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(request.timeout)
    return driver


def diagnostics(driver, adapter=None):
    if driver is None:
        return {}
    try:
        bodies = driver.find_elements(By.CSS_SELECTOR, 'body')
        url = driver.current_url
        parts = urlsplit(url)
        if parts.hostname == 'secure.indeed.com' and parts.path.split(';', 1)[0].rstrip('/') == '/auth':
            url = 'https://secure.indeed.com/auth'  # Do not persist account session IDs or continuation tokens.
        data = {'observed_url': url, 'page_title': driver.title,
                'body_excerpt': bodies[0].text[:2000] if bodies else ''}
        if adapter is not None:
            try:
                data.update(adapter.discovery_diagnostics(driver))
            except Exception:
                data['discovery_diagnostics_unavailable'] = True
        return data
    except Exception:
        return {'diagnostics_unavailable': True}


def run(request: CrawlRequest, output_dir: Path = Path('output/runs'), driver_factory=None,
        event_sink=None, seen_ids=None):
    driver_factory = driver_factory or create_driver
    seen_ids = set(seen_ids or ())

    def emit(kind, **data):
        if event_sink is not None:
            event_sink({'type': kind, **data})
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    root = Path(output_dir) / run_id
    manifest = {'run_id': run_id, 'mode': 'selenium', 'state': 'running',
                'request': asdict(request), 'sources': [], 'errors': [], 'jobs': [],
                'discovered_jobs': []}

    def checkpoint():
        save_json(root / 'jobs.json', {'keyword': request.keyword, 'jobs': manifest['jobs']})
        save_json(root / 'discovered.json', {'keyword': request.keyword, 'jobs': manifest['discovered_jobs']})
        save_json(root / 'manifest.json', manifest)

    checkpoint()
    for portal in request.portals:
        adapter_class = ADAPTERS[portal]
        portal_request = replace(request,
                                 indeed_user_data_dir=(request.indeed_user_data_dir if portal == 'indeed' else None),
                                 headless=(request.headless if request.headless is not None
                                  else getattr(adapter_class, 'default_headless', True)))
        record = {'portal': portal, 'state': 'running', 'pages': [], 'details': [],
                  'jobs_discovered': 0, 'jobs_accepted': 0, 'stop_reason': None,
                  'headless': portal_request.headless,
                  'date_filter': getattr(adapter_class, 'date_filter', 'portal_search_filter')}
        if portal_request.indeed_user_data_dir:
            record['browser_profile'] = 'persistent'
        manifest['sources'].append(record)
        emit('source_started', platform=portal, headless=portal_request.headless,
             date_filter=record['date_filter'])
        driver = None
        adapter = adapter_class(portal_request)
        refs = {}
        per_page = getattr(adapter, 'details_per_page', False)
        record['detail_schedule'] = 'per_page' if per_page else 'after_discovery'

        def process_details(references):
            for ref in references:
                detail = {'external_id': ref.external_id, 'url': ref.url, 'state': 'running'}
                record['details'].append(detail)
                checkpoint()
                emit('detail_started', platform=portal, external_id=ref.external_id)
                try:
                    print(f'[{portal}] detail id={ref.external_id}', flush=True)
                    time.sleep(request.delay)
                    adapter.open_detail(driver, ref)
                    job = adapter.extract(driver, ref)
                    payload = job.model_dump(mode='json')
                    manifest['jobs'].append(payload)
                    record['jobs_accepted'] += 1
                    detail['state'] = 'success'
                    save_json(root / f'{portal}-{ref.external_id}.json', payload)
                    emit('job', platform=portal, job=payload)
                except Exception as exc:
                    if isinstance(exc, TimeoutException):
                        exc = access_problem(driver, include_pending=True) or exc
                    status = exc.status if isinstance(exc, CrawlProblem) else 'failed'
                    detail.update(state=status, error=f'{type(exc).__name__}: {exc}')
                    detail['failure_artifacts'] = capture_failure(
                        driver, root, portal=portal, phase='detail', status=status,
                        headless=portal_request.headless, run_id=run_id,
                        page=ref.search_page, external_id=ref.external_id,
                    )
                    detail['diagnostics'] = diagnostics(driver, adapter)
                    manifest['errors'].append({'portal': portal, 'phase': 'detail', **detail})
                    emit('detail_error', platform=portal, external_id=ref.external_id, status=status)
                    if status in {'login_required', 'challenge_blocked', 'access_denied'}:
                        record['stop_reason'] = status
                        return True
                finally:
                    checkpoint()
            return False

        checkpoint()
        page = None
        try:
            print(f'[{portal}] headless={portal_request.headless}, date_filter={record["date_filter"]}', flush=True)
            if portal_request.indeed_user_data_dir:
                print(f'[{portal}] persistent profile={portal_request.indeed_user_data_dir}', flush=True)
            driver = driver_factory(portal_request)
            emit('browser_ready', platform=portal)
            for page in range(1, request.max_pages + 1):
                print(f'[{portal}] listing page/batch={page}', flush=True)
                emit('listing_started', platform=portal, page=page)
                time.sleep(request.delay)
                try:
                    batch = adapter.advance(driver, page, set(refs) | seen_ids)
                except TimeoutException as exc:
                    # A timeout cannot establish that the portal has no more results.
                    problem = access_problem(driver, include_pending=True)
                    if problem:
                        raise problem from exc
                    raise CrawlProblem('listing_timeout', f'Listing page/batch {page} did not become ready') from exc
                if not batch:
                    record['stop_reason'] = 'listing_exhausted'
                    break  # The empty/end probe is not a processed results page.
                new = [ref for ref in batch if ref.key not in refs and ref.key not in seen_ids]
                selected = []
                for ref in new:
                    if len(refs) >= request.max_jobs:
                        break
                    refs[ref.key] = ref
                    selected.append(ref)
                    manifest['discovered_jobs'].append({'keyword': request.keyword, **asdict(ref)})
                record['pages'].append({'page': page, 'url': driver.current_url,
                                        'cards_found': len(batch), 'new_ids': len(new)})
                record['jobs_discovered'] = len(refs)
                checkpoint()
                emit('page', platform=portal, page=page, keyword=request.keyword,
                     references=[asdict(ref) for ref in selected])
                if per_page and selected:
                    session = getattr(adapter, 'detail_session', None)
                    with session(driver) if session else nullcontext():
                        stopped = process_details(selected)
                    if stopped:
                        break
                if not new:
                    if batch and seen_ids and all(ref.key in seen_ids for ref in batch):
                        continue  # Another keyword can share early pages; still honor max_pages.
                    record['stop_reason'] = 'no_new_ids'
                    break
                if len(refs) >= request.max_jobs:
                    record['stop_reason'] = 'max_jobs'
                    break
            else:
                record['stop_reason'] = 'max_pages'
        except Exception as exc:
            status = (exc.status if isinstance(exc, CrawlProblem) else
                      'driver_unavailable' if isinstance(exc, NoSuchDriverException) else
                      'browser_start_failed' if driver is None else 'failed')
            record['listing_error'] = {'status': status, 'error': f'{type(exc).__name__}: {exc}'}
            record['listing_error']['failure_artifacts'] = capture_failure(
                driver, root, portal=portal, phase='listing', status=status,
                headless=portal_request.headless, run_id=run_id, page=page,
            )
            record['listing_error']['diagnostics'] = diagnostics(driver, adapter)
            manifest['errors'].append({'portal': portal, 'phase': 'listing', **record['listing_error']})
            record['stop_reason'] = status
        # Process IDs found before a pagination failure; do not reopen blocked portals.
        blocked = record.get('listing_error', {}).get('status') in {
            'login_required', 'challenge_blocked', 'access_denied'}
        try:
            if driver is not None and not blocked and not per_page:
                process_details(refs.values())
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception as exc:
                    manifest['errors'].append({'portal': portal, 'phase': 'cleanup', 'error': str(exc)})
            errors = [e for e in manifest['errors'] if e['portal'] == portal]
            record['state'] = ('partial' if refs or record['jobs_accepted'] else 'failed') if errors else 'completed'
            if getattr(adapter, 'verification_attempts', None):
                record['verification_attempts'] = adapter.verification_attempts
            checkpoint()
        print(f'[{portal}] discovered={len(refs)}, accepted={record["jobs_accepted"]}, state={record["state"]}')
        if record['stop_reason'] == 'listing_exhausted':
            print(f'[{portal}] All available results processed; {len(record["pages"])} page(s)/batch(es).', flush=True)
        emit('source_finished', platform=portal, state=record['state'], stop_reason=record['stop_reason'],
             pages_completed=len(record['pages']))
    manifest['state'] = 'completed_with_errors' if manifest['errors'] else 'completed'
    checkpoint()
    print(f'[DONE] {manifest["state"]}. Output: {root}')
    return manifest
