from urllib.parse import parse_qs, urlencode, urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from ..models import JobReference
from .base import PortalAdapter, access_problem, first_text, numeric_id


class LinkedInAdapter(PortalAdapter):
    name = 'linkedin'
    title_selectors = ('h1.top-card-layout__title', 'h1.topcard__title')
    company_selectors = ('a.topcard__org-name-link', '.topcard__flavor')
    location_selectors = ('.topcard__flavor--bullet',)
    description_selectors = ('.show-more-less-html__markup', '.description__text')
    salary_selectors = ('.salary.compensation__salary', '.compensation__salary')
    posted_selectors = ('.posted-time-ago__text', '.posted-time-ago__text--new')
    empty_selectors = ('.jobs-search-no-results-banner', '.no-results')
    expand_selectors = ('button.show-more-less-html__button--more',)

    def search_url(self, page=1):
        # Guest search loads additional cards through scrolling / Show more.
        # pageNum and position in a selected-card URL are not pagination controls here.
        return 'https://id.linkedin.com/jobs/search?' + urlencode({
            'keywords': self.request.keyword, 'location': self.request.location,
            'geoId': self.request.linkedin_geo_id, 'f_TPR': f'r{self.request.days * 86400}',
        })

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'id.linkedin.com', 'www.linkedin.com', 'linkedin.com'}:
            return None
        job_id = numeric_id(r'/jobs/view/(?:[^/]*-)?(\d+)/?$', parts.path)
        if job_id is None and parts.path.rstrip('/') == '/jobs/search':
            candidate = parse_qs(parts.query).get('currentJobId', [''])[0]
            job_id = candidate if candidate.isdigit() else None
        if not job_id:
            return None
        return JobReference(self.name, job_id, f'https://www.linkedin.com/jobs/view/{job_id}/',
                            title, source, page)

    def card_links(self, driver):
        return driver.find_elements(By.CSS_SELECTOR,
            '.jobs-search__results-list a[href*="/jobs/view/"], '
            'a.base-card__full-link[href*="/jobs/view/"]')

    def reference_from_link(self, link, source, page):
        # Guest cards often use an empty overlay anchor; the visible title is a sibling.
        title = link.text.strip()
        cards = link.find_elements(By.XPATH,
            './ancestor::*[self::li or contains(concat(" ", normalize-space(@class), " "), " base-card ")][1]')
        if cards:
            title = first_text(cards[0], ('.base-search-card__title', '.job-search-card__title', 'h3', 'h2')) or title
        if not title:
            for element in link.find_elements(By.CSS_SELECTOR, '.sr-only'):
                title = (element.get_attribute('textContent') or '').strip()
                if title:
                    break
        return self.reference(link.get_attribute('href') or '', title, source, page)

    def advance(self, driver, page, previous_ids):
        if page == 1:
            return super().advance(driver, page, previous_ids)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight)')
        clicked = False

        def changed(browser):
            nonlocal clicked
            problem = access_problem(browser)
            if problem:
                raise problem
            refs = self.collect(browser, page)
            if any(ref.key not in previous_ids for ref in refs):
                return refs
            if any(e.is_displayed() for e in browser.find_elements(
                    By.CSS_SELECTOR, '.inline-notification--no-more-results')):
                return 'end'
            if not clicked:
                for button in browser.find_elements(By.CSS_SELECTOR, 'button.infinite-scroller__show-more-button'):
                    if button.is_displayed() and button.is_enabled():
                        button.click()
                        clicked = True
                        break
            return False
        result = WebDriverWait(driver, self.request.timeout).until(changed)
        return [] if result == 'end' else result
