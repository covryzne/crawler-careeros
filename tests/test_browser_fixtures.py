"""Opt-in Chrome checks against synthetic fixtures, NOT evidence of live-site support."""
import os
from pathlib import Path

import pytest
from selenium.common.exceptions import TimeoutException

from src.crawler.adapters.jobstreet import JobStreetAdapter
from src.crawler.adapters.linkedin import LinkedInAdapter
from src.crawler.adapters.glints import GlintsAdapter
from src.crawler.adapters.indeed import IndeedAdapter
from src.crawler.adapters import ADAPTERS
from src.crawler.adapters.base import CrawlProblem
from src.crawler.models import CrawlRequest
from src.crawler.runner import create_driver

pytestmark = pytest.mark.skipif(os.getenv('CRAWLER_BROWSER_TESTS') != '1',
                               reason='Set CRAWLER_BROWSER_TESTS=1 to launch local Chrome')


class FixturePage:
    """Use a local DOM with a declared source URL; no connection to the portal."""
    def __init__(self, driver, current_url):
        self.driver = driver
        self.current_url = current_url

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def get(self, url):
        raise AssertionError(f'Local fixture must not navigate to a remote URL: {url}')


@pytest.fixture
def browser():
    driver = create_driver(CrawlRequest(keyword='AI Engineer', portals=('jobstreet',)))
    yield driver
    driver.quit()


@pytest.mark.parametrize('portal,adapter_class,url,job_id', [
    ('jobstreet', JobStreetAdapter, 'https://id.jobstreet.com/id/job/95550334', '95550334'),
    ('linkedin', LinkedInAdapter, 'https://www.linkedin.com/jobs/view/4484811461/', '4484811461'),
    ('glints', GlintsAdapter, 'https://glints.com/id/opportunities/jobs/ai-engineer/205a0916-c9fa-418c-8e10-f1faeb1b69f3', '205a0916-c9fa-418c-8e10-f1faeb1b69f3'),
    ('indeed', IndeedAdapter, 'https://id.indeed.com/viewjob?jk=db4460f475924520', 'db4460f475924520'),
])
def test_card_discovery_and_complete_detail_text(browser, portal, adapter_class, url, job_id):
    browser.get((Path(__file__).parent / 'fixtures' / f'{portal}.html').resolve().as_uri())
    adapter = adapter_class(CrawlRequest(keyword='AI Engineer', portals=(portal,), timeout=0.5))
    page = FixturePage(browser, url)
    refs = adapter.collect(page, 1)
    assert len(refs) == 1
    assert refs[0].external_id == job_id
    job = adapter.extract(page, refs[0])
    assert job.title == 'AI Engineer'
    assert job.company == 'Example Indonesia'
    assert 'Build AI systems.' in job.raw_description
    assert 'Learning allowance.' in job.raw_description
    assert job.requirements is None  # Benefits are never relabeled as requirements.
    if portal == 'glints':
        assert job.location == 'Jakarta, DKI Jakarta, ID'
        assert job.posted_at_raw == '2026-11-01T10:00:00Z'
    # A different selected job must not be accepted just because the DOM exists.
    page.current_url = url.replace(job_id, '999')
    with pytest.raises(TimeoutException):
        adapter.extract(page, refs[0])


def test_linkedin_empty_overlay_uses_title_from_its_own_card(browser):
    browser.get('about:blank')
    browser.execute_script('''
      document.body.innerHTML = `<ul class="jobs-search__results-list">
        <li><a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123/">
        </a><h3 class="base-search-card__title">Data Engineer</h3></li>
        <li><a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/456/">
        <span class="sr-only" style="display:none">AI Engineer</span></a></li></ul>`;
    ''')
    adapter = LinkedInAdapter(CrawlRequest(keyword='Engineer', portals=('linkedin',)))
    refs = adapter.collect(FixturePage(browser, adapter.search_url()), 1)
    assert [(ref.external_id, ref.title) for ref in refs] == [
        ('123', 'Data Engineer'), ('456', 'AI Engineer')]


