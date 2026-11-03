from urllib.parse import urlsplit

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .base import CrawlProblem, PortalAdapter, access_problem, first_text


class ObservedPaginationAdapter(PortalAdapter):
    """Follow an actual next control, rather than guessing offsets or page size."""
    next_selectors: tuple[str, ...] = ()
    next_xpath_selectors: tuple[str, ...] = ()
    pagination_login_selectors: tuple[str, ...] = ()

    def next_controls(self, driver):
        for selector in self.next_selectors:
            yield from driver.find_elements(By.CSS_SELECTOR, selector)
        for selector in self.next_xpath_selectors:
            yield from driver.find_elements(By.XPATH, selector)

    def advance(self, driver, page, previous_ids):
        if page == 1:
            return super().advance(driver, page, previous_ids)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight)')

        def next_control(browser):
            problem = access_problem(browser)
            if problem:
                raise problem
            # An infinite listing may have loaded more cards on scroll.
            refs = self.collect(browser, page)
            if any(ref.key not in previous_ids for ref in refs):
                return ('loaded', refs)
            for control in self.next_controls(browser):
                if not control.is_displayed():
                    continue
                if (not control.is_enabled() or control.get_attribute('aria-disabled') == 'true'
                        or control.get_attribute('disabled') is not None):
                    return ('end', None)
                return ('next', control)
            if first_text(browser, self.pagination_login_selectors):
                # Public detail URLs already collected may still be visited.
                raise CrawlProblem('pagination_login_required', 'More listing results require login; guest limit reached')
            if first_text(browser, self.empty_selectors):
                return ('end', None)
            return False

        try:
            action, value = WebDriverWait(driver, self.request.timeout).until(next_control)
        except TimeoutException as exc:
            raise CrawlProblem('pagination_unavailable', 'No next-page control or explicit end indicator found') from exc
        if action == 'loaded':
            return value
        if action == 'end':
            return []
        href = value.get_attribute('href')
        if href:
            target, seed = urlsplit(href), urlsplit(self.search_url(1))
            if target.scheme != 'https' or target.hostname != seed.hostname or target.path != seed.path:
                raise CrawlProblem('pagination_invalid', 'Next-page link left the portal search route')
            driver.get(href)
        else:
            value.click()

        def ready(browser):
            problem = access_problem(browser)
            if problem:
                raise problem
            refs = self.collect(browser, page)
            if any(ref.key not in previous_ids for ref in refs):
                return ('ready', refs)
            if first_text(browser, self.empty_selectors):
                return ('ready', [])
            return False
        return WebDriverWait(driver, self.request.timeout).until(ready)[1]
