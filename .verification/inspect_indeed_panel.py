"""Inspect a visible public Indeed panel; stop on access gates, never log in."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selenium.webdriver.support.ui import WebDriverWait
from src.crawler.adapters.indeed import IndeedAdapter
from src.crawler.adapters.base import access_problem
from src.crawler.models import CrawlRequest
from src.crawler.runner import create_driver

request = CrawlRequest(keyword='AI Engineer', portals=('indeed',), headless=False, timeout=20)
adapter = IndeedAdapter(request)
driver = create_driver(request)
try:
    refs = adapter.advance(driver, 1, set())
    if not refs:
        raise RuntimeError('No public cards found')
    adapter.open_detail(driver, refs[0])
    def ready(browser):
        problem = access_problem(browser)
        if problem:
            raise problem
        panel = adapter._panel(browser)
        return panel if panel is not None and len(panel.text) > 800 else False
    panel = WebDriverWait(driver, request.timeout).until(ready)
    data = driver.execute_script('''const p=arguments[0]; return {
      headings:[...p.querySelectorAll('h1,h2,h3')].map(e=>e.outerHTML),
      candidates:[...p.querySelectorAll('[id],[data-testid],[class*="escription"]')]
         .map(e=>({tag:e.tagName,id:e.id,testid:e.getAttribute('data-testid'),class:e.className,
                   text:e.innerText.slice(0,140),length:e.innerText.length})).slice(0,45),
      panel_html:p.outerHTML
    }''', panel)
    root = Path('output/probes')
    root.mkdir(parents=True, exist_ok=True)
    (root/'indeed-panel.html').write_text(data.pop('panel_html'), encoding='utf-8')
    (root/'indeed-panel.json').write_text(json.dumps(data, indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(data,indent=2,ensure_ascii=True))
finally:
    driver.quit()
