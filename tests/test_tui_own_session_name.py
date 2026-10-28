"""The TUI names its IPC files after its own pm session, not a grouped view (S118)."""

import shutil
import subprocess
import time

import pytest

from pm_core.tui.app import _own_session_name

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")


@pytest.fixture
def tmux_server(tmp_path, monkeypatch):
    sock = str(tmp_path / "tmux.sock")
    monkeypatch.setenv("PM_TMUX_SOCKET", sock)

    def t(*args):
        return subprocess.run(["tmux", "-S", sock, *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    yield t
    subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)


def _tui_pane(t, session, monkeypatch):
    pane = t("list-panes", "-t", f"={session}:", "-F", "#{pane_id}").split()[0]
    monkeypatch.setenv("TMUX_PANE", pane)
    return pane


def test_grouped_view_session_does_not_rename_the_tui(tmux_server, monkeypatch):
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    pane = _tui_pane(t, "pm-proj-abc", monkeypatch)
    time.sleep(1.1)  # the view becomes the most recently active session
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "v118")
    # Precondition: tmux itself names the view for the TUI's pane.
    assert t("display-message", "-p", "-t", pane, "#{session_name}") == "v118"
    assert _own_session_name() == "pm-proj-abc"


def test_pm_tilde_group_and_plain_session(tmux_server, monkeypatch):
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    _tui_pane(t, "pm-proj-abc", monkeypatch)
    assert _own_session_name() == "pm-proj-abc"
    time.sleep(1.1)
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "pm-proj-abc~1")
    assert _own_session_name() == "pm-proj-abc"


def test_popup_from_grouped_view_resolves_the_pm_session(tmux_server, monkeypatch):
    """A popup opened from the view gets PM_POPUP_SESSION=<view>; pm commands
    there (picker badges, runtime records) must still use the pm session."""
    from pm_core.cli.helpers import _get_current_pm_session
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "v118")
    monkeypatch.setenv("TMUX", "/x,1,0")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("PM_POPUP_SESSION", "v118")
    assert _get_current_pm_session() == "pm-proj-abc"
    t("new-session", "-d", "-s", "other", "sleep 60")
    monkeypatch.setenv("PM_POPUP_SESSION", "other")
    assert _get_current_pm_session() is None
