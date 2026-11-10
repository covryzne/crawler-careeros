import re
from urllib.parse import parse_qs, urlencode, urlsplit

from selenium.webdriver.common.by import By

from ..models import JobReference
from .base import PortalAdapter, numeric_id


class JobStreetAdapter(PortalAdapter):
    name = 'jobstreet'
    default_headless = False
    title_selectors = ('h1[data-automation="job-detail-title"]', '[data-automation="job-detail-title"]')
    company_selectors = ('[data-automation="advertiser-name"]',)
    location_selectors = ('[data-automation="job-detail-location"]',)
    description_selectors = ('[data-automation="jobAdDetails"]', '[data-automation="job-ad-details"]')
    salary_selectors = ('[data-automation="job-detail-salary"]',)
    posted_selectors = ('[data-automation="job-detail-date"]',)
    empty_selectors = ('[data-automation="searchZeroResults"]', '[data-automation="no-results"]')
    end_selectors = ('[data-automation="page-next"][aria-disabled="true"]',
                     'button[data-automation="page-next"]:disabled')

    def search_url(self, page=1):
        slug = re.sub(r'[^\w]+', '-', self.request.keyword.casefold(), flags=re.UNICODE).strip('-')
        if not slug:
            raise ValueError('JobStreet keyword must contain letters or digits')
        from urllib.parse import quote
        query = {'daterange': self.request.days}
        if page > 1:
            query['page'] = page
        return f'https://id.jobstreet.com/id/{quote(slug)}-jobs?' + urlencode(query)

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'id.jobstreet.com':
            return None
        job_id = numeric_id(r'/(?:id/)?job/(\d+)/?$', parts.path)
        if job_id is None:
            candidate = parse_qs(parts.query).get('jobId', [''])[0]
            job_id = candidate if candidate.isdigit() else None
        if not job_id:
            return None
        return JobReference(self.name, job_id, f'https://id.jobstreet.com/id/job/{job_id}',
                            title, source, page)

    def card_links(self, driver):
        return driver.find_elements(By.CSS_SELECTOR,
            'article a[data-automation="jobTitle"], '
            '[data-testid="job-card"] a[data-automation="jobTitle"]')
