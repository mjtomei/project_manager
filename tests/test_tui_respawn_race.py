"""The killed-TUI respawn hook and a ``pm session`` attach (QA scenario 42).

When the user kills the TUI pane, the ``after-kill-pane`` hook
(``pm _pane-closed``) respawns it; a ``pm session`` attach checks for the
TUI at the same moment.  QA S42 found three defects on a live tmux 3.2a:

* the respawned TUI started in the cwd of the client that ran
  ``kill-pane`` — another project's directory gave this session a TUI for
  *that* project, and a directory outside any project started the guide;
* both processes saw no TUI and each split one (two TUIs until the
  loser's pidfile refusal and its traceback), also on master;
* the attach adopted the hook's new pane before the hook registered it,
  and the hook then listed it a second time (this branch only).

These run on a disposable tmux server with a stand-in ``pm`` first on
PATH, so a ``pm _tui`` pane is a ``sleep`` that tmux still reports with the
``pm _tui`` start command.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_core import pane_layout, pane_registry
from pm_core import tmux as tmux_mod

needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None,
                                reason="needs tmux")

SESSION = "pm-qa it's_tui-abc"


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A private tmux server whose ``pm`` is a stand-in that sleeps."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "pm"
    # Exits at once while $HOME/stub-exit exists (a TUI that has exited).
    stub.write_text('#!/bin/sh\n[ -e "$HOME/stub-exit" ] && exit 0\n'
                    'exec sleep 300\n')
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    sock = str(tmp_path / "s.sock")
    monkeypatch.setenv("PM_TMUX_SOCKET", sock)
    for var in ("TMUX", "TMUX_PANE", "PM_SHARE_MODE"):
        monkeypatch.delenv(var, raising=False)
    # rebalance is layout work on a real client size; not under test here.
    monkeypatch.setattr(pane_layout, "rebalance", lambda s, w: None)

    def t(*args):
        return subprocess.run(["tmux", "-S", sock, *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    yield t
    subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)


def _start(t, tmp_path):
    """Session with TUI + notes, started in the project directory."""
    project = tmp_path / "qa it's # proj"
    project.mkdir()
    t("new-session", "-d", "-s", SESSION, "-n", "main", "-x", "200", "-y",
      "50", "-c", tmux_mod.format_literal(str(project)),
      f"PM_TMUX_SOCKET={os.environ['PM_TMUX_SOCKET']} pm _tui")
    tui = t("list-panes", "-t", f"={SESSION}:", "-F", "#{pane_id}")
    window = t("display-message", "-p", "-t", tui, "#{window_id}")
    notes = t("split-window", "-d", "-h", "-t", tui, "-P", "-F",
              "#{pane_id}", "sleep 300")
    pane_registry.registry_dir().mkdir(parents=True, exist_ok=True)
    pane_registry.registry_path(SESSION).write_text(json.dumps({
        "session": SESSION, "generation": "", "windows": {window: {
            "user_modified": False, "panes": [
                {"id": tui, "role": "tui", "order": 0, "cmd": "pm _tui"},
                {"id": notes, "role": "notes", "order": 1, "cmd": "x"}]}}}))
    return project, window, tui, notes


def _tui_panes(t):
    """Live panes of SESSION whose start command runs ``pm _tui``."""
    from pm_core.cli.helpers import _start_command_is_tui
    out = t("list-panes", "-s", "-t", f"={SESSION}", "-F",
            "#{pane_id} #{pane_dead} #{pane_start_command}")
    panes = [line.split(" ", 2) for line in out.splitlines()]
    return [p[0] for p in panes
            if len(p) == 3 and p[1] == "0" and _start_command_is_tui(p[2])]


def _registered_tuis():
    data = pane_registry.load_registry(SESSION)
    return [p["id"] for _, p in pane_registry._iter_all_panes(data)
            if p["role"] == "tui"]


@needs_tmux
class TestRespawnStartsInTheSessionDirectory:

    def test_a_kill_from_another_directory_respawns_in_the_project(
            self, server, tmp_path, monkeypatch):
        """The hook runs for the client that killed the pane; without
        ``-c`` tmux started the TUI in that client's cwd."""
        project, window, tui, notes = _start(server, tmp_path)
        elsewhere = tmp_path / "other-project"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        server("kill-pane", "-t", tui)
        pane_layout._process_registry_pane_closed(
            pane_registry.load_registry(SESSION))
        [new] = _tui_panes(server)
        assert new != tui
        assert server("display-message", "-p", "-t", new,
                      "#{window_id}") == window
        deadline = time.monotonic() + 5
        while server("display-message", "-p", "-t", new,
                     "#{pane_current_path}") != str(project):
            assert time.monotonic() < deadline, server(
                "display-message", "-p", "-t", new, "#{pane_current_path}")
            time.sleep(0.05)
        assert _registered_tuis() == [new]

    def test_a_new_window_respawn_also_starts_in_the_project(
            self, server, tmp_path, monkeypatch):
        """The TUI was the window's last pane: the new window gets the
        session's directory too."""
        project, window, tui, notes = _start(server, tmp_path)
        server("kill-pane", "-t", notes)
        server("new-window", "-d", "-t", f"={SESSION}:", "sleep 300")
        monkeypatch.chdir(tmp_path)
        server("kill-pane", "-t", tui)
        pane_layout._process_registry_pane_closed(
            pane_registry.load_registry(SESSION))
        [new] = _tui_panes(server)
        deadline = time.monotonic() + 5
        while server("display-message", "-p", "-t", new,
                     "#{pane_current_path}") != str(project):
            assert time.monotonic() < deadline
            time.sleep(0.05)


