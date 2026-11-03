import json
import sys
import types
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.common.exceptions import TimeoutException

from src.crawler.adapters.base import CrawlProblem, access_problem
from src.crawler.adapters.jobstreet import JobStreetAdapter
from src.crawler.adapters.linkedin import LinkedInAdapter
from src.crawler.adapters.glints import GlintsAdapter
from src.crawler.adapters.indeed import IndeedAdapter
from src.crawler.cli import main
from src.crawler.models import CrawlRequest, CrawledJob, JobReference
from src.crawler.runner import run


def request(**kwargs):
    return CrawlRequest(keyword='AI Engineer', portals=('jobstreet',), delay=0, **kwargs)


def test_search_filters_and_keyword_encoding():
    linkedin = LinkedInAdapter(request())
    params = parse_qs(urlsplit(linkedin.search_url(1)).query)
    assert params['keywords'] == ['AI Engineer']
    assert params['f_TPR'] == ['r604800']
    assert params['geoId'] == ['102478259']
    street = JobStreetAdapter(request())
    assert street.search_url(1) == 'https://id.jobstreet.com/id/ai-engineer-jobs?daterange=7'
    assert street.search_url(3).endswith('daterange=7&page=3')


@pytest.mark.parametrize('adapter,urls,key', [
    (JobStreetAdapter, ['https://id.jobstreet.com/id/ai-engineer-jobs?jobId=95550334&page=1',
                       'https://id.jobstreet.com/id/data-analyst-jobs?jobId=95550334&page=3',
                       'https://id.jobstreet.com/job/95550334?tracking=123'], 'jobstreet:95550334'),
    (LinkedInAdapter, ['https://id.linkedin.com/jobs/search?currentJobId=4484811461&position=2',
                      'https://www.linkedin.com/jobs/view/ai-engineer-at-example-4484811461/',
                      'https://www.linkedin.com/jobs/view/4484811461/?position=3'], 'linkedin:4484811461'),
])
def test_identity_is_independent_of_search_and_tracking(adapter, urls, key):
    refs = [adapter(request()).reference(url, 'title', 'source', 1) for url in urls]
    assert {ref.key for ref in refs} == {key}
    assert len({ref.url for ref in refs}) == 1


@pytest.mark.parametrize('url', [
    'https://id.jobstreet.com.evil.test/job/123', 'http://id.jobstreet.com/job/123',
    'https://evil.test/?jobId=123', 'https://id.jobstreet.com/job/not-an-id',
])
def test_jobstreet_ignores_foreign_or_invalid_links(url):
    assert JobStreetAdapter(request()).reference(url, '', '', 1) is None


@pytest.mark.parametrize('kwargs', [
    {'days': 0}, {'max_pages': 0}, {'max_jobs': 201}, {'timeout': float('nan')},
    {'location': 'Jakarta'}, {'linkedin_geo_id': 'bad'},
])
def test_invalid_request_rejected(kwargs):
    with pytest.raises(ValueError):
        request(**kwargs)


class Driver:
    current_url = 'https://id.jobstreet.com/id/ai-engineer-jobs'
    closed = False
    title = ''

    def find_elements(self, *args):
        return []

    def get(self, url):
        self.current_url = url

    def quit(self):
        self.closed = True


class Adapter:
    fail_page = None
    blocked_detail = False
    detail_failure = False

    def __init__(self, request):
        self.request = request

    def advance(self, driver, page, seen):
        if self.fail_page == page:
            raise TimeoutException('page timeout')
        ids = ('1', '2') if page == 1 else ('2', '3')
        return [JobReference('jobstreet', job_id, f'https://id.jobstreet.com/id/job/{job_id}',
                             f'Role {job_id}', driver.current_url, page) for job_id in ids]

    def extract(self, driver, ref):
        if self.blocked_detail:
            raise CrawlProblem('challenge_blocked', 'challenge')
        if self.detail_failure and ref.external_id == '1':
            raise TimeoutException('detail timeout')
        return CrawledJob(title=ref.title, job_url=ref.url, portal=ref.portal,
                          external_id=ref.external_id, raw_description='Original vacancy text',
                          observed_url=driver.current_url, keyword=self.request.keyword,
                          discovered_from=ref.discovered_from, search_page=ref.search_page,
                          crawled_at='2026-11-02T00:00:00+00:00')

    def open_detail(self, driver, ref):
        driver.get(ref.url)


def setup_runner(monkeypatch, adapter=Adapter):
    monkeypatch.setitem(sys.modules['src.crawler.runner'].ADAPTERS, 'jobstreet', adapter)
    driver = Driver()
    return driver


