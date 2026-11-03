import re
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlsplit

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from ..models import CrawlRequest, CrawledJob, JobReference


class CrawlProblem(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def first_text(root, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        for element in root.find_elements(By.CSS_SELECTOR, selector):
            try:
                value = element.text.strip()
                if element.is_displayed() and value:
                    return value
            except StaleElementReferenceException:
                continue
    return None


def access_problem(driver, include_pending=False):
    parts = urlsplit(driver.current_url)
    path = parts.path.lower()
    if parts.hostname == 'secure.indeed.com' and path.split(';', 1)[0].rstrip('/') == '/auth':
        return CrawlProblem('login_required', 'Indeed redirected to its account sign-in page')
    if any(part in path for part in ('/authwall', '/login', '/uas/login', '/checkpoint')):
        return CrawlProblem('login_required', 'Portal redirected to authentication/checkpoint')
    text = first_text(driver, ('body',)) or ''
    # Deliberately specific phrases, so ordinary vacancy text does not trigger this.
    lower = text.casefold()
    heading = (first_text(driver, ('h1',)) or '').casefold()
    if heading == 'request blocked':
        return CrawlProblem('access_denied', 'Portal displayed Request Blocked')
    if ('attention required' in driver.title.casefold()
            and 'sorry, you have been blocked' in lower):
        return CrawlProblem('access_denied', 'Portal displayed a Cloudflare access block')
    if heading == 'additional verification required':
        return CrawlProblem('challenge_blocked', 'Portal requires additional verification')
    if include_pending and ('performing security verification' in lower
                            or 'verifies you are not a bot' in lower
                            or driver.title.casefold() == 'just a moment...'):
        return CrawlProblem('challenge_blocked', 'Security verification did not clear within the wait timeout')
    if any(p in lower for p in ('verify you are human', 'unusual traffic from your',
                                'complete the security check', 'verifying you are human',
                                'please solve the captcha to confirm you are human')):
        return CrawlProblem('challenge_blocked', 'Portal displayed a security challenge')
    if lower.strip().startswith(('access denied', '403 forbidden')):
        return CrawlProblem('access_denied', 'Portal denied access')
    if driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"]'):
        if any(e.is_displayed() for e in driver.find_elements(
                By.CSS_SELECTOR, 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"]')):
            return CrawlProblem('challenge_blocked', 'Portal displayed CAPTCHA')
    return None


class PortalAdapter(ABC):
    name: str
    default_headless = True
    date_filter = 'portal_search_filter'
    title_selectors: tuple[str, ...]
    description_selectors: tuple[str, ...]
    company_selectors: tuple[str, ...] = ()
    location_selectors: tuple[str, ...] = ()
    salary_selectors: tuple[str, ...] = ()
    posted_selectors: tuple[str, ...] = ()
    empty_selectors: tuple[str, ...] = ()
    expand_selectors: tuple[str, ...] = ()

    def __init__(self, request: CrawlRequest):
        self.request = request

    @abstractmethod
    def search_url(self, page: int) -> str: ...

    @abstractmethod
    def reference(self, url: str, title: str, source: str, page: int) -> JobReference | None: ...

    @abstractmethod
    def card_links(self, driver): ...

    def collect(self, driver, page: int) -> list[JobReference]:
        found = {}
        for link in self.card_links(driver):
            try:
                observed_url = link.get_attribute('href') or ''
                ref = self.reference_from_link(link, driver.current_url, page)
            except StaleElementReferenceException:
                continue
            if ref:
                ref = replace(ref, observed_url=observed_url or None)
                try:
                    ref = replace(ref, **self.card_metadata(link, ref))
                except StaleElementReferenceException:
                    pass  # Optional metadata must not discard a known card ID and URL.
                found.setdefault(ref.key, ref)
        return list(found.values())

    def reference_from_link(self, link, source: str, page: int) -> JobReference | None:
        return self.reference(link.get_attribute('href') or '', link.text.strip(), source, page)

    def discovery_diagnostics(self, driver) -> dict:
        return {}

    def wait_listing(self, driver, page: int):
        def ready(browser):
            problem = access_problem(browser)
            if problem:
                raise problem
            refs = self.collect(browser, page)
            if refs:
                return refs
            if first_text(browser, self.empty_selectors):
                return 'empty'
            return False
        result = WebDriverWait(driver, self.request.timeout).until(ready)
        return [] if result == 'empty' else result

    def advance(self, driver, page: int, previous_ids: set[str]) -> list[JobReference]:
        driver.get(self.search_url(page))
        return self.wait_listing(driver, page)

    def extra_fields(self, driver, ref: JobReference) -> dict:
        return {}

    def card_metadata(self, link, ref: JobReference) -> dict:
        return {}

    def open_detail(self, driver, ref: JobReference):
        driver.get(ref.url)

    def detail_context(self, driver, ref: JobReference):
        observed = self.reference(driver.current_url, '', ref.discovered_from, ref.search_page)
        return driver if observed is not None and observed.key == ref.key else None

    def read_title(self, root, ref: JobReference):
        return first_text(root, self.title_selectors)

    def read_description(self, driver, root, ref: JobReference):
        return first_text(root, self.description_selectors)

    def extract(self, driver, ref: JobReference) -> CrawledJob:
        def ready(browser):
            problem = access_problem(browser)
            if problem:
                raise problem
            root = self.detail_context(browser, ref)
            if root is None:
                return False
            title = self.read_title(root, ref)
            description = self.read_description(browser, root, ref)
            return (root, title, description) if title and description else False
        WebDriverWait(driver, self.request.timeout).until(ready)
        for selector in self.expand_selectors:
            for button in driver.find_elements(By.CSS_SELECTOR, selector):
                if button.is_displayed() and button.is_enabled():
                    button.click()
                    break
        root, title, description = WebDriverWait(driver, self.request.timeout).until(ready)
        # No guessing of semantic sections: retain complete rendered source text.
        fields = dict(
            title=title, job_url=ref.url,
            company=first_text(root, self.company_selectors),
            location=first_text(root, self.location_selectors),
            description=description, raw_description=description,
            requirements=None, salary=first_text(root, self.salary_selectors),
            application_url=None, portal=self.name, external_id=ref.external_id,
            posted_at_raw=first_text(root, self.posted_selectors),
            observed_url=driver.current_url, keyword=self.request.keyword,
            discovered_from=ref.discovered_from, search_page=ref.search_page,
            crawled_at=datetime.now(timezone.utc).isoformat(),
        )
        fields.update(self.extra_fields(driver, ref))
        return CrawledJob(**fields)


def numeric_id(pattern: str, path: str) -> str | None:
    match = re.search(pattern, path)
    return match.group(1) if match else None
