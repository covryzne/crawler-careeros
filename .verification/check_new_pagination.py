"""Bounded read-only listing/pagination check without detail requests."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.crawler.adapters import ADAPTERS
from src.crawler.models import CrawlRequest
from src.crawler.runner import create_driver

for portal in ('dealls', 'kalibrr', 'techinasia'):
    if len(sys.argv) > 1 and portal not in sys.argv[1:]:
        continue
    adapter = ADAPTERS[portal](CrawlRequest(keyword='data engineer', portals=(portal,), timeout=20,
                                          headless=ADAPTERS[portal].default_headless))
    driver = create_driver(adapter.request)
    try:
        refs = adapter.advance(driver, 1, set())
        initial = [ref.external_id for ref in refs]
        if portal == 'kalibrr':
            Path('output/probes/kalibrr-initial.html').write_text(driver.page_source, encoding='utf-8')
            print(driver.execute_script('return [...document.querySelectorAll("input[placeholder]")].map(e=>({placeholder:e.placeholder,value:e.value}))'),flush=True)
        time.sleep(4)
        settled = adapter.collect(driver, 1)
        if portal == 'kalibrr':
            Path('output/probes/kalibrr-settled.html').write_text(driver.page_source, encoding='utf-8')
            print(driver.execute_script('return [...document.querySelectorAll("input[placeholder]")].map(e=>({placeholder:e.placeholder,value:e.value}))'),flush=True)
        print(json.dumps({'portal':portal,'initial':initial[:3],
                          'settled':[r.external_id for r in settled[:3]],
                          'initial_count':len(refs),'settled_count':len(settled)}), flush=True)
        refs = adapter.advance(driver, 2, {r.key for r in settled})
        print(json.dumps({'portal':portal,'batch2_count':len(refs),
                          'new_count':len({r.key for r in refs}-{r.key for r in settled})}), flush=True)
    except Exception as exc:
        print(portal, type(exc).__name__, str(exc)[:250], flush=True)
    finally:
        driver.quit()
