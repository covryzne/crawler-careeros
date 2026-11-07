import json
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

    def listing_exhausted(self, driver, refs):
        if super().listing_exhausted(driver, refs):
            return True
        # Public rendered Next.js state contains the search's advertised total.
        # Bind it to this keyword and the actual cards, not unrelated queries.
        for element in driver.find_elements(By.CSS_SELECTOR, 'script#__NEXT_DATA__'):
            try:
                data = json.loads(element.get_attribute('textContent') or '')
                queries = data['props']['pageProps']['dehydratedState']['queries']
                for query in queries:
                    key = query.get('queryKey', [])
                    if (not isinstance(key, list) or len(key) != 2
                            or key[0] != '/v1/explore-job/job' or not isinstance(key[1], dict)
                            or key[1].get('search') != self.request.keyword):
                        continue
                    pages = query['state']['data']['pages']
                    if not pages:
                        continue
                    total = pages[-1].get('totalDocs')
                    docs = [doc for page in pages for doc in page.get('docs', [])]
                    expected = {f"{doc['slug']}~{doc['company']['slug']}" for doc in docs}
                    actual = {ref.external_id for ref in refs}
                    # Recommended cards can follow the search results. Count only
                    # identities belonging to the matching search metadata.
                    if type(total) is int and total >= 0 and len(expected) == total and expected <= actual:
                        return True
            except (ValueError, TypeError, KeyError, AttributeError):
                continue  # Missing/stale metadata must not turn an uncertain listing into success.
        return False

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
