"""Opt-in container smoke test against a data URL; never crawls a portal."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.environ.get("CRAWLER_ROOT", "/app/crawler"))

from src.crawler.runner import create_driver

mode = os.environ.get("CRAWLER_BROWSER_MODE", "headless")
request = SimpleNamespace(headless=mode != "headed", timeout=15)
with create_driver(request) as browser:
    browser.get("data:text/html,<title>CareerOS browser check</title><p>Local fixture</p>")
    assert browser.title == "CareerOS browser check"
    arguments = browser.execute_cdp_cmd("Browser.getBrowserCommandLine", {})["arguments"]
    actual_headless = any(value.startswith("--headless") for value in arguments)
    assert actual_headless == request.headless
    print(f"Browser smoke passed: mode={mode}, headless={actual_headless}")
