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


@pytest.mark.parametrize(
    "mode,display", [("headless", False), ("headed", True), ("auto", True)]
)
def test_worker_exec_uses_display_only_when_needed(
    entrypoint, monkeypatch, mode, display
):
    monkeypatch.setenv("CRAWLER_BROWSER_MODE", mode)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        ["entrypoint.py", "/opt/backend/bin/python", "-m", "app.crawler.worker"],
    )
    launched = []
    monkeypatch.setattr(
        entrypoint, "start_display", lambda: monkeypatch.setenv("DISPLAY", ":91")
    )
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
    assert "-noreset" in started[0]


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


def test_xvfb_keeps_pipe_open_for_separate_newline_write(entrypoint, monkeypatch):
    """Reproduce Xorg's two write() calls; old startup closed before the newline."""
    monkeypatch.delenv("DISPLAY", raising=False)
    writers = []
    waits = []

    def popen(args, *, pass_fds):
        writer = os.dup(pass_fds[0])
        writers.append(writer)
        os.write(writer, b"91")
        return SimpleNamespace(poll=lambda: None)

    def readable(read, _, __, timeout):
        waits.append(timeout)
        if len(waits) == 2:
            assert "DISPLAY" not in os.environ
            # This must succeed before the reader closes its end of the pipe.
            os.write(writers[0], b"\n")
        return read, [], []

    monkeypatch.setattr(entrypoint.subprocess, "Popen", popen)
    monkeypatch.setattr(entrypoint.select, "select", readable)
    try:
        entrypoint.start_display()
        assert len(waits) == 2
        assert waits[1] <= waits[0]  # One deadline for the complete reply.
        assert os.environ["DISPLAY"] == ":91"
    finally:
        for writer in writers:
            os.close(writer)


@pytest.mark.parametrize("reply", [b"91", b"", b"invalid\n", b"-1\n", b"9" * 32])
def test_xvfb_incomplete_or_invalid_reply_cleans_up(entrypoint, monkeypatch, reply):
    monkeypatch.delenv("DISPLAY", raising=False)
    stopped = []

    def popen(args, *, pass_fds):
        if reply:
            os.write(pass_fds[0], reply)
        return SimpleNamespace(
            poll=lambda: None,
            terminate=lambda: stopped.append("terminate"),
            wait=lambda timeout: stopped.append("wait"),
        )

    monkeypatch.setattr(entrypoint.subprocess, "Popen", popen)
    monkeypatch.setattr(entrypoint.select, "select", lambda read, *args: (read, [], []))
    with pytest.raises(RuntimeError):
        entrypoint.start_display()
    assert "DISPLAY" not in os.environ
    assert stopped == ["terminate", "wait"]


def test_xvfb_partial_reply_uses_one_timeout_and_no_worker_exec(
    entrypoint, monkeypatch
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("CRAWLER_BROWSER_MODE", "headed")
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "worker"])
    stopped = []
    executed = []
    clock = iter([100, 100, 115])
    monkeypatch.setattr(entrypoint, "monotonic", lambda: next(clock))

    def popen(args, *, pass_fds):
        os.write(pass_fds[0], b"91")
        return SimpleNamespace(
            poll=lambda: None,
            terminate=lambda: stopped.append("terminate"),
            wait=lambda timeout: stopped.append("wait"),
        )

    monkeypatch.setattr(entrypoint.subprocess, "Popen", popen)
    monkeypatch.setattr(entrypoint.select, "select", lambda read, *args: (read, [], []))
    monkeypatch.setattr(entrypoint.os, "execvpe", lambda *args: executed.append(args))
    with pytest.raises(RuntimeError, match="timed out"):
        entrypoint.main()
    assert executed == []
    assert "DISPLAY" not in os.environ
    assert stopped == ["terminate", "wait"]
