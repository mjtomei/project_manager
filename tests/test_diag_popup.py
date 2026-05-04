"""Tests for the window-attached diag popup state map."""

from unittest.mock import patch

from pm_core import diag_popup


def test_diag_session_name_strips_at_prefix():
    assert diag_popup.diag_session_name("pm-foo", "@7") == "pm-foo-diag-7"
    assert diag_popup.diag_session_name("pm-foo~1", "@42") == "pm-foo-diag-42"


def test_session_tag_from_pm_session():
    assert diag_popup.session_tag_from_pm_session("pm-myrepo-abc123") == "myrepo-abc123"
    assert diag_popup.session_tag_from_pm_session("pm-myrepo-abc123~2") == "myrepo-abc123"
    assert diag_popup.session_tag_from_pm_session("custom-name") is None


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    diag_popup.record_diag_session("mytag", "@7", "pm-foo-diag-7")
    diag_popup.record_diag_session("mytag", "@8", "pm-foo-diag-8")
    state = diag_popup._load_state("mytag")
    assert state == {
        "@7": {"name": "pm-foo-diag-7"},
        "@8": {"name": "pm-foo-diag-8"},
    }

    # forget removes the entry and returns the recorded name
    name = diag_popup.forget_diag_session("mytag", "@7")
    assert name == "pm-foo-diag-7"
    state = diag_popup._load_state("mytag")
    assert state == {"@8": {"name": "pm-foo-diag-8"}}

    # forgetting an unknown window-id is a no-op
    assert diag_popup.forget_diag_session("mytag", "@nonexistent") is None


def test_kill_diag_session_for_window_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Record state, then simulate cleanup. session_exists returns False so
    # kill_session is not invoked, but state-map cleanup still runs.
    diag_popup.record_diag_session("mytag", "@9", "pm-mytag-diag-9")
    with patch("pm_core.tmux.session_exists", return_value=False) as se, \
         patch("pm_core.tmux.kill_session") as ks:
        diag_popup.kill_diag_session_for_window("pm-mytag", "@9")
    se.assert_called_once_with("pm-mytag-diag-9")
    ks.assert_not_called()
    assert "@9" not in diag_popup._load_state("mytag")


def test_kill_diag_session_for_window_kills_when_alive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    diag_popup.record_diag_session("mytag", "@10", "pm-mytag-diag-10")
    with patch("pm_core.tmux.session_exists", return_value=True), \
         patch("pm_core.tmux.kill_session") as ks:
        diag_popup.kill_diag_session_for_window("pm-mytag", "@10")
    ks.assert_called_once_with("pm-mytag-diag-10")
    assert "@10" not in diag_popup._load_state("mytag")


def test_resolve_host_cwd_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # No persisted pm_root for "missing-tag" → falls back to $HOME.
    cwd = diag_popup.resolve_host_cwd("missing-tag")
    assert cwd == str(tmp_path)


def test_ensure_diag_session_reuses_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("pm_core.tmux.session_exists", return_value=True) as se, \
         patch("pm_core.tmux.create_session") as cs:
        name = diag_popup.ensure_diag_session("pm-foo-abc", "@5")
    assert name == "pm-foo-abc-diag-5"
    se.assert_called_once_with("pm-foo-abc-diag-5")
    cs.assert_not_called()