@pytest.mark.parametrize('portal,adapter_class,new_url', [
    ('glints', GlintsAdapter,
     'https://glints.com/id/opportunities/jobs/second-role/4330dc0e-5f94-4651-b484-fbb469bcc6a8'),
    ('indeed', IndeedAdapter,
     'https://id.indeed.com/viewjob?jk=ab4460f475924521'),
])
def test_pagination_waits_for_new_ids_and_stops_at_disabled_next(
        browser, portal, adapter_class, new_url):
    browser.get((Path(__file__).parent / 'fixtures' / f'{portal}.html').resolve().as_uri())
    adapter = adapter_class(CrawlRequest(keyword='AI Engineer', portals=(portal,), timeout=0.5))
    page = FixturePage(browser, adapter.search_url())
    previous = {ref.key for ref in adapter.collect(page, 1)}
    browser.execute_script('''
      const b = document.createElement('button');
      b.textContent = 'Next';
      b.setAttribute(arguments[0], arguments[1]);
      const url = arguments[2];
      b.onclick = () => {
        const a = document.createElement('a'); a.href = url;
        a.setAttribute('aria-label', 'Job card title: Second role');
        a.className = 'jcs-JobTitle'; a.textContent = 'Second role';
        document.body.append(a); b.disabled = true;
      };
      document.body.append(b);
    ''', 'aria-label' if portal == 'glints' else 'data-testid',
        'Next page' if portal == 'glints' else 'pagination-page-next', new_url)
    refs = adapter.advance(page, 2, previous)
    assert len(refs) == 2
    assert any(ref.search_page == 2 and ref.key not in previous for ref in refs)
    assert adapter.advance(page, 3, {ref.key for ref in refs}) == []


def test_glints_guest_gate_is_not_clicked(browser):
    browser.get((Path(__file__).parent / 'fixtures/glints.html').resolve().as_uri())
    adapter = GlintsAdapter(CrawlRequest(keyword='AI Engineer', portals=('glints',), timeout=0.5))
    page = FixturePage(browser, adapter.search_url())
    browser.execute_script('''
      const button = document.createElement('button');
      button.id = 'see-more-jobs-login-button'; button.textContent = 'Login Sekarang';
      button.onclick = () => { document.title = 'clicked login'; };
      document.body.append(button);
    ''')
    with pytest.raises(CrawlProblem) as exc:
        adapter.advance(page, 2, {ref.key for ref in adapter.collect(page, 1)})
    assert exc.value.status == 'pagination_login_required'
    assert browser.title != 'clicked login'


def test_missing_pagination_is_reported_instead_of_assuming_end(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed.html').resolve().as_uri())
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=0.5))
    page = FixturePage(browser, adapter.search_url())
    with pytest.raises(CrawlProblem) as exc:
        adapter.advance(page, 2, {ref.key for ref in adapter.collect(page, 1)})
    assert exc.value.status == 'pagination_unavailable'


def test_indeed_uses_public_panel_and_retains_card_metadata(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-panel.html').resolve().as_uri())
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=1))
    source = adapter.search_url()
    page = FixturePage(browser, source + '&vjk=db4460f475924520')
    refs = adapter.collect(page, 1)
    assert len(refs) == 2
    assert refs[0].company == 'First Company'
    assert refs[0].location == 'Jakarta'
    assert refs[0].snippet == 'First card summary only.'
    assert refs[0].observed_url.endswith('jk=db4460f475924520')
    adapter.open_detail(page, refs[0])
    first = adapter.extract(page, refs[0])
    assert first.description == 'First job full description.'
    browser.execute_script('window.deferPanelUpdate = true')
    adapter.open_detail(page, refs[1])
    page.current_url = source + '&vjk=ab4460f475924521'
    # URL has switched; the reused panel still belongs to the old job.
    assert adapter.detail_context(page, refs[1]) is None
    browser.execute_script('window.commitPanel()')
    second = adapter.extract(page, refs[1])
    assert second.company == 'Second Company'
    assert second.description == 'Second job full description.'
    assert browser.execute_script('return document.body.dataset.selected') == refs[1].external_id


def test_indeed_same_title_panel_without_marker_waits_for_content_change(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-panel.html').resolve().as_uri())
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=1))
    page = FixturePage(browser, adapter.search_url() + '&vjk=db4460f475924520')
    refs = adapter.collect(page, 1)
    browser.execute_script('window.deferPanelUpdate = true')
    browser.execute_script("document.getElementById('jobsearch-ViewjobPaneWrapper').removeAttribute('data-jk')")
    adapter.open_detail(page, refs[1])
    page.current_url = adapter.search_url() + '&vjk=ab4460f475924521'
    assert adapter.detail_context(page, refs[1]) is None
    browser.execute_script('window.commitPanel()')
    assert adapter.extract(page, refs[1]).description == 'Second job full description.'


@pytest.mark.parametrize('dismissible', [True, False])
def test_indeed_optional_login_is_closed_but_mandatory_login_stops(browser, dismissible):
    browser.get((Path(__file__).parent / 'fixtures/indeed-panel.html').resolve().as_uri())
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=1))
    page = FixturePage(browser, adapter.search_url() + '&vjk=db4460f475924520')
    ref = adapter.collect(page, 1)[0]
    browser.execute_script('''
      const dialog = document.createElement('div'); dialog.setAttribute('role', 'dialog');
      dialog.textContent = 'Sign in to Indeed';
      if (arguments[0]) {
        const close = document.createElement('button'); close.setAttribute('aria-label', 'Close');
        close.textContent = 'Close'; close.onclick = () => dialog.remove(); dialog.append(close);
      }
      document.body.append(dialog);
    ''', dismissible)
    if dismissible:
        adapter.open_detail(page, ref)
        assert adapter.extract(page, ref).description == 'First job full description.'
    else:
        with pytest.raises(CrawlProblem) as exc:
            adapter.open_detail(page, ref)
        assert exc.value.status == 'login_required'


