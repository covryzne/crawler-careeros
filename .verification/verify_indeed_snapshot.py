"""Verify extraction against the public panel HTML captured by inspect_indeed_panel.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.crawler.adapters.indeed import IndeedAdapter
from src.crawler.models import CrawlRequest, JobReference
from src.crawler.runner import create_driver

source = Path('output/runs/20261102T215253Z-96945b/discovered.json')
rows = json.loads(source.read_text(encoding='utf-8'))['jobs']
row = next(row for row in rows if row['external_id'] == 'c426cd39d59fcca9')
ref = JobReference(**{key: value for key, value in row.items() if key != 'keyword'})
request = CrawlRequest(keyword='AI Engineer', portals=('indeed',), headless=True, timeout=3)
driver = create_driver(request)
class CapturedPage:
    current_url = ref.discovered_from
    def __getattr__(self, name):
        return getattr(driver, name)
    def get(self, url):
        raise AssertionError('Snapshot verification must not navigate to remote pages')
try:
    driver.get(Path('output/probes/indeed-panel.html').resolve().as_uri())
    page = CapturedPage()
    adapter = IndeedAdapter(request)
    adapter.open_detail(page, ref)
    job = adapter.extract(page, ref)
    payload = job.model_dump(mode='json')
    Path('output/probes/indeed-snapshot-extraction.json').write_text(
        json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'title': job.title, 'company': job.company, 'location': job.location,
                      'description_characters': len(job.description or ''),
                      'source': 'captured public panel HTML; not a fresh network crawl'},indent=2))
finally:
    driver.quit()
