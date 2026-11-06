"""Bounded, opt-in interaction with an exposed Cloudflare verification checkbox."""
from urllib.parse import urlsplit
from time import monotonic

from selenium.common.exceptions import (
    ElementClickInterceptedException, ElementNotInteractableException,
    DetachedShadowRootException, NoSuchFrameException, NoSuchShadowRootException,
    StaleElementReferenceException, TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .adapters.base import CrawlProblem, access_problem


CLICK_RETRY_INTERVAL = 5.0


def elements_in_shadow_roots(driver, selector):
    # element.shadowRoot in JavaScript returns null for closed roots. Chrome's
    # native WebDriver shadow_root command can expose those same roots.
    roots = [driver]
    visited_hosts = 0
    for root in roots:
        try:
            yield from root.find_elements(By.CSS_SELECTOR, selector)
            for host in root.find_elements(By.CSS_SELECTOR, '*'):
                if visited_hosts >= 1000 or len(roots) >= 100:
                    return
                visited_hosts += 1
                try:
                    roots.append(host.shadow_root)
                except (NoSuchShadowRootException, StaleElementReferenceException):
                    continue
        except (DetachedShadowRootException, StaleElementReferenceException):
            continue


def click_verification_checkbox(driver):
    """Click an exposed unchecked control only inside a Cloudflare challenge frame.

    No coordinate guesses, forced JS clicks, or changes to browser identity.
    Only roots exposed by WebDriver are reachable; no usable control may exist.
    """
    try:
        for frame in elements_in_shadow_roots(driver, 'iframe'):
            try:
                source = urlsplit(frame.get_attribute('src') or '')
                if (source.scheme != 'https' or source.hostname != 'challenges.cloudflare.com'
                        or not source.path.startswith('/cdn-cgi/challenge-platform/')
                        or not frame.is_displayed()):
                    continue
                driver.switch_to.frame(frame)
                for checkbox in elements_in_shadow_roots(driver, 'input[type="checkbox"], [role="checkbox"]'):
                    if (checkbox.is_enabled()
                            and not checkbox.is_selected()
                            and checkbox.get_attribute('aria-checked') != 'true'):
                        # Turnstile may hide the actual input (opacity:0) and
                        # expose its associated label as the interactive target.
                        targets = ([checkbox] if checkbox.is_displayed() else
                                   driver.execute_script('return Array.from(arguments[0].labels || [])', checkbox))
                        for target in targets:
                            if target.is_displayed() and target.is_enabled():
                                target.click()
                                return True
            except (StaleElementReferenceException, NoSuchFrameException,
                    ElementClickInterceptedException, ElementNotInteractableException):
                # A widget may still be rendering. Poll again within the deadline.
                continue
            finally:
                driver.switch_to.default_content()
        return False
    finally:
        driver.switch_to.default_content()


def attempt_verification(driver, timeout, portal, attempts, *, max_clicks=1):
    event = {'state': 'waiting', 'checkbox_clicked': False, 'click_count': 0,
             'max_clicks': max_clicks}
    attempts.append(event)
    next_click_at = 0.0
    print(f'[{portal}] verification detected; trying an available checkbox '
          f'(timeout={timeout}s, max_clicks={max_clicks})', flush=True)

    def ready(browser):
        nonlocal next_click_at
        problem = access_problem(browser, include_pending=True)
        if problem is None:
            return True
        if problem.status != 'challenge_blocked':
            raise problem
        if event['click_count'] < max_clicks and monotonic() >= next_click_at:
            if click_verification_checkbox(browser):
                event['checkbox_clicked'] = True
                event['click_count'] += 1
                next_click_at = monotonic() + CLICK_RETRY_INTERVAL
                print(f'[{portal}] verification checkbox clicked '
                      f'({event["click_count"]}/{max_clicks}); waiting for page', flush=True)
        return False

    try:
        WebDriverWait(driver, timeout, poll_frequency=0.5).until(ready)
    except TimeoutException as exc:
        event['state'] = 'timeout'
        reason = (f'checkbox clicked {event["click_count"]}/{max_clicks} times but verification did not clear' if event['checkbox_clicked']
                  else 'no accessible verification checkbox; verification did not clear')
        print(f'[{portal}] verification failed: {reason}', flush=True)
        raise CrawlProblem('challenge_blocked', reason) from exc
    except Exception:
        event['state'] = 'failed'
        raise
    event['state'] = 'cleared'
    print(f'[{portal}] verification page cleared; checking portal content', flush=True)
