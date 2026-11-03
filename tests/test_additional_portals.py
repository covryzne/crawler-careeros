from urllib.parse import parse_qs, urlsplit

import pytest

from src.crawler.adapters import ADAPTERS
from src.crawler.models import CrawlRequest, PORTALS


URLS = {
    'dealls': 'https://dealls.com/en/loker/data-engineer-2~example-company',
    'kalibrr': 'https://www.kalibrr.com/id-ID/c/example-company/jobs/248988/data-engineer',
    'techinasia': 'https://www.techinasia.com/jobs/617f6576-cc1a-4057-a1fb-a974b56008a0',
}


@pytest.mark.parametrize('portal', URLS)
def test_identity_is_independent_of_tracking_and_locale(portal):
    adapter = ADAPTERS[portal](CrawlRequest(keyword='data engineer', portals=(portal,)))
    original = adapter.reference(URLS[portal], 'Data Engineer', 'listing', 1)
    alternate = URLS[portal].replace('/en/loker/', '/loker/').replace('/id-ID/c/', '/c/')
    ref = adapter.reference(alternate + '?utm_source=search#tracking', '', '', 2)
    assert ref.key == original.key
    assert ref.url == original.url
    assert portal in PORTALS
    foreign = URLS[portal].replace(urlsplit(URLS[portal]).hostname,
                                 urlsplit(URLS[portal]).hostname + '.evil.test')
    assert adapter.reference(foreign, '', '', 1) is None
    assert adapter.reference(URLS[portal].replace('https:', 'http:'), '', '', 1) is None


@pytest.mark.parametrize('portal,url', [
    ('dealls', 'https://dealls.com/en/loker/saved'),
    ('dealls', 'https://dealls.com/en/loker/applied'),
    ('dealls', 'https://dealls.com/en/loker/data%2Fother~company'),
    ('kalibrr', 'https://www.kalibrr.com/id-ID/c/company/jobs'),
    ('kalibrr', 'https://www.kalibrr.com/id-ID/c/company/jobs/123/data%2Fother'),
    ('techinasia', 'https://www.techinasia.com/jobs/employers'),
    ('techinasia', URLS['techinasia'] + '/apply'),
])
def test_non_job_urls_are_rejected(portal, url):
    adapter = ADAPTERS[portal](CrawlRequest(keyword='data', portals=(portal,)))
    assert adapter.reference(url, '', '', 1) is None


@pytest.mark.parametrize('portal', URLS)
def test_new_portal_location_cannot_be_silently_ignored(portal):
    with pytest.raises(ValueError, match='Indonesia only'):
        CrawlRequest(keyword='data', portals=(portal,), location='Singapore')


def test_search_keywords_and_filters():
    req = CrawlRequest(keyword='AI + Data Engineer', portals=tuple(URLS))
    urls = {p: ADAPTERS[p](req).search_url() for p in URLS}
    assert parse_qs(urlsplit(urls['dealls']).query) == {'searchJob': ['AI + Data Engineer']}
    assert '/te/AI-%2B-Data-Engineer?' in urls['kalibrr']
    assert parse_qs(urlsplit(urls['kalibrr']).query) == {'sort': ['Freshness']}
    assert parse_qs(urlsplit(urls['techinasia']).query) == {
        'query': ['AI + Data Engineer'], 'country_name[]': ['Indonesia']}
    assert all('no_age_filter' in ADAPTERS[p].date_filter for p in URLS)


def test_kalibrr_waits_until_hydration_replaces_initial_cards(monkeypatch):
    from src.crawler.adapters.kalibrr import KalibrrAdapter
    from src.crawler.adapters.pagination import ObservedPaginationAdapter
    from src.crawler.models import JobReference
    old = JobReference('kalibrr', '1', 'old', 'Temporary', '', 1)
    actual = JobReference('kalibrr', '2', 'new', 'Data Engineer', '', 1)
    adapter = KalibrrAdapter(CrawlRequest(keyword='data', portals=('kalibrr',), timeout=1))
    adapter.listing_settle_seconds = 0.1
    clock = iter([0, 0, 0.01, 0.1, 0.11, 0.15, 0.25])
    monkeypatch.setattr('src.crawler.adapters.kalibrr.time.monotonic', lambda: next(clock))
    monkeypatch.setattr('src.crawler.adapters.kalibrr.access_problem', lambda _: None)
    monkeypatch.setattr(ObservedPaginationAdapter, 'advance', lambda *args: [old])
    cards = iter([[old], [actual], [actual], [actual]])
    monkeypatch.setattr(adapter, 'collect', lambda *args: next(cards))
    # A deterministic wait drives the readiness predicate through hydration.
    class Wait:
        def __init__(self, driver, *args, **kwargs):
            self.driver = driver
        def until(self, ready):
            for _ in range(4):
                result = ready(self.driver)
                if result:
                    return result
            raise AssertionError('listing did not settle')
    monkeypatch.setattr('src.crawler.adapters.kalibrr.WebDriverWait', Wait)
    assert adapter.advance(object(), 1, set()) == [actual]


def test_cloudflare_access_block_is_not_reported_as_selector_timeout():
    from src.crawler.adapters.base import access_problem
    class Element:
        text = 'Sorry, you have been blocked\nYou are unable to access dealls.com'
        def is_displayed(self):
            return True
    class Page:
        current_url = 'https://dealls.com/en?searchJob=data'
        title = 'Attention Required! | Cloudflare'
        def find_elements(self, by, selector):
            return [Element()] if selector == 'body' else []
    assert access_problem(Page()).status == 'access_denied'