def test_run_deduplicates_ids_and_writes_checkpoints(tmp_path, monkeypatch):
    driver = setup_runner(monkeypatch)
    result = run(request(), tmp_path, lambda _: driver)
    assert result['state'] == 'completed'
    assert [job['external_id'] for job in result['jobs']] == ['1', '2', '3']
    assert driver.closed
    saved = json.loads(next(tmp_path.glob('*/jobs.json')).read_text())
    assert len(saved['jobs']) == 3


def test_pagination_failure_preserves_discovered_jobs(tmp_path, monkeypatch):
    class FailingAdapter(Adapter):
        fail_page = 2
    driver = setup_runner(monkeypatch, FailingAdapter)
    result = run(request(), tmp_path, lambda _: driver)
    assert result['state'] == 'completed_with_errors'
    assert len(result['jobs']) == 2
    assert result['sources'][0]['state'] == 'partial'
    assert result['sources'][0]['listing_error']['status'] == 'listing_timeout'
    assert driver.closed


def test_detail_failure_continues_to_next_id(tmp_path, monkeypatch):
    class FailingAdapter(Adapter):
        detail_failure = True
    driver = setup_runner(monkeypatch, FailingAdapter)
    result = run(request(), tmp_path, lambda _: driver)
    assert [job['external_id'] for job in result['jobs']] == ['2', '3']
    assert result['sources'][0]['details'][0]['state'] == 'failed'
    assert driver.closed


def test_security_challenge_stops_portal(tmp_path, monkeypatch):
    class BlockedAdapter(Adapter):
        blocked_detail = True
    driver = setup_runner(monkeypatch, BlockedAdapter)
    result = run(request(), tmp_path, lambda _: driver)
    assert result['state'] == 'completed_with_errors'
    assert len(result['sources'][0]['details']) == 1
    assert result['sources'][0]['stop_reason'] == 'challenge_blocked'
    assert driver.closed


def test_browser_start_failure_is_saved(tmp_path):
    def fail(_):
        raise RuntimeError('browser cannot start')
    result = run(request(), tmp_path, fail)
    assert result['sources'][0]['state'] == 'failed'
    assert result['errors'][0]['phase'] == 'listing'
    assert next(tmp_path.glob('*/manifest.json')).exists()


def test_browser_use_default_route_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('SEARCH_KEYWORD', 'old keyword')
    calls = []
    module = types.ModuleType('src.browser_lab.orchestrator')
    module.main = lambda **kwargs: calls.append(kwargs)
    monkeypatch.setitem(sys.modules, 'src.browser_lab.orchestrator', module)
    main(['--keyword', 'Data Analyst', '--output-dir', str(tmp_path)])
    assert calls == [{'output_dir': tmp_path}]
    assert sys.modules['os'].environ['SEARCH_KEYWORD'] == 'Data Analyst'


def test_selenium_route_does_not_require_llm_key(monkeypatch, tmp_path):
    monkeypatch.setattr('src.crawler.cli.load_dotenv', lambda: None)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
    called = []
    monkeypatch.setattr('src.crawler.runner.run',
                        lambda req, path: called.append(req) or {'state': 'completed'})
    main(['--mode', 'selenium', '--keyword', 'Data Analyst', '--portals', 'linkedin',
          '--output-dir', str(tmp_path)])
    assert called[0].portals == ('linkedin',)
    assert called[0].keyword == 'Data Analyst'


def test_browser_use_does_not_silently_ignore_portal_options():
    with pytest.raises(SystemExit) as exc:
        main(['--days', '7'])
    assert exc.value.code == 2


def test_pending_cloudflare_verification_is_allowed_to_wait():
    class Element:
        text = 'Performing security verification. This website verifies you are not a bot.'
        def is_displayed(self):
            return True
    class VerificationPage(Driver):
        title = 'Just a moment...'
        def find_elements(self, by, selector):
            return [Element()] if selector == 'body' else []
    page = VerificationPage()
    assert access_problem(page) is None
    assert access_problem(page, include_pending=True).status == 'challenge_blocked'


