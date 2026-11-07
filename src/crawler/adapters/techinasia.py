import re
from urllib.parse import urlencode, urlsplit

from selenium.webdriver.common.by import By

from ..models import JobReference
from .pagination import ObservedPaginationAdapter
from .rendered import heading_section, join_sections, matching_posting, posting_metadata


class TechInAsiaAdapter(ObservedPaginationAdapter):
    name = 'techinasia'
    date_filter = 'portal_default_order_no_age_filter'
    title_selectors = ('.header-content h1',)
    description_selectors = ()
    company_selectors = ('.header-content a[href^="/companies/"]',)
    location_selectors = ('.header-content > div:has(> a[href^="/companies/"]) + div',)
    salary_selectors = ('.header-content .compensation',)
    posted_selectors = ('.header-content .dates__created',)
    next_selectors = ('a[rel="next"]', 'button[aria-label="Next page"]')
    next_xpath_selectors = ('//button[normalize-space(.)="Load more"]',
                            '//button[normalize-space(.)="Load more jobs"]')

    def search_url(self, page=1):
        return 'https://www.techinasia.com/jobs/search?' + urlencode({
            'query': self.request.keyword, 'country_name[]': 'Indonesia'})

    def listing_exhausted(self, driver, refs):
        if super().listing_exhausted(driver, refs):
            return True
        # Observed public result counter, scoped away from vacancy descriptions.
        for element in driver.find_elements(By.CSS_SELECTOR, '.meta-item'):
            if not element.is_displayed():
                continue
            match = re.fullmatch(r'Showing\s+([\d,]+)\s+results?', element.text.strip(), re.I)
            if match and len({ref.key for ref in refs}) == int(match[1].replace(',', '')):
                return True
        return False

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'www.techinasia.com', 'techinasia.com'}:
            return None
        match = re.fullmatch(r'/jobs/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})/?', parts.path)
        if not match:
            return None
        job_id = match[1].lower()
        return JobReference(self.name, job_id, f'https://www.techinasia.com/jobs/{job_id}', title, source, page)

    def card_links(self, driver):
        return driver.find_elements(By.CSS_SELECTOR, 'h3.job-title a[href*="/jobs/"]')

    def read_description(self, driver, root, ref):
        return join_sections(heading_section(root, label) for label in (
            'Job description & requirements', 'Required skills'))

    def extra_fields(self, driver, ref):
        return posting_metadata(matching_posting(self, driver, ref))
