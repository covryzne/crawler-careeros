"""Display readiness and launch behavior without opening Chrome or any network."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def entrypoint():
    path = Path(__file__).resolve().parents[1] / "docker" / "entrypoint.py"
    spec = importlib.util.spec_from_file_location("crawler_container_entrypoint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode,display", [("headless", False), ("headed", True), ("auto", True)])
def test_worker_exec_uses_display_only_when_needed(entrypoint, monkeypatch, mode, display):
    monkeypatch.setenv("CRAWLER_BROWSER_MODE", mode)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        ["entrypoint.py", "/opt/backend/bin/python", "-m", "app.crawler.worker"],
    )
    launched = []
    monkeypatch.setattr(entrypoint, "start_display", lambda: monkeypatch.setenv("DISPLAY", ":91"))
    monkeypatch.setattr(
        entrypoint.os,
        "execvpe",
        lambda command, args, env: launched.append((command, list(args), dict(env))),
    )
    entrypoint.main()
    assert launched[0][0] == "/opt/backend/bin/python"
    assert launched[0][1] == ["/opt/backend/bin/python", "-m", "app.crawler.worker"]
    assert ("DISPLAY" in launched[0][2]) == display


def test_invalid_mode_does_not_launch_worker(entrypoint, monkeypatch):
    monkeypatch.setenv("CRAWLER_BROWSER_MODE", "invalid")
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "worker"])
    with pytest.raises(SystemExit, match="Invalid CRAWLER_BROWSER_MODE"):
        entrypoint.main()


def test_xvfb_readiness_waits_for_displayfd(entrypoint, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    started = []

    def popen(args, *, pass_fds):
        started.append(args)
        os.write(pass_fds[0], b"91\n")
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(entrypoint.subprocess, "Popen", popen)
    monkeypatch.setattr(entrypoint.select, "select", lambda read, *args: (read, [], []))
    entrypoint.start_display()
    assert os.environ["DISPLAY"] == ":91"
    assert started[0][-2:] == ["-nolisten", "tcp"]


def test_xvfb_timeout_cleans_up_and_does_not_set_display(entrypoint, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    stopped = []
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: stopped.append("terminate"),
        wait=lambda timeout: stopped.append("wait"),
    )
    monkeypatch.setattr(entrypoint.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(entrypoint.select, "select", lambda *args: ([], [], []))
    with pytest.raises(RuntimeError, match="timed out"):
        entrypoint.start_display()
    assert stopped == ["terminate", "wait"]
    assert "DISPLAY" not in os.environ
