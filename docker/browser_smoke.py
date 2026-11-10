"""Opt-in container smoke test against a data URL; never crawls a portal."""

import os
import sys

sys.path.insert(0, os.environ.get("CRAWLER_ROOT", "/app/crawler"))

from src.crawler.models import CrawlRequest
from src.crawler.runner import create_driver


def main():
    mode = os.environ.get("CRAWLER_BROWSER_MODE", "headless")
    if mode not in {"headless", "headed", "auto"}:
        raise SystemExit("Invalid CRAWLER_BROWSER_MODE")
    # Exercise consecutive sessions on the same virtual display. Auto must support
    # both browser modes because each portal selects its own default.
    sessions = [False, True] if mode == "auto" else [mode == "headless"] * 2
    for index, headless in enumerate(sessions, 1):
        request = CrawlRequest(
            keyword="browser-smoke",
            portals=("linkedin",),
            headless=headless,
            timeout=15,
            delay=0,
            max_pages=1,
            max_jobs=1,
        )
        with create_driver(request) as browser:
            browser.get(
                "data:text/html,<title>CareerOS browser check</title><p>Local fixture</p>"
            )
            assert browser.title == "CareerOS browser check"
            arguments = browser.execute_cdp_cmd("Browser.getBrowserCommandLine", {})[
                "arguments"
            ]
            actual_headless = any(value.startswith("--headless") for value in arguments)
            assert actual_headless == request.headless
        print(
            f"Browser smoke session {index}/2 passed: mode={mode}, headless={headless}",
            flush=True,
        )
    print(f"Browser smoke passed: mode={mode}, sessions=2", flush=True)


if __name__ == "__main__":
    main()
