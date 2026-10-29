"""The TUI names its IPC files after its own pm session, not a grouped view (S118)."""

import shutil
import subprocess
import time

import pytest

from pm_core.tui.app import current_session_name

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
    monkeypatch.setenv("TMUX", "/x,1,0")
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
    assert current_session_name() == "pm-proj-abc"


def test_pm_tilde_group_and_plain_session(tmux_server, monkeypatch):
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    _tui_pane(t, "pm-proj-abc", monkeypatch)
    assert current_session_name() == "pm-proj-abc"
    time.sleep(1.1)
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "pm-proj-abc~1")
    assert current_session_name() == "pm-proj-abc"


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


def test_registry_session_of_a_grouped_view_is_the_pm_session(tmux_server, monkeypatch):
    """S121: hooks and popups get the view's name (``#{session_name}``) while
    its client acted last.  The popups' registry check and the pane-opened
    hook must use the pm session, not ``~/.pm/pane-registry/<view>.json``."""
    from pm_core.pane_registry import pm_session_name
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "myview")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "pm-proj-abc~2")
    t("new-session", "-d", "-s", "scratch", "sleep 60")
    t("new-session", "-d", "-t", "scratch", "-s", "other")
    assert pm_session_name("myview") == "pm-proj-abc"
    assert pm_session_name("pm-proj-abc~2") == "pm-proj-abc"
    assert pm_session_name("pm-proj-abc") == "pm-proj-abc"
    assert pm_session_name("other") == "other"
    assert pm_session_name("scratch") == "scratch"
    assert pm_session_name("gone") == "gone"


def test_pane_opened_from_a_grouped_view_marks_the_pm_registry(tmux_server, monkeypatch, tmp_path):
    from click.testing import CliRunner
    from pm_core import pane_registry
    from pm_core.cli import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "myview")
    import json
    pane_registry.registry_path("pm-proj-abc").write_text(
        json.dumps({"session": "pm-proj-abc", "windows": {}}))
    r = CliRunner().invoke(cli, ["_pane-opened", "myview", "@7", "%9"])
    assert r.exit_code == 0, r.output
    assert not (pane_registry.registry_dir() / "myview.json").exists()
    data = pane_registry.load_registry("pm-proj-abc")
    assert data["windows"]["@7"]["user_modified"] is True


def test_views_named_like_pm_or_with_tilde_resolve_through_their_group(tmux_server, monkeypatch):
    """S124: a view named ``pm-laptop`` or ``my~view`` is still a view of the
    pm session it is grouped with; an ungrouped ``pm-*`` session is itself."""
    from pm_core.cli.helpers import _get_current_pm_session
    from pm_core.pane_registry import pm_session_name
    t = tmux_server
    t("new-session", "-d", "-s", "pm-proj-abc", "sleep 60")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "pm-laptop")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", "my~view")
    t("new-session", "-d", "-s", "pm-solo", "sleep 60")
    assert pm_session_name("pm-laptop") == "pm-proj-abc"
    assert pm_session_name("my~view") == "pm-proj-abc"
    assert pm_session_name("pm-solo") == "pm-solo"
    monkeypatch.setenv("TMUX", "/x,1,0")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    for view in ("pm-laptop", "my~view"):
        monkeypatch.setenv("PM_POPUP_SESSION", view)
        assert _get_current_pm_session() == "pm-proj-abc"


def _view_registry(t, tmp_path, monkeypatch, view):
    """pm-proj-abc with a two-pane window registered, plus a grouped *view*
    that is the session pm sees (PM_POPUP_SESSION, as from a key binding)."""
    import json
    from pm_core import pane_registry
    monkeypatch.setenv("HOME", str(tmp_path))
    t("new-session", "-d", "-s", "pm-proj-abc", "-x", "120", "-y", "40", "sleep 60")
    keep = t("list-panes", "-t", "=pm-proj-abc:", "-F", "#{pane_id}")
    gone = t("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", keep, "sleep 60")
    wid = t("display-message", "-p", "-t", keep, "#{window_id}")
    t("new-session", "-d", "-t", "pm-proj-abc", "-s", view)
    pane_registry.registry_path("pm-proj-abc").write_text(json.dumps({
        "session": "pm-proj-abc", "windows": {wid: {"panes": [
            {"id": keep, "role": "review-claude", "order": 0, "cmd": "x"},
            {"id": gone, "role": "review-diff", "order": 1, "cmd": "y"}],
            "user_modified": False}}}))
    monkeypatch.setenv("TMUX", "/x,1,0")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("PM_POPUP_SESSION", view)
    return wid, keep, gone


@pytest.mark.parametrize("view", ["myview", "pm-laptop", "my~view"])
def test_pane_closed_from_a_grouped_view_updates_the_pm_registry(
        tmux_server, monkeypatch, tmp_path, view):
    """S124: the after-kill-pane hook names the view; the closed pane must
    leave the pm session's registry, with no ``<view>.json``."""
    from click.testing import CliRunner
    from pm_core import pane_registry
    from pm_core.cli import cli
    wid, keep, gone = _view_registry(tmux_server, tmp_path, monkeypatch, view)
    tmux_server("kill-pane", "-t", gone)
    r = CliRunner().invoke(cli, ["_pane-closed"])
    assert r.exit_code == 0, r.output
    data = pane_registry.load_registry("pm-proj-abc")
    assert [p["id"] for p in data["windows"][wid]["panes"]] == [keep]
    assert sorted(p.name for p in pane_registry.registry_dir().glob("*.json")) == [
        "pm-proj-abc.json"]


@pytest.mark.parametrize("view", ["myview", "pm-laptop", "my~view"])
def test_rebalance_from_a_grouped_view_uses_the_pm_registry(
        tmux_server, monkeypatch, tmp_path, view):
    """S124: prefix+R (``pm rebalance``) from a view rebalances the pm
    session's registered window instead of failing on ``<view>.json``."""
    from click.testing import CliRunner
    from pm_core import pane_registry
    from pm_core.cli import cli
    wid, _, _ = _view_registry(tmux_server, tmp_path, monkeypatch, view)
    r = CliRunner().invoke(cli, ["rebalance"])
    assert r.exit_code == 0, r.output
    assert "Layout rebalanced." in r.output
    assert not (pane_registry.registry_dir() / f"{view}.json").exists()
