"""Read-only DOM inspection for portal adapter development; no login or challenge solving."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.crawler.models import CrawlRequest
from src.crawler.runner import create_driver

parser = argparse.ArgumentParser()
parser.add_argument('portal', choices=('glints', 'indeed'))
parser.add_argument('--headed', action='store_true')
parser.add_argument('--detail', action='store_true')
parser.add_argument('--summary', action='store_true')
args = parser.parse_args()
urls = {
    'glints': 'https://glints.com/id/opportunities/jobs/explore?keyword=ai+engineer&country=ID&locationName=All+Cities%2FProvinces&lowestLocationLevel=1&sortBy=LATEST',
    'indeed': 'https://id.indeed.com/jobs?q=ai+engineer&l=&fromage=7',
}
driver = create_driver(CrawlRequest(keyword='AI Engineer', portals=('linkedin',),
                                   headless=not args.headed, timeout=30))
try:
    driver.get(urls[args.portal])
    time.sleep(5)
    if args.detail:
        links = driver.find_elements('css selector', 'a[aria-label^="Job card title:"]')
        if links:
            driver.get(links[0].get_attribute('href'))
            time.sleep(3)
    data = driver.execute_script('''return {
      url: location.href, title: document.title, body: document.body.innerText.slice(0, 2500),
      links: [...document.querySelectorAll('a[href]')].filter(a => /opportunities\\/jobs\\/(?!explore)|[?&](jk|vjk)=/.test(a.href)).slice(0, 12).map(a => ({href:a.href,text:a.innerText,html:a.outerHTML.slice(0,1200)})),
      headings: [...document.querySelectorAll('h1,h2,h3')].slice(0,12).map(e => e.outerHTML),
      sections: [...document.querySelectorAll('[class*="Description"],[class*="Location"],[class*="Salary"],[class*="Pagination"],[data-testid],[data-cy]')].slice(0,30).map(e => e.outerHTML.slice(0,1500)),
      pagination: [...document.querySelectorAll('button,a')].filter(e => /next|berikut|selanjutnya/i.test((e.getAttribute('aria-label')||'')+' '+e.innerText)).slice(0,8).map(e => e.outerHTML),
      jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(e => e.textContent.slice(0,2000))
    }''')
    if args.portal == 'indeed':
        from src.crawler.adapters.indeed import IndeedAdapter
        adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
        candidates = adapter.card_links(driver)
        checks = []
        for link in candidates[:4]:
            try:
                href = link.get_attribute('href') or ''
                ref = adapter.reference(href, link.text, driver.current_url, 1)
                checks.append({'href': href[:180], 'recognized': ref is not None,
                               'metadata': adapter.card_metadata(link, ref) if ref else None})
            except Exception as exc:
                checks.append({'error': f'{type(exc).__name__}: {exc}'})
        data['adapter_check'] = {'candidate_count': len(candidates), 'checks': checks,
                                 'collected_count': len(adapter.collect(driver, 1))}
    root = Path('output/probes')
    root.mkdir(parents=True, exist_ok=True)
    suffix = '-detail' if args.detail else ''
    (root / f'{args.portal}{suffix}.html').write_text(driver.page_source, encoding='utf-8')
    (root / f'{args.portal}{suffix}.json').write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: data[k] for k in ('url', 'title', 'adapter_check') if k in data}
                     if args.summary else data, indent=2, ensure_ascii=True))
finally:
    driver.quit()