@needs_tmux
class TestHookAndAttachStartOneTui:
    """Whichever of the two decides second sees the first one's TUI."""

    def test_attach_first_then_hook_does_not_respawn_again(
            self, server, tmp_path, monkeypatch, capsys):
        from pm_core.cli import session as session_mod
        project, window, tui, notes = _start(server, tmp_path)
        before = pane_registry.load_registry(SESSION)  # what the hook read
        server("kill-pane", "-t", tui)
        # The attach decides first: the registry still lists the killed
        # pane, nothing runs the TUI, so it respawns one.
        with pane_registry.tui_respawn_lock(SESSION):
            assert session_mod._ensure_tui_running(SESSION) == window
        assert "TUI pane missing — respawning..." in capsys.readouterr().out
        [attach_tui] = _tui_panes(server)
        # Then the hook: the killed TUI is reconciled away, and the one the
        # attach started is left alone.
        log = MagicMock()
        monkeypatch.setattr(pane_layout, "_logger", log)
        pane_layout._process_registry_pane_closed(before)
        assert _tui_panes(server) == [attach_tui]
        assert _registered_tuis() == [attach_tui]
        assert any("already running; not respawning" in c.args[0]
                   for c in log.info.call_args_list)

    def test_hook_first_then_attach_finds_the_tui(
            self, server, tmp_path, monkeypatch, capsys):
        from pm_core.cli import session as session_mod
        project, window, tui, notes = _start(server, tmp_path)
        server("kill-pane", "-t", tui)
        pane_layout._process_registry_pane_closed(
            pane_registry.load_registry(SESSION))
        [hook_tui] = _tui_panes(server)
        with pane_registry.tui_respawn_lock(SESSION):
            assert session_mod._ensure_tui_running(SESSION) is None
        assert "TUI pane missing" not in capsys.readouterr().out
        assert _tui_panes(server) == [hook_tui]
        assert _registered_tuis() == [hook_tui]

    def test_a_pane_already_listed_is_not_listed_twice(
            self, server, tmp_path, monkeypatch):
        """An attach without the lock (or the TUI's own heal) may record
        the new pane before the respawn does: it is listed once."""
        project, window, tui, notes = _start(server, tmp_path)
        real_split = tmux_mod.split_pane

        def split_then_adopt(*args, **kwargs):
            pane = real_split(*args, **kwargs)
            pane_registry.locked_read_modify_write(
                pane_registry.registry_path(SESSION),
                lambda raw: (pane_registry.register_tui_pane(
                    raw, window, pane), raw)[1])
            return pane

        monkeypatch.setattr(tmux_mod, "split_pane", split_then_adopt)
        server("kill-pane", "-t", tui)
        pane_layout._process_registry_pane_closed(
            pane_registry.load_registry(SESSION))
        [new] = _tui_panes(server)
        assert _registered_tuis() == [new]


