from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException

from src.crawler import verification
from src.crawler.adapters import ADAPTERS
from src.crawler.adapters.base import CrawlProblem
from src.crawler.cli import main
from src.crawler.models import CrawlRequest


def challenge():
    return CrawlProblem('challenge_blocked', 'Additional Verification Required')


@pytest.mark.parametrize('portal', ['jobstreet', 'indeed'])
def test_auto_verification_clears_before_listing_collection(monkeypatch, portal):
    adapter = ADAPTERS[portal](CrawlRequest(keyword='AI', portals=(portal,), auto_verify=True))
    states = iter([challenge(), challenge(), None])
    monkeypatch.setattr('src.crawler.adapters.base.access_problem', lambda *a, **kw: next(states))
    monkeypatch.setattr(verification, 'access_problem', lambda *a, **kw: next(states))
    click = Mock(return_value=True)
    monkeypatch.setattr(verification, 'click_verification_checkbox', click)
    ref = object()
    adapter.collect = Mock(return_value=[ref])
    assert adapter.wait_listing(object(), 1) == [ref]
    click.assert_called_once()
    assert adapter.verification_attempts == [{'state': 'cleared', 'checkbox_clicked': True,
                                             'click_count': 1, 'max_clicks': 1}]


@pytest.mark.parametrize('clicked', [False, True])
def test_unsolved_verification_times_out_without_repeated_clicks(monkeypatch, clicked):
    monkeypatch.setattr(verification, 'access_problem', lambda *a, **kw: challenge())
    click = Mock(return_value=clicked)
    monkeypatch.setattr(verification, 'click_verification_checkbox', click)
    attempts = []
    with pytest.raises(CrawlProblem) as error:
        verification.attempt_verification(object(), 0.01, 'indeed', attempts)
    assert error.value.status == 'challenge_blocked'
    assert attempts == [{'state': 'timeout', 'checkbox_clicked': clicked,
                         'click_count': int(clicked), 'max_clicks': 1}]
    if clicked:
        click.assert_called_once()


def test_access_denial_is_not_treated_as_checkbox_challenge(monkeypatch):
    monkeypatch.setattr(verification, 'access_problem',
                        lambda *a, **kw: CrawlProblem('access_denied', 'Request Blocked'))
    click = Mock()
    monkeypatch.setattr(verification, 'click_verification_checkbox', click)
    attempts = []
    with pytest.raises(CrawlProblem) as error:
        verification.attempt_verification(object(), 0.01, 'indeed', attempts)
    assert error.value.status == 'access_denied'
    click.assert_not_called()
    assert attempts[0]['state'] == 'failed'


@pytest.mark.parametrize('portal,enabled', [('jobstreet', False), ('indeed', False), ('glints', True)])
def test_verification_is_opt_in_and_scoped(monkeypatch, portal, enabled):
    adapter = ADAPTERS[portal](CrawlRequest(keyword='AI', portals=(portal,), auto_verify=enabled))
    problem = challenge()
    monkeypatch.setattr('src.crawler.adapters.base.access_problem', lambda *a, **kw: problem)
    attempt = Mock()
    monkeypatch.setattr(verification, 'attempt_verification', attempt)
    assert adapter.check_access(object()) is problem
    attempt.assert_not_called()


@pytest.mark.parametrize('frame_url,should_click', [
    ('https://challenges.cloudflare.com/cdn-cgi/challenge-platform/widget', True),
    ('https://challenges.cloudflare.com.evil.test/cdn-cgi/challenge-platform/widget', False),
    ('https://id.indeed.com/advertisement', False),
])
def test_only_clicks_inside_cloudflare_frame_and_restores_context(monkeypatch, frame_url, should_click):
    frame, checkbox = Mock(), Mock()
    frame.get_attribute.return_value = frame_url
    frame.is_displayed.return_value = True
    checkbox.is_displayed.return_value = checkbox.is_enabled.return_value = True
    checkbox.is_selected.return_value = False
    checkbox.get_attribute.return_value = 'false'
    driver = SimpleNamespace(switch_to=Mock())
    monkeypatch.setattr(verification, 'elements_in_shadow_roots',
                        lambda driver, selector: [frame] if selector == 'iframe' else [checkbox])
    assert verification.click_verification_checkbox(driver) is should_click
    assert checkbox.click.call_count == int(should_click)
    driver.switch_to.default_content.assert_called()


