"""Tests for shared command-history persistence (popup + TUI bar)."""

from __future__ import annotations

import multiprocessing
import os

import pytest

from pm_core import paths


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_append_and_read_roundtrip(tmp_home):
    paths.append_command_history("pr list", session_tag="t1")
    paths.append_command_history("plan show plan-1", session_tag="t1")
    out = paths.read_command_history(session_tag="t1")
    assert out == ["pr list", "plan show plan-1"]


def test_empty_command_skipped(tmp_home):
    paths.append_command_history("", session_tag="t1")
    paths.append_command_history("   ", session_tag="t1")
    paths.append_command_history("ok", session_tag="t1")
    assert paths.read_command_history(session_tag="t1") == ["ok"]


def test_trim_to_cap(tmp_home, monkeypatch):
    monkeypatch.setattr(paths, "COMMAND_HISTORY_CAP", 5)
    for i in range(20):
        paths.append_command_history(f"c{i}", session_tag="t1")
    out = paths.read_command_history(session_tag="t1")
    assert out == [f"c{i}" for i in range(15, 20)]


def test_read_limit(tmp_home):
    for i in range(10):
        paths.append_command_history(f"c{i}", session_tag="t1")
    out = paths.read_command_history(session_tag="t1", limit=3)
    assert out == ["c7", "c8", "c9"]


def test_missing_file_returns_empty(tmp_home):
    assert paths.read_command_history(session_tag="never") == []


def _writer(home, tag, prefix, n):
    os.environ["HOME"] = home
    # Re-import inside child to pick up env-derived paths.
    from pm_core import paths as p
    for i in range(n):
        p.append_command_history(f"{prefix}{i}", session_tag=tag)


def test_concurrent_appends_no_loss(tmp_home):
    ctx = multiprocessing.get_context("fork")
    procs = [
        ctx.Process(target=_writer, args=(str(tmp_home), "concurrent", f"a{i}-", 25))
        for i in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=10)
        assert p.exitcode == 0
    out = paths.read_command_history(session_tag="concurrent")
    assert len(out) == 4 * 25
