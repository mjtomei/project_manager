"""Tests for pm_core.cli._session_target.resolve_target_session."""

from __future__ import annotations

import pytest

from pm_core.cli import _session_target


def test_explicit_flag_wins(monkeypatch):
    monkeypatch.setenv("PM_SESSION", "pm-from-env")
    monkeypatch.setattr(_session_target.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(_session_target.tmux_mod, "session_exists",
                         lambda s: s == "pm-explicit")

    assert _session_target.resolve_target_session("pm-explicit") == "pm-explicit"


def test_falls_back_to_env_then_tmux(monkeypatch):
    monkeypatch.setenv("PM_SESSION", "pm-from-env")
    monkeypatch.setattr(_session_target.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(_session_target.tmux_mod, "session_exists",
                         lambda s: s == "pm-from-env")

    assert _session_target.resolve_target_session(None) == "pm-from-env"


def test_falls_back_to_in_tmux_detection(monkeypatch):
    monkeypatch.delenv("PM_SESSION", raising=False)
    monkeypatch.setattr(_session_target, "_get_pm_session",
                         lambda: "pm-detected")
    monkeypatch.setattr(_session_target.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(_session_target.tmux_mod, "session_exists",
                         lambda s: s == "pm-detected")

    assert _session_target.resolve_target_session(None) == "pm-detected"


def test_errors_when_nothing_resolves(monkeypatch):
    monkeypatch.delenv("PM_SESSION", raising=False)
    monkeypatch.setattr(_session_target, "_get_pm_session", lambda: None)

    with pytest.raises(SystemExit) as e:
        _session_target.resolve_target_session(None)
    assert e.value.code == 1


def test_errors_when_session_does_not_exist(monkeypatch):
    monkeypatch.setattr(_session_target.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(_session_target.tmux_mod, "session_exists",
                         lambda s: False)

    with pytest.raises(SystemExit) as e:
        _session_target.resolve_target_session("pm-nope")
    assert e.value.code == 1


def test_session_tag_strips_pm_prefix():
    assert _session_target.session_tag_from_name("pm-foo") == "foo"
    assert _session_target.session_tag_from_name("foo") == "foo"