def test_portal_failure_does_not_prevent_next_portal(tmp_path, monkeypatch):
    from src.crawler import runner
    class Broken(Adapter):
        def advance(self, *args):
            raise CrawlProblem('access_denied', 'denied')
    monkeypatch.setitem(runner.ADAPTERS, 'linkedin', Broken)
    monkeypatch.setitem(runner.ADAPTERS, 'jobstreet', Adapter)
    drivers = []
    def factory(_):
        driver = Driver()
        drivers.append(driver)
        return driver
    result = run(CrawlRequest(keyword='AI Engineer', portals=('linkedin', 'jobstreet'), delay=0),
                 tmp_path, factory)
    assert result['sources'][0]['state'] == 'failed'
    assert result['sources'][1]['state'] == 'completed'
    assert len(result['jobs']) == 3
    assert all(driver.closed for driver in drivers)


def test_detail_attempt_limit_is_enforced(tmp_path, monkeypatch):
    driver = setup_runner(monkeypatch)
    result = run(request(max_jobs=1), tmp_path, lambda _: driver)
    assert len(result['sources'][0]['details']) == 1
    assert result['sources'][0]['stop_reason'] == 'max_jobs'


def test_new_portal_search_filters():
    req = CrawlRequest(keyword='AI + ML Engineer', portals=('glints', 'indeed'))
    glints = parse_qs(urlsplit(GlintsAdapter(req).search_url()).query)
    assert glints['keyword'] == ['AI + ML Engineer']
    assert glints['country'] == ['ID']
    assert glints['sortBy'] == ['LATEST']
    assert GlintsAdapter.date_filter == 'latest_sort_only_no_age_filter'
    indeed = parse_qs(urlsplit(IndeedAdapter(req).search_url()).query, keep_blank_values=True)
    assert indeed == {'q': ['AI + ML Engineer'], 'l': [''], 'fromage': ['7']}
    req = CrawlRequest(keyword='AI Engineer', portals=('indeed',), location='Jakarta')
    assert parse_qs(urlsplit(IndeedAdapter(req).search_url()).query)['l'] == ['Jakarta']


@pytest.mark.parametrize('adapter,urls,key', [
    (GlintsAdapter, [
        'https://glints.com/id/opportunities/jobs/ai-engineer/205a0916-c9fa-418c-8e10-f1faeb1b69f3?utm_referrer=explore',
        'https://glints.com/id/opportunities/jobs/another-title/205a0916-c9fa-418c-8e10-f1faeb1b69f3?traceInfo=123',
    ], 'glints:205a0916-c9fa-418c-8e10-f1faeb1b69f3'),
    (IndeedAdapter, [
        'https://id.indeed.com/jobs?q=ai+engineer&vjk=db4460f475924520',
        'https://id.indeed.com/rc/clk?jk=db4460f475924520&from=search',
        'https://id.indeed.com/viewjob?jk=db4460f475924520',
    ], 'indeed:db4460f475924520'),
])
def test_new_portal_job_identity(adapter, urls, key):
    assert {adapter(request()).reference(url, '', '', 1).key for url in urls} == {key}


@pytest.mark.parametrize('adapter,url', [
    (GlintsAdapter, 'https://glints.com.evil.test/id/opportunities/jobs/title/205a0916-c9fa-418c-8e10-f1faeb1b69f3'),
    (GlintsAdapter, 'https://glints.com/id/opportunities/jobs/explore?keyword=AI'),
    (GlintsAdapter, 'https://glints.com/id/opportunities/jobs/title/not-a-uuid'),
    (IndeedAdapter, 'https://id.indeed.com.evil.test/viewjob?jk=db4460f475924520'),
    (IndeedAdapter, 'https://id.indeed.com/viewjob?jk=not-a-job-id'),
    (IndeedAdapter, 'https://id.indeed.com/account?jk=db4460f475924520'),
])
def test_new_portals_reject_non_job_urls(adapter, url):
    assert adapter(request()).reference(url, '', '', 1) is None


@pytest.mark.parametrize('headless,expected', [
    (None, [True, False, False, True, False, True, True]), (True, [True] * 7), (False, [False] * 7),
])
def test_browser_policy_applies_per_portal(tmp_path, monkeypatch, headless, expected):
    from src.crawler.adapters import ADAPTERS
    modes = []
    for adapter in ADAPTERS.values():
        monkeypatch.setattr(adapter, 'advance', lambda *args: [])
    def factory(req):
        modes.append(req.headless)
        return Driver()
    result = run(CrawlRequest(keyword='AI Engineer', portals=tuple(ADAPTERS), delay=0,
                             headless=headless), tmp_path, factory)
    assert modes == expected
    assert [source['headless'] for source in result['sources']] == expected


