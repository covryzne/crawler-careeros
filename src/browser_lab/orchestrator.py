import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .config import load_settings
from .discovery import discover
from .explorer import explore
from .validation import canonical_url, is_safe_public_url, relevance_decision


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    tmp.replace(path)


async def run(output_dir: Path = Path('output/runs')) -> dict:
    settings = load_settings()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    root = output_dir / run_id
    root.mkdir(parents=True, exist_ok=True)
    manifest = {'run_id': run_id, 'mode': 'browser-use', 'keyword': settings.keyword, 'state': 'running',
                'search_pages': [], 'sources': [], 'jobs': [], 'errors': []}
    save_json(root / 'manifest.json', manifest)
    seen_sources, seen_jobs = set(), set()
    source_count = 0
    print(f'[LAB] keyword={settings.keyword!r}, pages={settings.max_search_pages}, '
          f'sources(max TOTAL)={settings.max_sources}, jobs/source={settings.max_jobs_per_source}')

    for page_number in range(1, settings.max_search_pages + 1):
        if source_count >= settings.max_sources:
            break
        print(f'[SERP {page_number}/{settings.max_search_pages}] Discover')
        page_record = {'page': page_number, 'state': 'running', 'sources_found': 0}
        manifest['search_pages'].append(page_record)
        save_json(root / 'manifest.json', manifest)
        try:
            output, debug = await discover(settings, page_number, count=10)
            save_json(root / f'serp-page-{page_number:02d}.json', output.model_dump(mode='json'))
            save_json(root / f'serp-page-{page_number:02d}-debug.json', debug)
            page_record.update(state='completed', sources_found=len(output.sources))
        except Exception as exc:
            page_record.update(state='failed', error=f'{type(exc).__name__}: {exc}')
            manifest['errors'].append({'search_page': page_number, 'error': page_record['error']})
            save_json(root / 'manifest.json', manifest)
            continue
        save_json(root / 'manifest.json', manifest)

        # Crucial ordering: process every discovered source immediately before next SERP page.
        for hit in output.sources:
            if source_count >= settings.max_sources:
                break
            source_url = str(hit.url)
            if not is_safe_public_url(source_url):
                manifest['errors'].append({'source_url': source_url, 'error': 'unsafe or unsupported URL'})
                save_json(root / 'manifest.json', manifest)
                continue
            source_key = canonical_url(source_url)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            source_count += 1
            index = source_count
            record = {'source_index': index, 'search_page': page_number, 'search_title': hit.title,
                      'source_url': source_url, 'state': 'running', 'jobs_found': 0, 'jobs_accepted': 0}
            manifest['sources'].append(record)
            save_json(root / 'manifest.json', manifest)
            print(f'[SOURCE {index}/{settings.max_sources}] {source_url}')
            try:
                result, debug = await explore(settings, source_url)
                if canonical_url(str(result.source_url)) != source_key:
                    raise ValueError('Explorer changed source_url; exact SERP URL not preserved')
                raw = result.model_dump(mode='json')
                accepted, rejected = [], []
                for job in result.jobs[:settings.max_jobs_per_source]:
                    if job.job_url is None:
                        rejected.append({'job': job.model_dump(mode='json'), 'reason': 'missing unique job detail URL'})
                        continue
                    job_url = str(job.job_url)
                    if not is_safe_public_url(job_url):
                        rejected.append({'job': job.model_dump(mode='json'), 'reason': 'invalid/unsafe job URL'})
                        continue
                    relevant, reason = relevance_decision(settings.keyword, job)
                    if not relevant:
                        rejected.append({'job': job.model_dump(mode='json'), 'reason': reason})
                        continue
                    key = canonical_url(job_url)
                    if key in seen_jobs:
                        rejected.append({'job': job.model_dump(mode='json'), 'reason': 'duplicate job URL'})
                        continue
                    seen_jobs.add(key)
                    accepted.append({'keyword': settings.keyword, 'search_page': page_number,
                                     'discovered_from': source_url, 'relevance_reason': reason,
                                     **job.model_dump(mode='json')})
                # Save full raw extraction, including jobs rejected by relevance checks.
                save_json(root / f'source-{index:02d}.json', {'exploration': raw, 'accepted_jobs': accepted, 'rejected_jobs': rejected})
                save_json(root / f'source-{index:02d}-debug.json', debug)
                manifest['jobs'].extend(accepted)
                rejection_reasons = dict(Counter(item['reason'] for item in rejected))
                incomplete_urls = any(reason in rejection_reasons for reason in (
                    'missing unique job detail URL', 'invalid/unsafe job URL'))
                source_state = 'partial' if result.status == 'success' and incomplete_urls else result.status
                record.update(state=source_state, reported_status=result.status, page_type=result.page_type,
                              jobs_found=len(result.jobs), jobs_accepted=len(accepted),
                              jobs_rejected=len(rejected), rejection_reasons=rejection_reasons,
                              notes=result.notes)
                if source_state not in {'success', 'no_relevant_jobs'}:
                    manifest['errors'].append({
                        'phase': 'exploration', 'source_url': source_url,
                        'code': f'SOURCE_{source_state.upper()}', 'status': source_state,
                        'error': result.notes or f'Source exploration ended with status {source_state}',
                        'jobs_accepted': len(accepted), 'rejection_reasons': rejection_reasons,
                    })
                save_json(root / 'jobs.json', {'keyword': settings.keyword, 'jobs': manifest['jobs']})
            except Exception as exc:
                record.update(state='failed', error=f'{type(exc).__name__}: {exc}')
                manifest['errors'].append({'source_url': source_url, 'error': record['error']})
                print(f'[WARN] {record["error"]}')
            finally:
                save_json(root / 'manifest.json', manifest)

    manifest['state'] = 'completed_with_errors' if manifest['errors'] else 'completed'
    save_json(root / 'jobs.json', {'keyword': settings.keyword, 'jobs': manifest['jobs']})
    save_json(root / 'manifest.json', manifest)
    print(f'[DONE] sources={source_count}, accepted_jobs={len(manifest["jobs"])}. Output: {root}')
    return manifest


def main(output_dir: Path = Path('output/runs')):
    result = asyncio.run(run(output_dir))
    if result['state'] != 'completed':
        raise SystemExit(1)
