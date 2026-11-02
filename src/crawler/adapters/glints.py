import json
import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from selenium.webdriver.common.by import By

from ..models import JobReference
from .base import first_text
from .pagination import ObservedPaginationAdapter


class GlintsAdapter(ObservedPaginationAdapter):
    name = 'glints'
    default_headless = False  # Headed guest search verified; headless returned a challenge.
    date_filter = 'latest_sort_only_no_age_filter'
    title_selectors = ('h1[aria-label="Job Title"]', 'h1[class*="JobOverViewTitle"]')
    description_selectors = ('[aria-label="Job Description"] [class*="DescriptionContainer"]',
                             '[aria-label="Job Description"]')
    company_selectors = ('[class*="JobOverViewCompanyName"] a[href*="/companies/"]',
                         '[class*="JobOverViewCompanyName"]')
    salary_selectors = ('[class*="TopFold"] [class*="BasicSalary"]',)
    empty_selectors = ('[data-testid="no-jobs-found"]', '[data-cy="no-jobs-found"]')
    next_selectors = ('a[rel="next"]', 'button[aria-label="Next page"]',
                      'button[aria-label="Next"]', '[data-testid="pagination-next"]')
    pagination_login_selectors = ('#see-more-jobs-login-button',)

    def search_url(self, page=1):
        return 'https://glints.com/id/opportunities/jobs/explore?' + urlencode({
            'keyword': self.request.keyword, 'country': 'ID',
            'locationName': 'All Cities/Provinces', 'lowestLocationLevel': 1, 'sortBy': 'LATEST',
        })

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'glints.com', 'www.glints.com'}:
            return None
        match = re.fullmatch(
            r'/(?:id/)?opportunities/jobs/([^/]+)/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})/?',
            parts.path)
        if not match:
            return None
        slug, job_id = match.groups()
        url = f'https://glints.com/id/opportunities/jobs/{quote(unquote(slug), safe="-")}/{job_id.lower()}'
        return JobReference(self.name, job_id.lower(), url, title, source, page)

    def card_links(self, driver):
        return driver.find_elements(By.CSS_SELECTOR, 'a[aria-label^="Job card title:"][href*="/opportunities/jobs/"]')

    def extra_fields(self, driver, ref):
        # Use the page's own JobPosting for location and the exact posting timestamp.
        # Glints' identifier.value may identify the company, so it is not used as a job ID.
        title = first_text(driver, self.title_selectors)
        matches = []
        for element in driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]'):
            try:
                data = json.loads(element.get_attribute('textContent') or '')
            except (ValueError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                for posting in item.get('@graph', [item]):
                    if (isinstance(posting, dict) and posting.get('@type') == 'JobPosting'
                            and posting.get('title') == title):
                        if posting.get('url'):
                            identity = self.reference(posting['url'], '', '', 1)
                            if identity is None or identity.key != ref.key:
                                continue
                        matches.append(posting)
        if len(matches) != 1:
            return {}
        posting = matches[0]
        result = {}
        date = posting.get('datePosted')
        if isinstance(date, str):
            result['posted_at_raw'] = date
        place = posting.get('jobLocation', {})
        if isinstance(place, list):
            place = place[0] if place else {}
        address = place.get('address', {}) if isinstance(place, dict) else {}
        if isinstance(address, dict):
            parts = [address.get(key) for key in ('addressLocality', 'addressRegion', 'addressCountry')]
            location = ', '.join(dict.fromkeys(part for part in parts if isinstance(part, str) and part))
            if location:
                result['location'] = location
        return result
