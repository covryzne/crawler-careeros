import json
from datetime import datetime
from pathlib import Path

import pytest

from src.crawler.adapters.base import CrawlProblem
from src.crawler.artifacts import capture_failure
from src.crawler.models import CrawlRequest, JobReference
from src.crawler.runner import ADAPTERS, run


class Driver:
    current_url = 'https://id.jobstreet.com/id/ai-engineer-jobs?token=private#private'
    title = 'Just a moment...'
    closed = False

    def find_elements(self, *args):
        return []

    def save_screenshot(self, path):
        assert not self.closed, 'Capture must happen before browser cleanup'
        Path(path).write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-image')
        return True

    def quit(self):
        self.closed = True


class ListingBlocked:
    def __init__(self, request):
        pass

    def advance(self, *args):
        raise CrawlProblem('challenge_blocked', 'Portal requires verification')


class DetailBlocked(ListingBlocked):
    details_per_page = True

    def advance(self, driver, page, seen):
        return [JobReference('jobstreet', '123', 'https://id.jobstreet.com/id/job/123',
                             'Fixture', driver.current_url, page)]

    def open_detail(self, driver, ref):
        driver.current_url = ref.url

    def extract(self, *args):
        raise CrawlProblem('challenge_blocked', 'Detail requires verification')


@pytest.mark.parametrize('adapter,phase', [(ListingBlocked, 'listing'), (DetailBlocked, 'detail')])
def test_challenge_captures_before_quit_and_checkpoints_metadata(tmp_path, monkeypatch, adapter, phase):
    monkeypatch.setitem(ADAPTERS, 'jobstreet', adapter)
    driver = Driver()
    result = run(CrawlRequest(keyword='AI Engineer', portals=('jobstreet',), delay=0,
                             headless=False, max_pages=1), tmp_path, lambda _: driver)
    root = tmp_path / result['run_id']
    saved = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    error = next(error for error in saved['errors'] if error['phase'] == phase)
    artifacts = error['failure_artifacts']
    assert driver.closed
    assert error.get('status', error.get('state')) == 'challenge_blocked'
    assert (root / artifacts['screenshot']).read_bytes().startswith(b'\x89PNG')
    metadata = json.loads((root / artifacts['metadata']).read_text(encoding='utf-8'))
    assert metadata['status'] == 'challenge_blocked'
    assert metadata['phase'] == phase
    assert metadata['page'] == 1
    assert metadata['headless'] is False
    assert metadata['run_id'] == result['run_id']
    assert metadata['page_title'] == 'Just a moment...'
    assert '?' not in metadata['observed_url'] and '#' not in metadata['observed_url']
    assert datetime.fromisoformat(metadata['detected_at']).utcoffset().total_seconds() == 0
    assert metadata['captured_at'] >= metadata['detected_at']
    assert metadata['capture_errors'] == {}
    assert result['sources'][0]['stop_reason'] == 'challenge_blocked'


@pytest.mark.parametrize('failure', ['raise', 'false'])
def test_screenshot_failure_preserves_original_crawl_outcome(tmp_path, monkeypatch, failure):
    monkeypatch.setitem(ADAPTERS, 'jobstreet', ListingBlocked)
    driver = Driver()

    def fail(path):
        if failure == 'raise':
            raise OSError('sensitive browser internals')
        return False

    driver.save_screenshot = fail
    result = run(CrawlRequest(keyword='AI Engineer', portals=('jobstreet',), delay=0),
                 tmp_path, lambda _: driver)
    artifacts = result['errors'][0]['failure_artifacts']
    assert driver.closed
    assert result['sources'][0]['stop_reason'] == 'challenge_blocked'
    assert artifacts['screenshot'] is None
    text = (tmp_path / result['run_id'] / artifacts['metadata']).read_text(encoding='utf-8')
    assert 'sensitive browser internals' not in text
    assert json.loads(text)['capture_errors']['screenshot'] in {'OSError', 'ScreenshotNotSaved'}


def test_no_browser_and_storage_failure_are_nonfatal(tmp_path):
    context = {'portal': 'jobstreet', 'phase': 'listing', 'status': 'browser_start_failed',
               'headless': False, 'run_id': 'fixture-run'}
    artifact = capture_failure(None, tmp_path, **context)
    metadata = json.loads((tmp_path / artifact['metadata']).read_text(encoding='utf-8'))
    assert metadata['capture_errors']['screenshot'] == 'BrowserUnavailable'
    file = tmp_path / 'not-a-directory'
    file.write_text('fixture')
    failed = capture_failure(None, file, **context)
    assert failed['metadata'] is None
    assert failed['capture_error_type'] in {
        'NotADirectoryError', 'FileNotFoundError', 'FileExistsError'
    }