def test_intercepted_checkbox_click_restores_frame(monkeypatch):
    frame, checkbox = Mock(), Mock()
    frame.get_attribute.return_value = 'https://challenges.cloudflare.com/cdn-cgi/challenge-platform/widget'
    checkbox.is_selected.return_value = False
    checkbox.get_attribute.return_value = 'false'
    checkbox.click.side_effect = ElementClickInterceptedException()
    driver = SimpleNamespace(switch_to=Mock())
    monkeypatch.setattr(verification, 'elements_in_shadow_roots',
                        lambda driver, selector: [frame] if selector == 'iframe' else [checkbox])
    assert verification.click_verification_checkbox(driver) is False
    driver.switch_to.default_content.assert_called()


def test_cli_verification_options_reach_runner(monkeypatch, tmp_path):
    run = Mock(return_value={'state': 'completed'})
    monkeypatch.setattr('src.crawler.runner.run', run)
    main(['--mode', 'selenium', '--portals', 'indeed', '--auto-verify',
          '--verification-timeout', '45', '--verification-max-clicks', '5',
          '--output-dir', str(tmp_path)])
    request = run.call_args.args[0]
    assert request.auto_verify is True
    assert request.verification_timeout == 45
    assert request.verification_max_clicks == 5


@pytest.mark.parametrize('flags', [['--auto-verify'], ['--verification-max-clicks', '5']])
def test_browser_use_rejects_verification_options(flags):
    with pytest.raises(SystemExit) as error:
        main(flags)
    assert error.value.code == 2


@pytest.mark.parametrize('timeout', [0, -1, 301, float('nan'), float('inf')])
def test_verification_timeout_is_bounded(timeout):
    with pytest.raises(ValueError):
        CrawlRequest(keyword='AI', portals=('indeed',), verification_timeout=timeout)


@pytest.mark.parametrize('limit', [0, -1, 21, 1.5, True, '5'])
def test_verification_click_limit_is_bounded_integer(limit):
    with pytest.raises(ValueError):
        CrawlRequest(keyword='AI', portals=('indeed',), verification_max_clicks=limit)


@pytest.mark.parametrize('clear_after,expected_clicks,state', [(3, 3, 'cleared'), (None, 5, 'timeout')])
def test_retry_clicks_respect_spacing_cap_and_stop_after_clear(monkeypatch, clear_after, expected_clicks, state):
    clock = [0]
    click = Mock(return_value=True)
    monkeypatch.setattr(verification, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(verification, 'click_verification_checkbox', click)
    monkeypatch.setattr(verification, 'access_problem',
                        lambda *a, **kw: None if clear_after and click.call_count >= clear_after else challenge())

    class Wait:
        def __init__(self, driver, timeout, **kwargs):
            self.driver = driver
            assert timeout == 60  # One shared deadline, not per-click waits.

        def until(self, condition):
            for tick in range(31):
                clock[0] = tick
                if condition(self.driver):
                    return True
                # Even though polled every second, successful clicks stay >=5s apart.
                assert click.call_count <= min(tick // 5 + 1, 5)
            raise TimeoutException()

    monkeypatch.setattr(verification, 'WebDriverWait', Wait)
    attempts = []
    if state == 'timeout':
        with pytest.raises(CrawlProblem) as error:
            verification.attempt_verification(object(), 60, 'indeed', attempts, max_clicks=5)
        assert error.value.status == 'challenge_blocked'
    else:
        verification.attempt_verification(object(), 60, 'indeed', attempts, max_clicks=5)
    assert click.call_count == expected_clicks
    assert attempts[0]['state'] == state
    assert attempts[0]['click_count'] == expected_clicks
    assert attempts[0]['max_clicks'] == 5


@pytest.mark.parametrize('selected,aria_checked', [(True, 'false'), (False, 'true')])
def test_retry_never_toggles_checked_checkbox(monkeypatch, selected, aria_checked):
    frame, checkbox = Mock(), Mock()
    frame.get_attribute.return_value = 'https://challenges.cloudflare.com/cdn-cgi/challenge-platform/widget'
    checkbox.is_selected.return_value = selected
    checkbox.get_attribute.return_value = aria_checked
    driver = SimpleNamespace(switch_to=Mock())
    monkeypatch.setattr(verification, 'elements_in_shadow_roots',
                        lambda driver, selector: [frame] if selector == 'iframe' else [checkbox])
    assert verification.click_verification_checkbox(driver) is False
    checkbox.click.assert_not_called()
