import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from src.crawler import runner
from src.crawler.cli import main
from src.crawler.models import CrawlRequest


def test_profile_path_is_normalized_and_passed_to_chrome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    profile = tmp_path / 'profile with spaces'
    request = CrawlRequest(keyword='AI', portals=('indeed',), indeed_user_data_dir='profile with spaces')
    chrome = Mock()
    monkeypatch.setattr(runner.webdriver, 'Chrome', chrome)
    runner.create_driver(request)
    assert request.indeed_user_data_dir == str(profile)
    assert profile.is_dir()
    assert f'--user-data-dir={profile}' in chrome.call_args.kwargs['options'].arguments
    chrome.return_value.set_page_load_timeout.assert_called_once_with(20)


def test_no_profile_option_keeps_temporary_chrome(monkeypatch):
    chrome = Mock()
    monkeypatch.setattr(runner.webdriver, 'Chrome', chrome)
    runner.create_driver(CrawlRequest(keyword='AI', portals=('indeed',)))
    assert not any(a.startswith('--user-data-dir') for a in chrome.call_args.kwargs['options'].arguments)


@pytest.mark.parametrize('path', ['', '   ', 123])
def test_profile_rejects_invalid_paths(path):
    with pytest.raises(ValueError, match='directory path'):
        CrawlRequest(keyword='AI', portals=('indeed',), indeed_user_data_dir=path)


def test_profile_requires_indeed():
    with pytest.raises(ValueError, match='requires indeed'):
        CrawlRequest(keyword='AI', portals=('jobstreet',), indeed_user_data_dir='/tmp/profile')


def test_profile_is_used_only_for_indeed_in_mixed_run(tmp_path, monkeypatch):
    requests = []
    for name in ('jobstreet', 'indeed'):
        monkeypatch.setattr(runner.ADAPTERS[name], 'advance', lambda *args: [])

    class Driver:
        current_url = 'about:blank'

        def quit(self):
            pass

    def factory(request):
        requests.append(request)
        return Driver()

    profile = str(tmp_path / 'indeed-profile')
    result = runner.run(CrawlRequest(keyword='AI', portals=('jobstreet', 'indeed'),
                                    delay=0, indeed_user_data_dir=profile), tmp_path / 'runs', factory)
    assert result['state'] == 'completed'
    assert [r.indeed_user_data_dir for r in requests] == [None, profile]
    assert 'browser_profile' not in result['sources'][0]
    assert result['sources'][1]['browser_profile'] == 'persistent'
    assert result['request']['indeed_user_data_dir'] == profile


def test_cli_passes_profile_directory(tmp_path, monkeypatch):
    run = Mock(return_value={'state': 'completed'})
    monkeypatch.setattr(runner, 'run', run)
    main(['--mode', 'selenium', '--portals', 'indeed', '--indeed-user-data-dir', str(tmp_path)])
    assert run.call_args.args[0].indeed_user_data_dir == str(tmp_path)


def test_browser_use_rejects_profile_option(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(['--indeed-user-data-dir', str(tmp_path)])
    assert error.value.code == 2


@pytest.mark.skipif(os.getenv('CRAWLER_BROWSER_TESTS') != '1', reason='Opt-in local Chrome test')
def test_profile_retains_cookie_and_local_storage_across_browser_restarts(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body>Local profile fixture</body></html>')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = CrawlRequest(keyword='AI', portals=('indeed',), headless=True,
                           indeed_user_data_dir=str(tmp_path / 'profile'))
    url = f'http://127.0.0.1:{server.server_port}/'
    try:
        browser = runner.create_driver(request)
        try:
            browser.get(url)
            browser.add_cookie({'name': 'profile_fixture', 'value': 'retained',
                                'expiry': int(time.time()) + 3600})
            browser.execute_script("localStorage.setItem('profile_fixture', 'retained')")
        finally:
            browser.quit()
        browser = runner.create_driver(request)
        try:
            browser.get(url)
            assert browser.get_cookie('profile_fixture')['value'] == 'retained'
            assert browser.execute_script("return localStorage.getItem('profile_fixture')") == 'retained'
        finally:
            browser.quit()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