def test_indeed_collects_h3_card_with_attribute_identity_and_no_href(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-panel.html').resolve().as_uri())
    browser.execute_script('''
      const a = document.querySelector('a.jcs-JobTitle');
      a.removeAttribute('href'); a.dataset.jk = 'db4460f475924520'; a.setAttribute('role','button');
      const heading = document.createElement('h3'); heading.className = 'jobTitle';
      a.parentNode.replaceWith(heading); heading.append(a);
    ''')
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
    page = FixturePage(browser, adapter.search_url())
    refs = adapter.collect(page, 1)
    assert len(refs) == 2
    assert refs[0].external_id == 'db4460f475924520'
    assert refs[0].url == 'https://id.indeed.com/viewjob?jk=db4460f475924520'


def test_indeed_reads_visible_description_section_without_legacy_ids(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-semantic-panel.html').resolve().as_uri())
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=1))
    page = FixturePage(browser, adapter.search_url() + '&vjk=db4460f475924520')
    ref = adapter.collect(page, 1)[0]
    adapter.open_detail(page, ref)
    job = adapter.extract(page, ref)
    assert job.title == 'AI Engineer'
    assert 'production AI systems' in job.description
    assert 'Learning allowance' in job.description
    assert 'RECOMMENDATION' not in job.description
    assert 'FOOTER' not in job.description
    assert 'Example Indonesia' not in job.description


def test_indeed_does_not_use_entire_panel_when_description_section_is_unknown(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-semantic-panel.html').resolve().as_uri())
    browser.execute_script("[...document.querySelectorAll('h2')].find(e=>e.textContent==='Full job description').textContent='Other section'")
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=0.5))
    page = FixturePage(browser, adapter.search_url() + '&vjk=db4460f475924520')
    ref = adapter.collect(page, 1)[0]
    with pytest.raises(TimeoutException):
        adapter.extract(page, ref)


