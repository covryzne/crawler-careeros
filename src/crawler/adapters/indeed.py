import re
from urllib.parse import parse_qs, urlencode, urlsplit

from selenium.webdriver.common.by import By
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..models import JobReference
from .pagination import ObservedPaginationAdapter
from .base import CrawlProblem, access_problem, first_text


class IndeedAdapter(ObservedPaginationAdapter):
    name = 'indeed'
    details_per_page = True
    card_link_selector = ('a.jcs-JobTitle, .jobTitle a, a[data-testid="job-title"], '
                          'a[data-jk][role="button"]')
    title_selectors = ('[data-testid="vj-job-title"]',
                       'h1[data-testid="jobsearch-JobInfoHeader-title"]',
                       'h1.jobsearch-JobInfoHeader-title',
                       'h2[data-testid="jobsearch-JobInfoHeader-title"]',
                       'h2.jobsearch-JobInfoHeader-title')
    description_selectors = ('#jobDescriptionText', '.simple-job-description-html')
    company_selectors = ('[data-testid="company-info-metadata"] a[href*="/cmp/"]',
                         '[data-testid="inlineHeader-companyName"]',
                         '[data-testid="company-name"]', '.jobsearch-InlineCompanyRating-companyHeader a')
    location_selectors = ('[data-testid="inlineHeader-companyLocation"]',
                          '[data-testid="job-location"]')
    salary_selectors = ('#salaryInfoAndJobType', '[data-testid="salaryInfoAndJobType"]')
    posted_selectors = ('[data-testid="job-age"]',)
    empty_selectors = ('.jobsearch-NoResult-messageContainer', '[data-testid="no-results"]')
    next_selectors = ('a[data-testid="pagination-page-next"]',
                      'button[data-testid="pagination-page-next"]', 'a[aria-label="Next Page"]')
    panel_selectors = ('#jobsearch-ViewjobPaneWrapper', '.jobsearch-RightPane',
                       '[data-testid="jobsearch-JobComponent"]', '.jobsearch-JobComponent', '#vjs-container')

    def __init__(self, request):
        super().__init__(request)
        self._previous_panel_id = None
        self._previous_description = None
        self._expected_key = None
        self._dismissed_login = False
        self._listing_url = None

    def advance(self, driver, page, previous_ids):
        if page > 1 and self._listing_url:
            problem = access_problem(driver)
            if problem:
                raise problem
            if self._listing_key(driver.current_url) != self._listing_key(self._listing_url):
                driver.get(self._listing_url)
                self.wait_listing(driver, page - 1)
        refs = super().advance(driver, page, previous_ids)
        self._listing_url = driver.current_url
        return refs

    def search_url(self, page=1):
        location = '' if self.request.location.casefold().strip() == 'indonesia' else self.request.location
        return 'https://id.indeed.com/jobs?' + urlencode({
            'q': self.request.keyword, 'l': location, 'fromage': self.request.days,
        })

    def reference(self, url, title, source, page):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in {'id.indeed.com', 'www.indeed.com', 'indeed.com'}:
            return None
        if parts.path.rstrip('/') not in {'/viewjob', '/jobs', '/rc/clk', '/pagead/clk'}:
            return None
        query = parse_qs(parts.query)
        job_id = query.get('jk', query.get('vjk', ['']))[0].lower()
        if not re.fullmatch(r'[0-9a-f]{16}', job_id):
            return None
        return JobReference(self.name, job_id, f'https://id.indeed.com/viewjob?jk={job_id}',
                            title, source, page)

    def card_links(self, driver):
        visible = []
        for link in driver.find_elements(By.CSS_SELECTOR, self.card_link_selector):
            try:
                if link.is_displayed() and link.is_enabled():
                    visible.append(link)
            except StaleElementReferenceException:
                continue
        return visible

    def reference_from_link(self, link, source, page):
        href = link.get_attribute('href') or ''
        title = link.text.strip()
        ref = self.reference(href, title, source, page)
        marker = (link.get_attribute('data-jk') or '').lower()
        valid_marker = re.fullmatch(r'[0-9a-f]{16}', marker)
        if ref is not None:
            return None if valid_marker and marker != ref.external_id else ref
        # Some listing layouts expose card identity via data-jk rather than href.
        # Trust that identity only on the supported public listing and never follow
        # a foreign URL merely because its element has a data-jk attribute.
        origin = urlsplit(source)
        if (not valid_marker or origin.scheme != 'https' or origin.hostname != 'id.indeed.com'
                or origin.path != '/jobs'):
            return None
        target = urlsplit(href)
        if href and href not in {'#', 'javascript:void(0)', 'javascript:void(0);'}:
            if (target.scheme != 'https' or target.hostname != origin.hostname
                    or target.path not in {'/jobs', '/rc/clk', '/pagead/clk', '/viewjob'}):
                return None
        return JobReference(self.name, marker, f'https://id.indeed.com/viewjob?jk={marker}',
                            title, source, page)

    def discovery_diagnostics(self, driver):
        rows = driver.execute_script('''return [...document.querySelectorAll(arguments[0])]
          .filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')
          .slice(0, 5).map(e => ({href: e.href || '', id: e.getAttribute('data-jk'),
                               title: e.innerText.slice(0, 120)}))''', self.card_link_selector)
        structure = driver.execute_script('''return {
          description_count: document.querySelectorAll(arguments[1]).length,
          panels: arguments[0].map(s => ({selector:s,count:document.querySelectorAll(s).length})),
          frames: [...document.querySelectorAll('iframe')].slice(0,6).map(e => ({id:e.id,src:e.src})),
          page_tail: document.body.innerText.slice(-1600)
        }''', list(self.panel_selectors), ','.join(self.description_selectors))
        structure['frames'] = [{'id': frame['id'], 'host': urlsplit(frame['src']).hostname,
                                'path': urlsplit(frame['src']).path.split(';', 1)[0]}
                               for frame in structure['frames']]
        return {'detail_structure': structure, 'card_candidates': len(self.card_links(driver)), 'card_samples': [
            {'host': urlsplit(row['href']).hostname, 'path': urlsplit(row['href']).path,
             'url_job_id': parse_qs(urlsplit(row['href']).query).get('jk', [None])[0],
             'element_job_id': row['id'], 'title': row['title']} for row in rows]}

    def card_metadata(self, link, ref):
        cards = link.find_elements(By.XPATH,
            './ancestor::*[@data-jk or contains(concat(" ", normalize-space(@class), " "), " job_seen_beacon ")][1]')
        if not cards:
            return {}
        card = cards[0]
        marker = card.get_attribute('data-jk')
        if marker and marker != ref.external_id:
            return {}
        return {
            'company': first_text(card, ('[data-testid="company-name"]', '.companyName')),
            'location': first_text(card, ('[data-testid="text-location"]', '.companyLocation')),
            'salary': first_text(card, ('.salary-snippet-container', '[data-testid="salary-snippet"]')),
            'snippet': first_text(card, ('.job-snippet', '[data-testid="job-snippet"]',
                                         '[data-testid="belowJobSnippet"]')),
        }

    def _panel(self, driver):
        for selector in self.panel_selectors:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                if element.is_displayed():
                    return element
        return None

    def read_title(self, root, ref):
        title = super().read_title(root, ref)
        if title:
            return title
        expected = ' '.join(ref.title.casefold().split())
        if not expected:
            return None
        for heading in root.find_elements(By.CSS_SELECTOR, 'h1,h2,h3,[role="heading"]'):
            if heading.is_displayed() and ' '.join(heading.text.casefold().split()) == expected:
                return heading.text.strip()
        return None

    def read_description(self, driver, root, ref):
        description = super().read_description(driver, root, ref)
        if description:
            return description
        # New layouts may render the description without the legacy ID. Use the
        # visible description section inside the identity-checked detail panel.
        # Never treat the entire panel (metadata, recommendations, footer) as text.
        return driver.execute_script('''
          const root=arguments[0];
          const norm=s=>s.trim().toLowerCase().replace(/[:\\s]+$/g,'');
          const labels=new Set(['full job description','job description',
            'deskripsi pekerjaan','deskripsi lowongan','deskripsi lengkap pekerjaan']);
          const boundaries=new Set(['similar jobs','similar jobs nearby','report job',
            'return to search result','browse jobs','people also searched']);
          const visible=e=>e.getClientRects().length>0 && getComputedStyle(e).visibility!=='hidden';
          const headings=[...root.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')];
          for (const h of headings.filter(e=>visible(e)&&labels.has(norm(e.innerText)))) {
            let branch=h;
            for(let depth=0;depth<4 && branch && branch!==root;depth++,branch=branch.parentElement) {
              const parts=[];
              let sibling=branch.nextElementSibling;
              for(let count=0;sibling && root.contains(sibling)&&count<20;count++,sibling=sibling.nextElementSibling) {
                if(!visible(sibling))continue;
                if(sibling.matches('footer,nav')||boundaries.has(norm(sibling.innerText)))break;
                if([...sibling.querySelectorAll('h1,h2,h3,h4,[role="heading"]')]
                   .some(e=>boundaries.has(norm(e.innerText))))break;
                if(sibling.matches('button,a'))continue;
                const text=sibling.innerText.trim();
                if(text)parts.push(text);
              }
              const text=parts.join('\\n\\n');
              if(text.length>=40)return text;
            }
          }
          return null;
        ''', root)

    def extra_fields(self, driver, ref):
        root = self.detail_context(driver, ref)
        if root is None:
            return {}
        # Card metadata is a captured observation for this exact job ID, not a
        # requirement to infer fields from the combined company/rating/location row.
        return {'company': first_text(root, self.company_selectors) or ref.company,
                'location': first_text(root, self.location_selectors) or ref.location,
                'salary': first_text(root, self.salary_selectors) or ref.salary}

    def _optional_login(self, driver):
        for dialog in driver.find_elements(By.CSS_SELECTOR, '[role="dialog"], [aria-modal="true"]'):
            if not dialog.is_displayed():
                continue
            text = dialog.text.casefold()
            if not any(word in text for word in ('sign in', 'log in', 'login', 'masuk', 'create an account')):
                continue
            if not self._dismissed_login:
                for button in dialog.find_elements(By.CSS_SELECTOR,
                        'button[aria-label="Close"], button[aria-label="close"], '
                        'button[aria-label="Dismiss"], button[aria-label="Tutup"], '
                        'button[data-testid="close-button"]'):
                    if button.is_displayed() and button.is_enabled():
                        button.click()
                        self._dismissed_login = True
                        WebDriverWait(driver, self.request.timeout).until(EC.invisibility_of_element(dialog))
                        return
            raise CrawlProblem('login_required', 'Indeed sign-in dialog prevents reading public details')

    @staticmethod
    def _listing_key(url):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        query.pop('vjk', None)
        return parts.scheme, parts.hostname, parts.path, sorted(query.items())

    def open_detail(self, driver, ref):
        # Use the public card interaction and its search-page panel. Do not force
        # /viewjob navigation, which can require authentication for anonymous users.
        problem = access_problem(driver)
        if problem:
            raise problem
        source = urlsplit(ref.discovered_from)
        if source.scheme != 'https' or source.hostname != 'id.indeed.com' or source.path != '/jobs':
            raise CrawlProblem('detail_unavailable', 'Indeed reference has no supported public search context')
        self._expected_key = ref.key
        self._dismissed_login = False
        self._previous_panel_id = self._previous_description = None
        if self._listing_key(driver.current_url) != self._listing_key(ref.discovered_from):
            driver.get(ref.discovered_from)
        problem = access_problem(driver)
        if problem:
            raise problem
        self._optional_login(driver)
        current = self.reference(driver.current_url, '', '', ref.search_page)
        panel = self._panel(driver)
        if current is not None and current.key == ref.key and panel is not None:
            if self.read_description(driver, panel, ref):
                return
        if panel is not None:
            self._previous_panel_id = panel.id
            self._previous_description = self.read_description(driver, panel, ref)
        for link in self.card_links(driver):
            candidate = self.reference_from_link(link, driver.current_url, ref.search_page)
            if candidate is not None and candidate.key == ref.key:
                try:
                    link.click()
                except ElementClickInterceptedException:
                    dismissed_before = self._dismissed_login
                    self._optional_login(driver)
                    if self._dismissed_login and not dismissed_before:
                        link.click()  # One retry after a dismissible sign-in prompt.
                    else:
                        raise
                return
        raise CrawlProblem('detail_unavailable', 'Observed Indeed card is no longer present on its search page')

    def detail_context(self, driver, ref):
        if super().detail_context(driver, ref) is None:
            return None
        if urlsplit(driver.current_url).path != '/jobs':
            return driver  # Standalone public detail pages can still be parsed.
        self._optional_login(driver)
        panel = self._panel(driver)
        if panel is None:
            return None
        try:
            marker = panel.get_attribute('data-jk') or panel.get_attribute('data-jobkey')
            if marker:
                return panel if marker == ref.external_id else None
            title = self.read_title(panel, ref)
            if not ref.title or ' '.join((title or '').casefold().split()) != ' '.join(ref.title.casefold().split()):
                return None
            if (self._expected_key == ref.key and self._previous_description is not None
                    and panel.id == self._previous_panel_id
                    and self.read_description(driver, panel, ref) == self._previous_description):
                return None  # Same-title cards must not reuse the previous card's text.
        except StaleElementReferenceException:
            return None
        return panel