class TestTuiRespawnLock:

    def test_a_second_holder_waits_for_the_first(self, tmp_path,
                                                 monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        released = threading.Event()
        taken = threading.Event()

        def first():
            with pane_registry.tui_respawn_lock(SESSION) as locked:
                assert locked
                taken.set()
                time.sleep(0.3)
                released.set()

        th = threading.Thread(target=first)
        th.start()
        assert taken.wait(5)
        with pane_registry.tui_respawn_lock(SESSION, timeout=5) as locked:
            assert locked
            assert released.is_set()
        th.join()

    def test_a_held_lock_times_out_and_the_caller_goes_ahead(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        log = MagicMock()
        monkeypatch.setattr(pane_registry, "_logger", log)
        with pane_registry.tui_respawn_lock(SESSION):
            start = time.monotonic()
            with pane_registry.tui_respawn_lock(SESSION,
                                                timeout=0.2) as locked:
                assert locked is False
            assert time.monotonic() - start >= 0.2
        log.warning.assert_called_once()
        # The registry's own lock is a different file: not blocked.
        with pane_registry.tui_respawn_lock(SESSION):
            pane_registry.locked_read_modify_write(
                pane_registry.registry_path(SESSION), lambda raw: {"a": 1},
                timeout=0.2)

    def test_an_unopenable_lock_file_goes_ahead(self, tmp_path,
                                                monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        reg = pane_registry.registry_dir()
        reg.mkdir(parents=True, exist_ok=True)
        (reg / f"{SESSION}.json.respawn.lock").mkdir()  # open() fails
        with pane_registry.tui_respawn_lock(SESSION) as locked:
            assert locked is False


class TestSessionStartDecidesUnderTheLock:

    def test_ensure_tui_running_is_called_with_the_lock_held(
            self, monkeypatch):
        """``_session_start``'s TUI check runs inside the respawn lock and
        rebalances outside it."""
        from pm_core.cli import session as session_mod
        events = []

        class Lock:
            def __init__(self, name):
                events.append(("lock", name))

            def __enter__(self):
                events.append("enter")
                return True

            def __exit__(self, *exc):
                events.append("exit")

        monkeypatch.setattr(pane_registry, "tui_respawn_lock", Lock)
        monkeypatch.setattr(session_mod, "_ensure_tui_running",
                            lambda s: events.append(("ensure", s)) or "@4")
        monkeypatch.setattr(pane_layout, "rebalance",
                            lambda s, w: events.append(("rebalance", s, w)))

        class Stop(Exception):
            pass

        def stop(*a, **k):
            raise Stop

        monkeypatch.setattr(session_mod, "_register_tmux_bindings", stop)
        monkeypatch.setattr(session_mod, "_resolve_start_session_name",
                            lambda shared: "pm-x")
        monkeypatch.setattr(session_mod, "_resolve_session_socket",
                            lambda n, shared: ("/tmp/none", False))
        exists = iter([True, True])
        monkeypatch.setattr(session_mod.tmux_mod, "session_exists",
                            lambda *a, **k: next(exists))
        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        from pm_core import hook_install
        monkeypatch.setattr(hook_install, "ensure_hooks_installed",
                            lambda: None)
        monkeypatch.setattr(session_mod, "state_root",
                            MagicMock(side_effect=FileNotFoundError()))
        with pytest.raises(Stop):
            session_mod._session_start()
        assert events == [("lock", "pm-x"), "enter", ("ensure", "pm-x"),
                          "exit", ("rebalance", "pm-x", "@4")]


@needs_tmux
class TestFindRunningTuiPane:

    def test_dead_and_other_session_tui_panes_are_not_running_tuis(
            self, server, tmp_path):
        from pm_core.cli.helpers import _find_running_tui_pane
        project, window, tui, notes = _start(server, tmp_path)
        assert _find_running_tui_pane(SESSION) == (tui, window)
        # Another session on the same server running a TUI does not count.
        server("new-session", "-d", "-s", "pm-other", "pm _tui")
        # A TUI pane that has exited (kept by remain-on-exit) is not one.
        server("set-option", "-w", "-t", f"={SESSION}:", "remain-on-exit",
               "on")
        (Path(os.environ["HOME"]) / "stub-exit").touch()
        server("respawn-pane", "-k", "-t", tui, "pm _tui")
        assert server("display-message", "-p", "-t", tui,
                      "#{pane_start_command}") == '"pm _tui"'
        deadline = time.monotonic() + 5
        while server("display-message", "-p", "-t", tui,
                     "#{pane_dead}") != "1":
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert _find_running_tui_pane(SESSION) is None
        assert _find_running_tui_pane("pm-other") is not None
        (Path(os.environ["HOME"]) / "stub-exit").unlink()


class TestHookDecidesUnderTheLock:

    def test_reconcile_and_respawn_run_with_the_lock_held(self,
                                                          monkeypatch):
        """The hook's "TUI gone, none running, start one" is one step
        under the lock ``pm session`` also takes; rebalance runs after."""
        events = []

        class Lock:
            def __init__(self, name):
                events.append(("lock", name))

            def __enter__(self):
                events.append("enter")
                return True

            def __exit__(self, *exc):
                events.append("exit")

        monkeypatch.setattr(pane_registry, "tui_respawn_lock", Lock)
        monkeypatch.setattr(pane_layout, "_reconcile_registry",
                            lambda s, w: events.append("reconcile") or ["%0"])
        monkeypatch.setattr(pane_layout, "_running_tui_pane",
                            lambda s: events.append("running?") or None)
        monkeypatch.setattr(pane_layout, "_respawn_tui",
                            lambda s, w: events.append("respawn") or w)
        monkeypatch.setattr(pane_layout, "rebalance",
                            lambda s, w: events.append("rebalance"))
        pane_layout._process_registry_pane_closed({
            "session": "pm-x", "windows": {"@0": {"panes": [
                {"id": "%0", "role": "tui", "order": 0, "cmd": "pm _tui"}]}}})
        assert events == [("lock", "pm-x"), "enter", "reconcile",
                          "running?", "respawn", "exit", "rebalance"]
