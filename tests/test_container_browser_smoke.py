"""Smoke request compatibility and repeated browser cleanup using fixture drivers."""

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "mode,headless",
    [("headed", [False, False]), ("headless", [True, True]), ("auto", [False, True])],
)
def test_smoke_uses_complete_requests_and_closes_each_session(
    monkeypatch, capsys, mode, headless
):
    path = Path(__file__).resolve().parents[1] / "docker/browser_smoke.py"
    spec = importlib.util.spec_from_file_location("container_browser_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("CRAWLER_BROWSER_MODE", mode)
    events = []

    class Browser:
        title = "CareerOS browser check"

        def __init__(self, request):
            assert (
                request.indeed_user_data_dir is None
            )  # The old namespace lacked this field.
            assert request.headless == headless[len(events) // 3]
            self.headless = request.headless
            events.append("open")

        def __enter__(self):
            return self

        def get(self, url):
            assert url.startswith("data:")
            events.append("navigate")

        def execute_cdp_cmd(self, command, parameters):
            return {"arguments": ["--headless=new"] if self.headless else []}

        def __exit__(self, *args):
            events.append("close")

    monkeypatch.setattr(module, "create_driver", Browser)
    module.main()
    assert events == ["open", "navigate", "close"] * 2
    assert f"Browser smoke passed: mode={mode}, sessions=2" in capsys.readouterr().out