def test_indeed_new_native_layout_matches_observed_live_structure(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-native-panel.html').resolve().as_uri())
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',), timeout=1))
    page = FixturePage(browser, adapter.search_url() + '&vjk=c426cd39d59fcca9')
    ref = adapter.collect(page, 1)[0]
    adapter.open_detail(page, ref)
    job = adapter.extract(page, ref)
    assert job.title == 'Data & AI Platform Engineer'
    assert job.company == 'Example Indonesia'
    assert job.location == 'Jakarta'
    assert 'AI runtime infrastructure' in job.description
    assert 'professional development' in job.description
    assert 'UNRELATED' not in job.description
    assert 'Apply on company site' not in job.description
    assert job.requirements is None


def test_indeed_hidden_duplicate_links_are_not_discovered_as_jobs(browser):
    browser.get((Path(__file__).parent / 'fixtures/indeed-panel.html').resolve().as_uri())
    browser.execute_script('''
      const link=document.createElement('a'); link.className='jcs-JobTitle';
      link.href='https://id.indeed.com/viewjob?jk=f1e2d3c4b5a67890';
      link.dataset.jk='f1e2d3c4b5a67890'; link.textContent='Hidden duplicate';
      link.style.display='none'; document.body.append(link);
    ''')
    adapter = IndeedAdapter(CrawlRequest(keyword='AI Engineer', portals=('indeed',)))
    page = FixturePage(browser, adapter.search_url())
    assert len(adapter.collect(page, 1)) == 2
    assert all(ref.external_id != 'f1e2d3c4b5a67890' for ref in adapter.collect(page, 1))


@pytest.mark.parametrize('portal,url,card,detail', [
    ('dealls', 'https://dealls.com/en/loker/data-engineer~example',
     '<a data-index="0" href="https://dealls.com/en/loker/data-engineer~example"><h2>Data Engineer</h2></a>',
     '<header><div><h1>Data Engineer</h1><a href="/en/karir/example"><h2>Example</h2></a></div></header>'
     '<div class="SectionWrapper_job_description__hash"><h3>Job Description</h3><div>Build pipelines.</div></div>'
     '<div><h3>Requirements</h3><div>Know SQL.</div></div><div><h3>Benefits</h3><div>Learning allowance.</div></div>'),
    ('kalibrr', 'https://www.kalibrr.com/id-ID/c/example/jobs/123/data-engineer',
     '<h2><a itemprop="name" href="https://www.kalibrr.com/id-ID/c/example/jobs/123/data-engineer">Data Engineer</a></h2>',
     '<h1 itemprop="title">Data Engineer</h1><span><a><h2>Example</h2></a></span>'
     '<div itemprop="description">Build pipelines.</div><div itemprop="qualifications">Know SQL.</div>'
     '<div itemprop="jobBenefits">Learning allowance.</div><span itemprop="datePosted" style="display:none">2026-09-01</span>'),
    ('techinasia', 'https://www.techinasia.com/jobs/617f6576-cc1a-4057-a1fb-a974b56008a0',
     '<h3 class="job-title"><a href="https://www.techinasia.com/jobs/617f6576-cc1a-4057-a1fb-a974b56008a0">Data Engineer</a></h3>',
     '<div class="header-content"><h1>Data Engineer</h1><a href="/companies/example">Example</a></div>'
     '<section><h2>Job description &amp; requirements</h2><div>Build pipelines. Know SQL. Learning allowance.</div></section>'
     '<section><h2>Required skills</h2><div>Python</div></section>'),
])
def test_additional_portal_rendered_details_are_scoped(browser, tmp_path, portal, url, card, detail):
    path = tmp_path / 'portal.html'
    path.write_text('<html><body>' + card + detail +
                    '<section><h2>About the company</h2><div>UNRELATED COMPANY TEXT</div></section>'
                    '<section><h2>Similar jobs</h2><div>UNRELATED RECOMMENDATION</div></section>'
                    '</body></html>', encoding='utf-8')
    browser.get(path.resolve().as_uri())
    adapter = ADAPTERS[portal](CrawlRequest(keyword='data', portals=(portal,), timeout=0.5))
    page = FixturePage(browser, url)
    refs = adapter.collect(page, 1)
    assert len(refs) == 1
    assert refs[0].title == 'Data Engineer'
    job = adapter.extract(page, refs[0])
    assert job.company == 'Example'
    assert 'Build pipelines.' in job.raw_description
    assert 'Know SQL.' in job.raw_description
    assert 'Learning allowance.' in job.raw_description
    assert 'UNRELATED' not in job.raw_description
    if portal != 'techinasia':
        assert job.requirements == 'Know SQL.'
    if portal == 'kalibrr':
        assert job.posted_at_raw == '2026-09-01'
    page.current_url = url.replace('data-engineer~example', 'saved').replace('617f6576', '00000000')
    if portal == 'kalibrr':
        page.current_url = url.replace('/123/', '/999/')
    with pytest.raises(TimeoutException):
        adapter.extract(page, refs[0])


@pytest.mark.parametrize('portal,label', [('dealls', 'See More'), ('kalibrr', 'Load more jobs')])
def test_additional_portal_load_more_uses_observed_control(browser, tmp_path, portal, label):
    from src.crawler.adapters.base import CrawlProblem
    path = tmp_path / 'pagination.html'
    path.write_text('<html><body><button disabled>' + label + '</button></body></html>', encoding='utf-8')
    browser.get(path.resolve().as_uri())
    adapter = ADAPTERS[portal](CrawlRequest(keyword='data', portals=(portal,), timeout=0.2))
    page = FixturePage(browser, adapter.search_url())
    assert adapter.advance(page, 2, set()) == []
    browser.execute_script('document.querySelector("button").remove()')
    with pytest.raises(CrawlProblem, match='No next-page control'):
        adapter.advance(page, 2, set())


@pytest.mark.parametrize('blocked', [False, True])
def test_detail_session_preserves_listing_dom_and_closes_its_tab(browser, tmp_path, blocked):
    path = tmp_path / 'listing.html'
    path.write_text('<html><body><div id="loaded-batch">batch 2 loaded</div></body></html>', encoding='utf-8')
    browser.get(path.resolve().as_uri())
    listing = browser.current_window_handle
    adapter = JobStreetAdapter(CrawlRequest(keyword='data', portals=('jobstreet',)))
    def process():
        with adapter.detail_session(browser):
            assert browser.current_window_handle != listing
            browser.get('about:blank')
            if blocked:
                raise CrawlProblem('challenge_blocked', 'test challenge')
    if blocked:
        with pytest.raises(CrawlProblem):
            process()
    else:
        process()
    assert browser.window_handles == [listing]
    assert browser.current_window_handle == listing
    assert browser.find_element('id', 'loaded-batch').text == 'batch 2 loaded'


def test_indeed_detail_session_keeps_public_panel_tab(browser):
    browser.get('about:blank')
    listing = browser.current_window_handle
    adapter = IndeedAdapter(CrawlRequest(keyword='data', portals=('indeed',)))
    with adapter.detail_session(browser):
        assert browser.current_window_handle == listing
        assert browser.window_handles == [listing]