@pytest.mark.parametrize('flag,expected', [('--headed', False), ('--headless', True)])
def test_browser_cli_overrides(monkeypatch, flag, expected):
    called = []
    monkeypatch.setattr('src.crawler.runner.run',
                        lambda req, path: called.append(req) or {'state': 'completed'})
    main(['--mode', 'selenium', '--portals', 'glints', 'indeed', flag])
    assert called[0].headless is expected


@pytest.mark.parametrize('heading,expected', [
    ('Request Blocked', 'access_denied'), ('Additional Verification Required', 'challenge_blocked'),
])
def test_indeed_block_pages_are_classified(heading, expected):
    class Element:
        text = heading
        def is_displayed(self):
            return True
    class BlockedPage(Driver):
        def find_elements(self, by, selector):
            return [Element()] if selector == 'h1' else []
    assert access_problem(BlockedPage()).status == expected


def test_guest_pagination_limit_preserves_public_details(tmp_path, monkeypatch):
    class GuestLimited(Adapter):
        def advance(self, driver, page, seen):
            if page > 1:
                raise CrawlProblem('pagination_login_required', 'guest limit')
            return super().advance(driver, page, seen)
    driver = setup_runner(monkeypatch, GuestLimited)
    result = run(request(), tmp_path, lambda _: driver)
    assert len(result['jobs']) == 2
    assert result['sources'][0]['state'] == 'partial'
    assert result['sources'][0]['stop_reason'] == 'pagination_login_required'


@pytest.mark.parametrize('url', [
    'https://secure.indeed.com/auth?continue2=example',
    'https://secure.indeed.com/auth;jsessionid=fixture-session?hl=en',
])
def test_indeed_account_redirect_is_login_required(url):
    driver = Driver()
    driver.current_url = url
    assert access_problem(driver).status == 'login_required'


def test_login_gate_stops_detail_attempts_and_preserves_all_discoveries(tmp_path, monkeypatch):
    class LoginAdapter(Adapter):
        def extract(self, driver, ref):
            raise CrawlProblem('login_required', 'account required')
    driver = setup_runner(monkeypatch, LoginAdapter)
    result = run(request(), tmp_path, lambda _: driver)
    assert result['sources'][0]['state'] == 'partial'
    assert result['sources'][0]['stop_reason'] == 'login_required'
    assert len(result['sources'][0]['details']) == 1
    assert len(result['discovered_jobs']) == 3
    assert result['jobs'] == []
    discovered = json.loads(next(tmp_path.glob('*/discovered.json')).read_text(encoding='utf-8'))
    assert [job['external_id'] for job in discovered['jobs']] == ['1', '2', '3']
    assert discovered['jobs'][0]['title'] == 'Role 1'
    assert driver.closed


def test_indeed_login_diagnostics_omit_session_ids():
    from src.crawler.runner import diagnostics
    driver = Driver()
    driver.current_url = 'https://secure.indeed.com/auth;jsessionid=fixture-session?continue2=fixture'
    data = diagnostics(driver)
    assert data['observed_url'] == 'https://secure.indeed.com/auth'
    assert 'fixture-session' not in json.dumps(data)


def test_indeed_listing_context_ignores_selection_but_preserves_page_and_filters():
    key = IndeedAdapter._listing_key
    source = 'https://id.indeed.com/jobs?q=AI&fromage=7&vjk=db4460f475924520'
    assert key(source) == key('https://id.indeed.com/jobs?fromage=7&q=AI&vjk=ab4460f475924521')
    assert key(source) != key('https://id.indeed.com/jobs?q=AI&fromage=7&start=10')


def test_indeed_retries_card_once_only_after_dismissing_optional_login(monkeypatch):
    from selenium.common.exceptions import ElementClickInterceptedException
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
    driver = Driver()
    driver.current_url = adapter.search_url()
    ref = adapter.reference('https://id.indeed.com/viewjob?jk=db4460f475924520',
                            'AI Engineer', driver.current_url, 1)
    class Link:
        clicks = 0
        text = 'AI Engineer'
        def get_attribute(self, name):
            return ref.url
        def click(self):
            self.clicks += 1
            if self.clicks == 1:
                raise ElementClickInterceptedException('optional dialog appeared')
    link = Link()
    calls = []
    def optional_login(_):
        calls.append(True)
        if len(calls) == 2:
            adapter._dismissed_login = True
    monkeypatch.setattr(adapter, 'card_links', lambda _: [link])
    monkeypatch.setattr(adapter, '_optional_login', optional_login)
    adapter.open_detail(driver, ref)
    assert link.clicks == 2
    assert len(calls) == 2


