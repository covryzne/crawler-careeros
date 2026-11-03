import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from selenium.webdriver.common.by import By

from ..models import JobReference
from .base import first_text
from .pagination import ObservedPaginationAdapter
from .rendered import heading_section, join_sections, matching_posting, posting_metadata


class DeallsAdapter(ObservedPaginationAdapter):
    name = 'dealls'
    default_headless = False  # Public listing/detail worked headed; headless was blocked.
    date_filter = 'portal_default_order_no_age_filter'
    title_selectors = ('h1',)
    description_selectors = ('[class*="SectionWrapper_job_description"]',)
    company_selectors = ('a[href*="/karir/"] h2',)
    next_xpath_selectors = ('//button[normalize-space(.)="See More"]',)

    def search_url(self, page=1):
        return 'https://dealls.com/en?' + urlencode({'searchJob': self.request.keyword})

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'dealls.com', 'www.dealls.com'}:
            return None
        match = re.fullmatch(r'/(?:en/)?loker/([a-zA-Z0-9%_-]+~[a-zA-Z0-9%_-]+)/?', parts.path)
        if not match:
            return None
        # Listing exposes a route slug, not the native ID present only on detail JSON-LD.
        slug = unquote(match[1])
        if not re.fullmatch(r'[\w-]+~[\w-]+', slug):
            return None
        return JobReference(self.name, slug, 'https://dealls.com/en/loker/' + quote(slug, safe='-~'),
                            title, source, page)

    def card_links(self, driver):
        return driver.find_elements(By.CSS_SELECTOR, 'a[data-index][href*="/loker/"]')

    def reference_from_link(self, link, source, page):
        title = first_text(link, ('h2',))
        return self.reference(link.get_attribute('href') or '', title or '', source, page)

    def read_description(self, driver, root, ref):
        return join_sections(heading_section(root, label) for label in ('Job Description', 'Requirements', 'Benefits'))

    def extra_fields(self, driver, ref):
        fields = posting_metadata(matching_posting(self, driver, ref))
        requirements = heading_section(driver, 'Requirements')
        if requirements:
            fields['requirements'] = requirements
        # Read visible header salary; "Actively hiring" is not a posting date.
        for element in driver.find_elements(By.CSS_SELECTOR, 'h1'):
            header = element.find_element(By.XPATH, '../..')
            for row in header.find_elements(By.CSS_SELECTOR, 'li'):
                if row.is_displayed() and row.text.strip().startswith('Rp'):
                    fields['salary'] = row.text.strip()
        return fields
