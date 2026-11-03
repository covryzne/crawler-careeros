import re
import time
from urllib.parse import quote, unquote, urlencode, urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from ..models import JobReference
from .base import access_problem, first_text
from .pagination import ObservedPaginationAdapter
from .rendered import join_sections


class KalibrrAdapter(ObservedPaginationAdapter):
    name = 'kalibrr'
    date_filter = 'latest_sort_only_no_age_filter'
    title_selectors = ('h1[itemprop="title"]',)
    description_selectors = ('div[itemprop="description"]',)
    company_selectors = ('h1[itemprop="title"] ~ span a h2',)
    location_selectors = ('h1[itemprop="title"] ~ ul span[itemtype$="PostalAddress"]',)
    next_xpath_selectors = ('//button[normalize-space(.)="Load more jobs"]',)
    listing_settle_seconds = 2

    def advance(self, driver, page, previous_ids):
        refs = super().advance(driver, page, previous_ids)
        if not refs:
            return refs
        # Hydration initially exposes unrelated landing-page cards, then replaces
        # them with keyword results. Do not checkpoint that transient card set.
        last_ids = None
        changed_at = time.monotonic()

        def settled(browser):
            nonlocal last_ids, changed_at
            problem = access_problem(browser)
            if problem:
                raise problem
            current = self.collect(browser, page)
            ids = tuple(ref.key for ref in current)
            if ids != last_ids:
                last_ids, changed_at = ids, time.monotonic()
            return current if current and time.monotonic() - changed_at >= self.listing_settle_seconds else False

        return WebDriverWait(driver, self.request.timeout, poll_frequency=0.25).until(settled)

    def search_url(self, page=1):
        keyword = quote(re.sub(r'\s+', '-', self.request.keyword.strip()), safe='')
        return f'https://www.kalibrr.com/id-ID/home/te/{keyword}?' + urlencode({'sort': 'Freshness'})

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'www.kalibrr.com', 'kalibrr.com'}:
            return None
        match = re.fullmatch(r'/(?:[a-z]{2}-[A-Z]{2}/)?c/([^/]+)/jobs/(\d+)/([^/]+)/?', parts.path)
        if not match:
            return None
        company, job_id, slug = match.groups()
        if not all(re.fullmatch(r'[\w-]+', unquote(v)) for v in (company, slug)):
            return None
        canonical = f'https://www.kalibrr.com/id-ID/c/{quote(unquote(company), safe="-")}/jobs/{job_id}/{quote(unquote(slug), safe="-")}'
        return JobReference(self.name, job_id, canonical, title, source, page)

    def card_links(self, driver):
        return driver.find_elements(By.CSS_SELECTOR, 'h2 a[itemprop="name"][href*="/jobs/"]')

    def read_description(self, driver, root, ref):
        return join_sections(first_text(root, (selector,)) for selector in (
            'div[itemprop="description"]', 'div[itemprop="qualifications"]', 'div[itemprop="jobBenefits"]'))

    def extra_fields(self, driver, ref):
        fields = {}
        requirements = first_text(driver, ('div[itemprop="qualifications"]',))
        if requirements:
            fields['requirements'] = requirements
        # Portal's own hidden posting timestamp; never use recruiter activity as job age.
        elements = driver.find_elements(By.CSS_SELECTOR, '[itemprop="datePosted"]')
        if len(elements) == 1:
            date = (elements[0].get_attribute('content') or elements[0].get_attribute('textContent') or '').strip()
            if date:
                fields['posted_at_raw'] = date
        return fields