def test_indeed_does_not_navigate_around_mandatory_account_login():
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
    ref = adapter.reference('https://id.indeed.com/viewjob?jk=db4460f475924520',
                            'AI Engineer', adapter.search_url(), 1)
    class LoginPage(Driver):
        current_url = 'https://secure.indeed.com/auth'
        def get(self, url):
            raise AssertionError('Do not retry an alternative route after mandatory login')
    with pytest.raises(CrawlProblem) as exc:
        adapter.open_detail(LoginPage(), ref)
    assert exc.value.status == 'login_required'


@pytest.mark.parametrize('href,marker,accepted', [
    ('', 'db4460f475924520', True),
    ('#', 'db4460f475924520', True),
    ('javascript:void(0)', 'db4460f475924520', True),
    ('https://evil.test/viewjob?jk=db4460f475924520', 'db4460f475924520', False),
    ('https://id.indeed.com/viewjob?jk=db4460f475924520', 'ab4460f475924521', False),
    ('', 'not-an-id', False),
])
def test_indeed_card_attribute_identity_is_scoped_to_trusted_listing(href, marker, accepted):
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
    class Link:
        text = 'AI Engineer'
        def get_attribute(self, name):
            return {'href': href, 'data-jk': marker}.get(name)
    result = adapter.reference_from_link(Link(), adapter.search_url(), 1)
    assert (result is not None) is accepted
    if result:
        assert result.external_id == 'db4460f475924520'


def test_optional_stale_metadata_does_not_discard_discovered_card(monkeypatch):
    from selenium.common.exceptions import StaleElementReferenceException
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
    class Link:
        text = 'AI Engineer'
        def get_attribute(self, name):
            return {'href': 'https://id.indeed.com/rc/clk?jk=db4460f475924520',
                    'data-jk': 'db4460f475924520'}.get(name)
    driver = Driver()
    driver.current_url = adapter.search_url()
    monkeypatch.setattr(adapter, 'card_links', lambda _: [Link()])
    def stale(*_):
        raise StaleElementReferenceException('React replaced the metadata')
    monkeypatch.setattr(adapter, 'card_metadata', stale)
    refs = adapter.collect(driver, 1)
    assert len(refs) == 1
    assert refs[0].external_id == 'db4460f475924520'
    assert refs[0].company is None


def test_per_page_details_are_saved_before_next_page_challenge(tmp_path, monkeypatch):
    events = []
    class PerPage(Adapter):
        details_per_page = True
        def advance(self, driver, page, seen):
            events.append(f'listing-{page}')
            if page == 2:
                raise CrawlProblem('challenge_blocked', 'next page verification')
            return super().advance(driver, page, seen)
        def extract(self, driver, ref):
            events.append(f'detail-{ref.external_id}')
            return super().extract(driver, ref)
    driver = setup_runner(monkeypatch, PerPage)
    result = run(request(), tmp_path, lambda _: driver)
    assert events == ['listing-1', 'detail-1', 'detail-2', 'listing-2']
    assert len(result['jobs']) == 2
    assert result['sources'][0]['state'] == 'partial'
    assert result['sources'][0]['listing_error']['status'] == 'challenge_blocked'
    saved = json.loads(next(tmp_path.glob('*/jobs.json')).read_text(encoding='utf-8'))
    assert len(saved['jobs']) == 2
    assert driver.closed


def test_per_page_detail_login_stops_before_pagination(tmp_path, monkeypatch):
    pages = []
    class PerPage(Adapter):
        details_per_page = True
        def advance(self, driver, page, seen):
            pages.append(page)
            return super().advance(driver, page, seen)
        def extract(self, driver, ref):
            raise CrawlProblem('login_required', 'mandatory account')
    driver = setup_runner(monkeypatch, PerPage)
    result = run(request(), tmp_path, lambda _: driver)
    assert pages == [1]
    assert len(result['discovered_jobs']) == 2
    assert len(result['sources'][0]['details']) == 1
    assert result['sources'][0]['stop_reason'] == 'login_required'


def test_per_page_schedule_deduplicates_details_and_enforces_total_cap(tmp_path, monkeypatch):
    class PerPage(Adapter):
        details_per_page = True
    driver = setup_runner(monkeypatch, PerPage)
    result = run(request(max_jobs=3), tmp_path, lambda _: driver)
    assert [detail['external_id'] for detail in result['sources'][0]['details']] == ['1', '2', '3']
    assert result['sources'][0]['stop_reason'] == 'max_jobs'
    assert len(result['jobs']) == 3
