"""Inspect public rendered pages for adapter development."""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.crawler.models import CrawlRequest
from src.crawler.runner import create_driver

URLS = {
    'dealls': 'https://dealls.com/en?searchJob=data',
    'kalibrr': 'https://www.kalibrr.com/id-ID/home/te/ai-engineer?sort=Freshness',
    'techinasia': 'https://www.techinasia.com/jobs/search?query=data%20engineer&country_name%5B%5D=Indonesia',
}
driver = create_driver(CrawlRequest(keyword='data', portals=('linkedin',), headless=False, timeout=30))
root = Path('output/probes')
root.mkdir(parents=True, exist_ok=True)
try:
    for name, url in URLS.items():
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        try:
            driver.get(url)
            time.sleep(6)
            for phase in ('listing', 'detail'):
                data = driver.execute_script('''return {
                  url: location.href, title: document.title, body: document.body.innerText.slice(0,18000),
                  links: [...document.querySelectorAll('a[href]')].filter(a => /\\/loker\\/|\\/c\\/[^/]+\\/jobs\\/|\\/jobs\\/[^/?]+$/.test(a.pathname)).slice(0,12).map(a=>({href:a.href,text:a.innerText,html:a.outerHTML.slice(0,2000)})),
                  headings: [...document.querySelectorAll('h1,h2,h3')].slice(0,30).map(e=>e.outerHTML),
                  sections: [...document.querySelectorAll('[itemprop],[data-testid],[class*="description"],[class*="Description"],article')].slice(0,30).map(e=>e.outerHTML.slice(0,5000)),
                  buttons: [...document.querySelectorAll('button,a[rel="next"]')].map(e=>({text:e.innerText,html:e.outerHTML.slice(0,800)})).slice(-30),
                  jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(e=>e.textContent)
                }''')
                (root / f'{name}-{phase}.json').write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                (root / f'{name}-{phase}.html').write_text(driver.page_source, encoding='utf-8')
                print(json.dumps({'portal': name, 'phase': phase, 'url': data['url'], 'title':data['title'], 'links':len(data['links'])}), flush=True)
                if phase == 'listing':
                    candidates = [link for link in data['links'] if link['text'].strip()
                                  and '/loker/saved' not in link['href']
                                  and '/loker/applied' not in link['href']
                                  and '/jobs/search' not in link['href']]
                    if name == 'techinasia':
                        candidates = [link for link in candidates if re.search(r'/jobs/[0-9a-f-]{36}$', link['href'])]
                    if not candidates:
                        break
                    driver.get(candidates[0]['href'])
                    time.sleep(5)
        except Exception as exc:
            print(name, type(exc).__name__, str(exc)[:250], flush=True)
finally:
    driver.quit()
