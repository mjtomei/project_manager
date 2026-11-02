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
import shlex
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

    def test_a_lock_error_that_is_not_contention_goes_ahead_at_once(
            self, tmp_path, monkeypatch):
        """Only another holder is worth waiting for.  A filesystem that
        cannot lock at all (``ENOLCK``) would otherwise hold up the hook and
        the attach for the whole timeout on every call."""
        import errno
        import fcntl
        monkeypatch.setenv("HOME", str(tmp_path))
        log = MagicMock()
        monkeypatch.setattr(pane_registry, "_logger", log)

        def no_locks(fd, op):
            raise OSError(errno.ENOLCK, "No locks available")

        monkeypatch.setattr(fcntl, "flock", no_locks)
        start = time.monotonic()
        with pane_registry.tui_respawn_lock(SESSION, timeout=2) as locked:
            assert locked is False
        assert time.monotonic() - start < 1
        log.warning.assert_called_once()
        assert "cannot lock" in log.warning.call_args.args[0]

    def test_an_error_in_the_body_releases_the_lock(self, tmp_path,
                                                    monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        with pytest.raises(RuntimeError):
            with pane_registry.tui_respawn_lock(SESSION) as locked:
                assert locked
                raise RuntimeError("respawn failed")
        with pane_registry.tui_respawn_lock(SESSION, timeout=0.2) as locked:
            assert locked


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


def _attach(session):
    """A real client attached to *session* under a pty, or skip."""
    sock = os.environ["PM_TMUX_SOCKET"]
    proc = subprocess.Popen(
        ["script", "-qec",
         f"tmux -S {shlex.quote(sock)} attach -t {shlex.quote('=' + session)}",
         "/dev/null"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        r = subprocess.run(["tmux", "-S", sock, "list-clients", "-F",
                            "#{client_session}"],
                           capture_output=True, text=True)
        if session in r.stdout.splitlines():
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    proc.kill()
    pytest.skip("could not attach a tmux client in this environment")


@needs_tmux
class TestAttachRespawnLeavesOtherClientsAlone:
    """QA S45: a joiner's ``pm session`` (run outside tmux) found the TUI's
    window gone and respawned it in a new window.  The respawn then selected
    that window through ``select_window``, which outside tmux falls back to
    the first *attached* grouped session — the shared session's owner — so
    the owner was switched off the window they were using."""

    def test_a_new_window_respawn_does_not_switch_an_attached_client(
            self, server, tmp_path):
        from pm_core.cli import session as session_mod
        project, window, tui, notes = _start(server, tmp_path)
        shell = server("new-window", "-d", "-t", f"={SESSION}:", "-P", "-F",
                       "#{window_id}", "sleep 300")
        for n in ("~1", "~2"):
            server("new-session", "-d", "-t", f"={SESSION}",
                   "-s", f"{SESSION}{n}")
            server("select-window", "-t", f"={SESSION}{n}:{shell}")
        owner = _attach(f"{SESSION}~1")
        try:
            server("kill-window", "-t", window)  # the TUI and notes
            with pane_registry.tui_respawn_lock(SESSION):
                new_window = session_mod._ensure_tui_running(SESSION)
            assert new_window not in (None, window)
            assert _tui_panes(server) != []
            assert server("list-clients", "-F",
                          "#{client_session} #{window_id}") == (
                f"{SESSION}~1 {shell}")
        finally:
            owner.kill()


class TestSessionStartSelectsTheRespawnedWindowInItsOwnSession:

    def _run(self, monkeypatch, tmp_path, respawned):
        from contextlib import nullcontext
        from pm_core.cli import session as session_mod
        events = []
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(pane_registry, "tui_respawn_lock",
                            lambda name: nullcontext(True))

        class Stop(Exception):
            pass

        def attach(name, socket_path=None):
            events.append(("attach", name))
            raise Stop

        monkeypatch.setattr(session_mod, "_ensure_tui_running",
                            lambda s: respawned)
        monkeypatch.setattr(pane_layout, "rebalance", lambda s, w: None)
        monkeypatch.setattr(session_mod, "_register_tmux_bindings",
                            lambda s: None)
        monkeypatch.setattr(session_mod, "_schedule_rebalance",
                            lambda s: None)
        monkeypatch.setattr(session_mod, "_resolve_start_session_name",
                            lambda shared: "pm-x")
        monkeypatch.setattr(session_mod, "_resolve_session_socket",
                            lambda n, shared: ("/tmp/none", False))
        exists = iter([True, True])
        monkeypatch.setattr(session_mod.tmux_mod, "session_exists",
                            lambda *a, **k: next(exists))
        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(session_mod.tmux_mod,
                            "find_unattached_grouped_session",
                            lambda *a, **k: "pm-x~2")
        monkeypatch.setattr(
            session_mod.tmux_mod, "select_window_in_session",
            lambda s, w: events.append(("select_in", s, w)) or True)
        monkeypatch.setattr(
            session_mod.tmux_mod, "select_window",
            lambda s, w: events.append(("select", s, w)) or True)
        monkeypatch.setattr(session_mod.tmux_mod, "attach", attach)
        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        from pm_core import hook_install
        monkeypatch.setattr(hook_install, "ensure_hooks_installed",
                            lambda: None)
        monkeypatch.setattr(session_mod, "state_root",
                            MagicMock(side_effect=FileNotFoundError()))
        with pytest.raises(Stop):
            session_mod._session_start()
        return events

    def test_a_respawned_window_is_selected_in_the_attached_session(
            self, monkeypatch, tmp_path):
        assert self._run(monkeypatch, tmp_path, "@4") == [
            ("select_in", "pm-x~2", "@4"), ("attach", "pm-x~2")]

    def test_nothing_is_selected_when_the_tui_was_running(
            self, monkeypatch, tmp_path):
        assert self._run(monkeypatch, tmp_path, None) == [("attach", "pm-x~2")]


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

    def test_one_lock_for_all_windows_rebalances_after(self, monkeypatch):
        """With several registered windows the hook takes the lock once,
        reconciles every window under it, and rebalances after it."""
        events = []

        class Lock:
            def __init__(self, name):
                events.append(("lock", name))

            def __enter__(self):
                events.append("enter")
                return True

            def __exit__(self, *exc):
                events.append("exit")

        removed = {"@0": ["%0"], "@4": [], "@6": ["%9"]}
        monkeypatch.setattr(pane_registry, "tui_respawn_lock", Lock)
        monkeypatch.setattr(pane_layout, "_reconcile_registry",
                            lambda s, w: events.append(("reconcile", w))
                            or removed[w])
        monkeypatch.setattr(pane_layout, "_running_tui_pane",
                            lambda s: events.append("running?") or None)
        monkeypatch.setattr(pane_layout, "_respawn_tui",
                            lambda s, w: events.append(("respawn", w)) or "@7")
        monkeypatch.setattr(pane_layout, "rebalance",
                            lambda s, w: events.append(("rebalance", w)))
        pane_layout._process_registry_pane_closed({
            "session": "pm-x", "windows": {
                "@0": {"panes": [{"id": "%0", "role": "tui", "order": 0,
                                  "cmd": "pm _tui"}]},
                "@4": {"panes": [{"id": "%5", "role": "review-claude",
                                  "order": 0, "cmd": "x"}]},
                "@6": {"user_modified": True, "panes": [
                    {"id": "%9", "role": "review-claude", "order": 0,
                     "cmd": "x"}]}}})
        # The TUI's window was gone: rebalance the window it respawned in;
        # @4 lost nothing; @6 was rearranged by the user.
        assert events == [("lock", "pm-x"), "enter",
                          ("reconcile", "@0"), "running?", ("respawn", "@0"),
                          ("reconcile", "@4"), ("reconcile", "@6"),
                          "exit", ("rebalance", "@7")]


class TestStuckHolderDelaysOneWait:
    """QA S47: the after-kill-pane hook is a synchronous run-shell, so the
    client that closed a pane is frozen while the hook waits for the lock.
    A stuck holder used to cost one full wait per registered window."""

    def test_a_close_with_three_windows_waits_once(self, tmp_path,
                                                   monkeypatch):
        import fcntl
        import functools
        monkeypatch.setenv("HOME", str(tmp_path))
        log = MagicMock()
        monkeypatch.setattr(pane_registry, "_logger", log)
        monkeypatch.setattr(
            pane_registry, "tui_respawn_lock",
            functools.partial(pane_registry.tui_respawn_lock, timeout=0.4))
        monkeypatch.setattr(pane_layout, "_reconcile_registry",
                            lambda s, w: [])
        monkeypatch.setattr(pane_layout, "rebalance", lambda s, w: None)
        reg = pane_registry.registry_path(SESSION)
        reg.parent.mkdir(parents=True, exist_ok=True)
        lock_path = reg.with_suffix(reg.suffix + ".respawn.lock")
        with open(lock_path, "a") as holder:  # another process's flock
            fcntl.flock(holder, fcntl.LOCK_EX)
            start = time.monotonic()
            pane_layout._process_registry_pane_closed({
                "session": SESSION, "windows": {
                    w: {"panes": []} for w in ("@0", "@4", "@6")}})
            elapsed = time.monotonic() - start
        assert 0.4 <= elapsed < 0.8, elapsed
        assert log.warning.call_count == 1
        assert "still held" in log.warning.call_args.args[0]


@needs_tmux
class TestAnotherReconcileTookTheDeadTuiEntry:
    """QA S50: every ``rebalance()`` reconciles the registry without the
    respawn lock.  The background rebalance of a ``pm session`` attach
    (about 0.6 s after its Enter) could drop the killed TUI's entry before
    the after-kill-pane hook reconciled, and the hook, which respawned
    only a TUI its own reconcile removed, left the session with none."""

    def test_entry_gone_before_the_hook_read_the_registry(
            self, server, tmp_path, monkeypatch):
        project, window, tui, notes = _start(server, tmp_path)
        server("kill-pane", "-t", tui)
        # The attach's rebalance reconciles first: the hook then reads a
        # registry that lists no TUI at all.
        assert pane_registry._reconcile_registry(SESSION, window) == [tui]
        pane_layout._process_registry_pane_closed(
            pane_registry.load_registry(SESSION))
        [new] = _tui_panes(server)
        assert server("display-message", "-p", "-t", new,
                      "#{window_id}") == window
        assert _registered_tuis() == [new]

    def test_entry_gone_between_the_hooks_read_and_its_reconcile(
            self, server, tmp_path, monkeypatch):
        project, window, tui, notes = _start(server, tmp_path)
        before = pane_registry.load_registry(SESSION)  # what the hook read
        server("kill-pane", "-t", tui)
        assert pane_registry._reconcile_registry(SESSION, window) == [tui]
        pane_layout._process_registry_pane_closed(before)
        [new] = _tui_panes(server)
        assert server("display-message", "-p", "-t", new,
                      "#{window_id}") == window
        assert _registered_tuis() == [new]

    def test_with_no_listed_window_the_tui_goes_into_main(
            self, server, tmp_path, monkeypatch):
        """Nothing records where the TUI was: ``main``, as ``pm session``'s
        own respawn picks."""
        project, window, tui, notes = _start(server, tmp_path)
        other = server("new-window", "-d", "-P", "-F", "#{window_id}",
                       "-t", f"={SESSION}:", "sleep 300")
        server("kill-pane", "-t", tui)
        pane_registry._reconcile_registry(SESSION, window)
        pane_layout._process_registry_pane_closed(
            {"session": SESSION, "windows": {other: {"panes": []}}})
        [new] = _tui_panes(server)
        assert server("display-message", "-p", "-t", new,
                      "#{window_id}") == window

    def test_a_running_unlisted_tui_is_left_alone(
            self, server, tmp_path, monkeypatch):
        """A TUI that has not registered itself yet is running: no second."""
        project, window, tui, notes = _start(server, tmp_path)
        pane_registry.unregister_pane(SESSION, tui)
        pane_layout._process_registry_pane_closed(
            pane_registry.load_registry(SESSION))
        assert _tui_panes(server) == [tui]


class TestUnlistedTuiRespawnNeedsTheLock:

    def _wire(self, monkeypatch, *, locked, registry, running=None):
        events = []

        class Lock:
            def __init__(self, name):
                pass

            def __enter__(self):
                return locked

            def __exit__(self, *exc):
                events.append("exit")

        monkeypatch.setattr(pane_registry, "tui_respawn_lock", Lock)
        monkeypatch.setattr(pane_layout, "_reconcile_registry",
                            lambda s, w: [])
        monkeypatch.setattr(pane_layout, "load_registry", lambda s: registry)
        monkeypatch.setattr(pane_layout, "_running_tui_pane",
                            lambda s: events.append("running?") or running)
        monkeypatch.setattr(pane_layout, "_respawn_tui",
                            lambda s, w: events.append(("respawn", w)) or w)
        monkeypatch.setattr(pane_layout, "rebalance",
                            lambda s, w: events.append(("rebalance", w)))
        return events

    SNAPSHOT = {"session": "pm-x", "windows": {"@0": {"panes": [
        {"id": "%0", "role": "tui", "order": 0, "cmd": "pm _tui"},
        {"id": "%1", "role": "notes", "order": 1, "cmd": "x"}]}}}

    def test_respawns_under_the_lock(self, monkeypatch):
        events = self._wire(monkeypatch, locked=True, registry={
            "windows": {"@0": {"panes": [
                {"id": "%1", "role": "notes", "order": 1, "cmd": "x"}]}}})
        pane_layout._process_registry_pane_closed(self.SNAPSHOT)
        assert events == ["running?", ("respawn", "@0"), "exit",
                          ("rebalance", "@0")]

    def test_not_without_the_lock(self, monkeypatch):
        """Two hooks past a stuck holder would both find no TUI; only the
        one whose reconcile removed the entry starts one."""
        events = self._wire(monkeypatch, locked=False, registry={
            "windows": {"@0": {"panes": []}}})
        pane_layout._process_registry_pane_closed(self.SNAPSHOT)
        assert events == ["exit"]

    def test_not_while_a_tui_is_listed(self, monkeypatch):
        """A TUI pane kept dead by remain-on-exit is still listed (tmux
        still has it); ``pm session`` leaves that alone too.  Nothing is
        asked of tmux on an ordinary close."""
        events = self._wire(monkeypatch, locked=True,
                            registry=self.SNAPSHOT)
        pane_layout._process_registry_pane_closed(self.SNAPSHOT)
        assert events == ["exit"]

    def test_not_while_a_tui_runs(self, monkeypatch):
        events = self._wire(monkeypatch, locked=True, running="%5",
                            registry={"windows": {}})
        pane_layout._process_registry_pane_closed(self.SNAPSHOT)
        assert events == ["running?", "exit"]
