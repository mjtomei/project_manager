"""Per-session tmux server isolation (pr-073910f).

Covers:
- paths: deterministic per-session socket paths (and long-name fallback)
- tmux: $TMUX resolution, explicit default-server targeting, precise client
  detach, cross-server discovery
- CLI: TUI pane discovery across servers
- integration: two disposable tmux servers stay independent under
  quit/detach/cleanup in one of them

The integration tests create their own sockets and never touch the user's
live tmux server.
"""

import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import paths, tmux


# ---------------------------------------------------------------------------
# paths: session_socket_path
# ---------------------------------------------------------------------------

class TestSessionSocketPath:
    def test_deterministic(self):
        a = paths.session_socket_path("repo-abcd1234")
        b = paths.session_socket_path("repo-abcd1234")
        assert a == b

    def test_prefix_and_dir(self):
        p = paths.session_socket_path("repo-abcd1234")
        assert p.parent == paths.SHARED_SOCKET_DIR
        assert p.name == "pm-repo-abcd1234"

    def test_shared_socket_path_alias(self):
        assert (paths.shared_socket_path("tag")
                == paths.session_socket_path("tag"))

    def test_distinct_tags_distinct_sockets(self):
        assert (paths.session_socket_path("a-11111111")
                != paths.session_socket_path("b-22222222"))

    def test_long_tag_uses_short_hashed_name(self):
        p = paths.session_socket_path("x" * 200)
        assert p.parent == paths.SHARED_SOCKET_DIR
        assert len(str(p)) <= 100
        assert p.name.startswith("pm-")
        # Deterministic even when hashed
        assert p == paths.session_socket_path("x" * 200)

    def test_ensure_socket_dir_alias(self, tmp_path):
        fake = tmp_path / "pm-sessions"
        with patch.object(paths, "SHARED_SOCKET_DIR", fake):
            paths.ensure_socket_dir()
        assert fake.is_dir()
        assert (fake.stat().st_mode & 0o7777) == 0o1777


# ---------------------------------------------------------------------------
# tmux: ambient socket resolution
# ---------------------------------------------------------------------------

class TestSocketPathFromTmuxEnv:
    def test_none_without_tmux(self):
        assert tmux.socket_path_from_tmux_env({}) is None

    def test_accepts_pm_socket(self, tmp_path):
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path):
            sock = tmp_path / "pm-repo-abc"
            env = {"TMUX": f"{sock},1234,0"}
            assert tmux.socket_path_from_tmux_env(env) == str(sock)

    def test_rejects_default_server(self, tmp_path):
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path / "pm-sessions"):
            env = {"TMUX": "/tmp/tmux-1000/default,1234,0"}
            assert tmux.socket_path_from_tmux_env(env) is None

    def test_parses_socket_with_commas(self, tmp_path):
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path):
            sock = tmp_path / "pm-with,comma"
            env = {"TMUX": f"{sock},1234,7"}
            assert tmux.socket_path_from_tmux_env(env) == str(sock)

    def test_pm_tmux_socket_wins(self, tmp_path):
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path):
            env = {"PM_TMUX_SOCKET": "/explicit",
                   "TMUX": f"{tmp_path / 'pm-x'},1,0"}
            assert tmux.resolve_ambient_socket(env) == "/explicit"

    def test_export_sets_env(self, tmp_path):
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path):
            sock = tmp_path / "pm-x"
            env = {"TMUX": f"{sock},1,0"}
            assert tmux.export_ambient_socket(env) == str(sock)
            assert env["PM_TMUX_SOCKET"] == str(sock)


# ---------------------------------------------------------------------------
# wrapper: the entry-point resolver (R4.1)
#
# The wrapper runs before pm_core is imported, so it repeats the socket
# directory instead of importing paths.  Pin it to the real value.
# ---------------------------------------------------------------------------

class TestWrapperMarksTmuxSocket:
    def test_socket_dir_literal_matches_paths(self):
        from pm_core import wrapper

        assert wrapper._PM_SOCKET_DIR == str(paths.SHARED_SOCKET_DIR)

    def test_exports_pm_socket_from_tmux(self):
        from pm_core import wrapper

        env = {"TMUX": "/tmp/pm-sessions/pm-repo-abc,1234,0"}
        wrapper._mark_tmux_socket(env)
        assert env["PM_TMUX_SOCKET"] == "/tmp/pm-sessions/pm-repo-abc"

    def test_leaves_ordinary_tmux_sessions_alone(self):
        from pm_core import wrapper

        env = {"TMUX": "/tmp/tmux-1000/default,1234,0"}
        wrapper._mark_tmux_socket(env)
        assert "PM_TMUX_SOCKET" not in env

    def test_keeps_an_explicit_socket(self):
        from pm_core import wrapper

        env = {"PM_TMUX_SOCKET": "/tmp/pm-sessions/pm-explicit",
               "TMUX": "/tmp/pm-sessions/pm-other,1234,0"}
        wrapper._mark_tmux_socket(env)
        assert env["PM_TMUX_SOCKET"] == "/tmp/pm-sessions/pm-explicit"

    def test_no_tmux_no_socket(self):
        from pm_core import wrapper

        env: dict[str, str] = {}
        wrapper._mark_tmux_socket(env)
        assert "PM_TMUX_SOCKET" not in env


class TestQaStatusSocketLiteral:
    """qa_status.py runs standalone (no pm_core import), so it hardcodes
    the socket directory; keep the copy honest without importing the
    module (it configures logging at import time)."""

    def test_hardcoded_socket_dir_matches_paths(self):
        import pm_core

        src = (Path(pm_core.__file__).parent / "qa_status.py").read_text()
        assert f'"{paths.SHARED_SOCKET_DIR}"' in src


class TestQaStatusSocketRouting:
    """The QA status pane must drive the client of *its own* server.

    ``qa_status.py`` runs standalone and builds tmux argv itself, so it
    resolves the socket from ``PM_TMUX_SOCKET`` (exported into every pm
    pane) and falls back to a ``$TMUX`` value only when that names a pm
    socket.  Without this, ``select-window`` addressed the default server
    and a private session's status pane could not switch its window.
    """

    @staticmethod
    def _module():
        import logging

        # Importing qa_status installs a file logger; keep the suite's
        # logging configuration untouched.
        with patch.object(logging, "basicConfig"):
            from pm_core import qa_status
        return qa_status

    def test_switching_windows_uses_the_session_socket(self, monkeypatch):
        qa_status = self._module()
        monkeypatch.delenv("TMUX_PANE", raising=False)
        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-x")
        calls: list[list[str]] = []

        class _Result:
            returncode = 0
            stdout = "pm-x 1\n"

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _Result()

        monkeypatch.setattr(qa_status.subprocess, "run", fake_run)
        qa_status._switch_to_window("pm-x", "main")

        assert calls, "no tmux command ran"
        assert all(cmd[:3] == ["tmux", "-S", "/tmp/pm-sessions/pm-x"]
                   for cmd in calls), calls
        assert calls[-1][3:] == ["select-window", "-t", "pm-x:main"]

    def test_falls_back_to_the_pm_socket_named_by_tmux(self, monkeypatch):
        qa_status = self._module()
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setenv("TMUX", "/tmp/pm-sessions/pm-x,4242,0")

        assert qa_status._tmux_argv("list-sessions") == [
            "tmux", "-S", "/tmp/pm-sessions/pm-x", "list-sessions"]

    def test_leaves_an_ordinary_tmux_session_alone(self, monkeypatch):
        qa_status = self._module()
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,4242,0")

        assert qa_status._tmux_argv("list-sessions") == [
            "tmux", "list-sessions"]


# ---------------------------------------------------------------------------
# tmux: explicit default-server targeting
# ---------------------------------------------------------------------------

class TestUseEnvFlag:
    def test_use_env_false_omits_socket(self):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/pm-sessions/pm-x"}):
            cmd = tmux._tmux_cmd("list-sessions", use_env=False)
        assert "-S" not in cmd

    def test_use_env_true_uses_env(self):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/pm-sessions/pm-x"}):
            cmd = tmux._tmux_cmd("list-sessions")
        assert cmd == ["tmux", "-S", "/tmp/pm-sessions/pm-x", "list-sessions"]

    @patch("pm_core.tmux.subprocess.run")
    def test_session_exists_forwards_use_env(self, mock_run):
        """use_env=False must reach the real default server, not $TMUX."""
        mock_run.return_value = MagicMock(returncode=1)
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/pm-sessions/pm-x",
                                     "TMUX": "/tmp/pm-sessions/pm-x,1,0"}):
            tmux.session_exists("pm-x", use_env=False)
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["tmux", "-S", str(paths.default_socket_path())]

    @patch("pm_core.tmux.subprocess.run")
    def test_session_exists_keeps_ambient_socket_by_default(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/pm-sessions/pm-x"}):
            tmux.session_exists("pm-x")
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["tmux", "-S", "/tmp/pm-sessions/pm-x"]

    def test_default_socket_path_is_uid_scoped(self):
        p = paths.default_socket_path()
        assert p.name == "default"
        assert p.parent.name == f"tmux-{os.getuid()}"


# ---------------------------------------------------------------------------
# tmux: which server hosts a session (private socket vs legacy default)
# ---------------------------------------------------------------------------

class TestFindSessionServer:
    def test_private_socket_wins(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(
            tmux, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path == str(tmp_path / "pm-repo-abc"))

        sock, private = tmux.find_session_server("pm-repo-abc~2")
        assert (sock, private) == (str(tmp_path / "pm-repo-abc"), True)

    def test_falls_back_to_explicit_default_server(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(
            tmux, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path is None and not use_env)

        sock, private = tmux.find_session_server("pm-legacy")
        # Not None: the default server must be addressed by its path,
        # because tmux would otherwise follow $TMUX.
        assert sock == str(paths.default_socket_path())
        assert private is False

    def test_missing_everywhere(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(tmux, "session_exists", lambda *a, **kw: False)
        assert tmux.find_session_server("pm-gone") == (None, False)

    def test_tmux_unavailable_degrades_to_none(self, monkeypatch, tmp_path):
        """A missing/broken tmux must not crash discovery."""
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)

        def boom(*a, **kw):
            raise OSError("no tmux")

        monkeypatch.setattr(tmux, "session_exists", boom)
        assert tmux.find_session_server("pm-repo-abc") == (None, False)

    def test_non_pm_name_only_checks_default(self, monkeypatch, tmp_path):
        """A plain tmux session must never be mapped to a pm socket."""
        seen: list[str | None] = []
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)

        def exists(name, socket_path=None, use_env=True):
            seen.append(socket_path)
            return True

        monkeypatch.setattr(tmux, "session_exists", exists)
        sock, private = tmux.find_session_server("work")
        assert (sock, private) == (str(paths.default_socket_path()), False)
        assert seen == [None]  # no private-socket probe was made


class TestServerAlive:
    def test_live_and_stale_sockets(self, monkeypatch):
        monkeypatch.setattr(
            tmux, "_run",
            lambda *a, **kw: MagicMock(returncode=0, stdout=""))
        assert tmux.server_alive("/tmp/pm-sessions/pm-x") is True

        monkeypatch.setattr(
            tmux, "_run",
            lambda *a, **kw: MagicMock(returncode=1, stderr="no server"))
        assert tmux.server_alive("/tmp/pm-sessions/pm-x") is False

    def test_unprobeable_socket_counts_as_alive(self, monkeypatch):
        """Never delete a socket on a guess: if tmux cannot run, keep it.

        ``pm session kill`` unlinks a socket file when ``server_alive`` says
        nothing answers on it; an OSError (tmux missing or not executable)
        must not be read as "the server is gone".
        """

        def boom(*a, **kw):
            raise OSError("no tmux")

        monkeypatch.setattr(tmux, "_run", boom)
        assert tmux.server_alive("/tmp/pm-sessions/pm-x") is True


class TestGetSessionEnvironment:
    """Reading a session's environment is how share mode is recovered."""

    def test_returns_the_value(self, monkeypatch):
        monkeypatch.setattr(
            tmux, "_run",
            lambda *a, **kw: MagicMock(returncode=0,
                                       stdout="PM_SHARE_MODE=global\n"))
        assert tmux.get_session_environment(
            "pm-x", "PM_SHARE_MODE") == "global"

    def test_unset_variable_is_none(self, monkeypatch):
        # tmux exits non-zero for a variable the session does not have.
        monkeypatch.setattr(
            tmux, "_run",
            lambda *a, **kw: MagicMock(returncode=1, stdout=""))
        assert tmux.get_session_environment("pm-x", "PM_SHARE_MODE") is None

    def test_marked_for_removal_is_none(self, monkeypatch):
        monkeypatch.setattr(
            tmux, "_run",
            lambda *a, **kw: MagicMock(returncode=0, stdout="-PM_SHARE_MODE\n"))
        assert tmux.get_session_environment("pm-x", "PM_SHARE_MODE") is None

    def test_tmux_missing_is_none(self, monkeypatch):
        def boom(*a, **kw):
            raise OSError("no tmux")

        monkeypatch.setattr(tmux, "_run", boom)
        assert tmux.get_session_environment("pm-x", "PM_SHARE_MODE") is None


# ---------------------------------------------------------------------------
# tmux: precise client detach
# ---------------------------------------------------------------------------

class TestDetachCurrentClient:
    @patch("pm_core.tmux.subprocess.run")
    def test_detaches_only_client_viewing_pane_window(self, mock_run,
                                                      monkeypatch):
        monkeypatch.setenv("TMUX_PANE", "%7")
        # Empty (falsy) and restored to absent by monkeypatch.
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            args = cmd
            if "display" in args and "-t" in args:
                target = args[args.index("-t") + 1]
                if target == "%7":
                    return MagicMock(returncode=0, stdout="@1\n")
                if target == "pm-x~1":
                    return MagicMock(returncode=0, stdout="@1\n")
                return MagicMock(returncode=0, stdout="@2\n")
            if "display-message" in args and "%7" in args:
                return MagicMock(returncode=0, stdout="pm-x~1\n")
            if "list-sessions" in args:
                return MagicMock(returncode=0,
                                 stdout="pm-x\npm-x~1\npm-x~2\n")
            if "list-clients" in args:
                # ~1 views the TUI window, ~2 does not.
                return MagicMock(
                    returncode=0,
                    stdout="/dev/pts/1|100|10|pm-x~1\n"
                           "/dev/pts/2|200|20|pm-x~2\n")
            if "detach-client" in args:
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-1] == "/dev/pts/1"

    @patch("pm_core.tmux.subprocess.run")
    def test_falls_back_to_session_detach(self, mock_run, monkeypatch):
        """No client views the TUI window: detach by session, not server-wide.

        The client is attached to a grouped session whose active window is
        a *different* window (e.g. a review window), so the precise
        per-window match finds nothing and the session-level fallback has
        to fire.
        """
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            # Command checks first: list-sessions also carries a bare
            # "#{session_name}" format argument.
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\npm-x~1\n")
            if "list-clients" in cmd:
                return MagicMock(returncode=0,
                                 stdout="/dev/pts/1|100|10|pm-x~1\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{window_id}" in cmd:
                target = cmd[cmd.index("-t") + 1]
                # TUI pane lives in @1; the client's session views @2.
                return MagicMock(returncode=0,
                                 stdout="@1\n" if target == "%7" else "@2\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "#{session_attached}" in cmd:
                target = cmd[cmd.index("-t") + 1]
                return MagicMock(returncode=0,
                                 stdout="1\n" if target == "pm-x~1" else "0\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-2:] == ["-s", "pm-x~1"]

    @patch("pm_core.tmux.subprocess.run")
    def test_failed_detach_is_not_reported_as_success(self, mock_run,
                                                      monkeypatch):
        """A non-zero detach-client must not be claimed as a detach."""
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-clients" in cmd:
                return MagicMock(returncode=0,
                                 stdout="/dev/pts/1|100|10|pm-x\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=1, stdout="",
                                 stderr="no such client")
            if "#{window_id}" in cmd:
                return MagicMock(returncode=0, stdout="@1\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            return MagicMock(returncode=0, stdout="0\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is False

    @patch("pm_core.tmux.subprocess.run")
    def test_never_issues_bare_detach(self, mock_run, monkeypatch):
        monkeypatch.setenv("TMUX_PANE", "%7")
        # Empty (falsy) and restored to absent by monkeypatch.
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "display-message" in cmd and "%7" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-clients" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "display-message" in cmd:
                return MagicMock(returncode=0, stdout="0\n")
            return MagicMock(returncode=0, stdout="")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is False
        for call in mock_run.call_args_list:
            assert call[0][0][-1] != "detach-client"

    def test_no_pane_returns_false(self, monkeypatch):
        monkeypatch.delenv("TMUX_PANE", raising=False)
        assert tmux.detach_current_client() is False

    def test_tmux_missing_does_not_crash_the_quit_path(self, monkeypatch):
        """``quit_app`` must degrade, not raise, when tmux cannot be run.

        The TUI's quit handler calls this directly; an ``OSError`` from a
        missing/unexecutable tmux would surface as an exception instead of
        "nothing to detach" (the same degrade-never-crash contract the
        discovery paths follow).
        """
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setattr(tmux, "_run",
                            MagicMock(side_effect=OSError("no tmux")))
        assert tmux.detach_current_client() is False

    @patch("pm_core.tmux.subprocess.run")
    def test_explicit_socket_is_used_for_every_call(self, mock_run,
                                                    monkeypatch):
        """``socket_path=`` must reach every tmux query, not just the detach.

        ``quit_app`` relies on ``PM_TMUX_SOCKET``, but the argument is part
        of the signature; a call that dropped it would query — and detach —
        on whichever server the process happens to sit on.
        """
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        sock = "/tmp/pm-sessions/pm-x"

        def fake_run(cmd, **kwargs):
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-clients" in cmd:
                return MagicMock(returncode=0,
                                 stdout="/dev/pts/1|100|10|pm-x\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            return MagicMock(returncode=0, stdout="@1\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client(socket_path=sock) is True
        for call in mock_run.call_args_list:
            assert call[0][0][:3] == ["tmux", "-S", sock], call[0][0]

    @patch("pm_core.tmux.subprocess.run")
    def test_tolerates_non_numeric_client_timestamps(self, mock_run,
                                                     monkeypatch):
        """Empty/garbage client_activity fields must not crash the quit path."""
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-clients" in cmd:
                return MagicMock(returncode=0,
                                 stdout="/dev/pts/1|abc||pm-x\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            return MagicMock(returncode=0, stdout="@1\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True


# ---------------------------------------------------------------------------
# tmux: cross-server discovery
# ---------------------------------------------------------------------------

class TestListPmSessions:
    @patch("pm_core.tmux.subprocess.run")
    def test_lists_private_and_default_servers(self, mock_run, tmp_path):
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        sock = sock_dir / "pm-repo-abc"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(sock))
        finally:
            s.close()

        def fake_run(cmd, **kwargs):
            if str(sock) in cmd:
                return MagicMock(returncode=0, stdout=(
                    "pm-repo-abc|0\n"
                    "pm-repo-abc~1|2\n"
                ))
            if str(paths.default_socket_path()) in cmd:
                return MagicMock(returncode=0, stdout="pm-legacy-1|1\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            rows = tmux.list_pm_sessions()

        by_name = {r["name"]: r for r in rows}
        assert by_name["pm-repo-abc"]["socket"] == str(sock)
        assert by_name["pm-repo-abc"]["attached"] == 2  # base + grouped
        assert by_name["pm-legacy-1"]["socket"] is None
        assert by_name["pm-legacy-1"]["attached"] == 1

    @patch("pm_core.tmux.subprocess.run")
    def test_skips_dead_socket(self, mock_run, tmp_path):
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        (sock_dir / "pm-dead").write_text("")  # not a socket
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            assert tmux.list_pm_sessions() == []

    @patch("pm_core.tmux.subprocess.run")
    def test_marks_shared_sockets(self, mock_run, tmp_path):
        """--global/--group chmod the socket; private servers stay 0600."""
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        for name, mode in (("pm-shared", 0o777), ("pm-private", 0o600)):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.bind(str(sock_dir / name))
            finally:
                s.close()
            (sock_dir / name).chmod(mode)

        def fake_run(cmd, **kwargs):
            if "-S" in cmd:
                sock = Path(cmd[cmd.index("-S") + 1])
                return MagicMock(returncode=0,
                                 stdout=f"{sock.name}|0\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            rows = tmux.list_pm_sessions()

        by_socket = {Path(r["socket"]).name: r["shared"]
                     for r in rows if r["socket"]}
        assert by_socket["pm-shared"] is True
        assert by_socket["pm-private"] is False

    @patch("pm_core.tmux.subprocess.run")
    def test_default_server_row_ignores_tmux(self, mock_run, tmp_path,
                                             monkeypatch):
        """Run from inside a pm pane, the default row must still be default.

        tmux honours $TMUX when no -S is given, which previously made the
        "default server" row list the *current* private server instead.
        """
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        monkeypatch.setenv("TMUX", "/tmp/pm-sessions/pm-x,1,0")
        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-x")
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            tmux.list_pm_sessions()

        default_calls = [c for c in mock_run.call_args_list
                         if str(paths.default_socket_path()) in c[0][0]]
        assert len(default_calls) == 1


# ---------------------------------------------------------------------------
# CLI: resolving a session *and* its server outside tmux
# ---------------------------------------------------------------------------

class TestGetPmSessionSelectsServer:
    def test_private_socket_selected_outside_tmux(self, monkeypatch, tmp_path):
        from pm_core.cli import helpers

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(helpers.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(helpers, "_get_current_pm_session", lambda: None)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-target")
        monkeypatch.setattr(
            helpers.tmux_mod, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path == str(tmp_path / "pm-target"))

        assert helpers._get_pm_session() == "pm-target"
        assert os.environ["PM_TMUX_SOCKET"] == str(tmp_path / "pm-target")

    def test_legacy_session_selects_default_server(self, monkeypatch, tmp_path):
        from pm_core.cli import helpers

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/other")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(helpers.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(helpers, "_get_current_pm_session", lambda: None)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-legacy")
        monkeypatch.setattr(
            helpers.tmux_mod, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path is None and not use_env)

        assert helpers._get_pm_session() == "pm-legacy"
        assert os.environ["PM_TMUX_SOCKET"] == str(paths.default_socket_path())

    def test_inside_pm_session_keeps_ambient_socket(self, monkeypatch):
        """The common in-pane path must not pay an extra tmux lookup."""
        from pm_core.cli import helpers

        monkeypatch.setattr(helpers.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(helpers, "_get_current_pm_session",
                            lambda: "pm-current")
        monkeypatch.setattr(
            helpers.tmux_mod, "session_exists",
            lambda *a, **kw: pytest.fail("should not query tmux"))

        assert helpers._get_pm_session() == "pm-current"


# ---------------------------------------------------------------------------
# CLI: TUI pane discovery across servers
# ---------------------------------------------------------------------------

class TestFindTuiPaneAcrossServers:
    def test_scans_private_servers(self, monkeypatch):
        from pm_core.cli import helpers
        from pm_core import pane_registry

        # Empty (falsy) and restored to absent by monkeypatch.
        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-target", "socket": "/tmp/s",
                                      "attached": 0}])
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists",
                            lambda pane: pane == "%42")
        monkeypatch.setattr(
            pane_registry, "load_registry",
            lambda name: {"windows": {"@1": {"panes": [
                {"id": "%42", "role": "tui"}]}}})

        pane_id, session = helpers._find_tui_pane()
        assert (pane_id, session) == ("%42", "pm-target")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/s"

    def test_no_tmux_degrades_to_no_session(self, monkeypatch):
        """Discovery must not crash when tmux cannot be run.

        ``find_session_server`` already degrades to ``(None, False)``; the
        rest of the scan (session probe, server list, pane probe) has to
        follow, otherwise ``pm tui view`` / ``pm autostart`` trace back on a
        machine where tmux is missing or unexecutable.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(
            pane_registry, "load_registry",
            lambda name: {"windows": {"@1": {"panes": [
                {"id": "%6", "role": "tui"}]}}})
        monkeypatch.setattr(helpers.subprocess, "run",
                            MagicMock(side_effect=OSError("no tmux")))

        assert helpers._find_tui_pane() == (None, None)
        assert helpers._find_live_tui_pane() == (None, None)

    def test_tmux_missing_inside_a_pane_degrades_to_no_session(
            self, monkeypatch):
        """``$TMUX`` set but no tmux binary must not crash discovery.

        The in-tmux branch resolves the current session first; that query
        is a subprocess like every other probe in the scan, so it has to
        degrade rather than raise when tmux cannot be run (a forwarded
        pane environment, or a container without tmux installed).
        """
        from pm_core.cli import helpers

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            MagicMock(side_effect=OSError("no tmux")))
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [])

        assert helpers._find_tui_pane() == (None, None)

    def test_failed_scan_restores_ambient_socket(self, monkeypatch):
        """A lookup that finds nothing must not leave the env re-pointed."""
        from pm_core.cli import helpers

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-a", "socket": "/tmp/s1",
                                      "attached": 0},
                                     {"name": "pm-b", "socket": "/tmp/s2",
                                      "attached": 0}])
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists", lambda p: False)
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **kw: MagicMock(returncode=1,
                                                       stdout=""))

        assert helpers._find_tui_pane() == (None, None)
        assert "PM_TMUX_SOCKET" not in os.environ

    def test_failed_lookup_restores_the_original_socket(self, monkeypatch,
                                                       tmp_path):
        """The cwd branch selects a server *before* the scan runs.

        A failed lookup must restore the socket this process came in with,
        not the cwd session's socket the earlier branch happened to select.
        """
        from pm_core.cli import helpers

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/original.sock")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        # The cwd session is running, so _select_session_socket re-points
        # PM_TMUX_SOCKET at it — but its registry has no live TUI pane.
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: True)
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists", lambda p: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [])
        monkeypatch.setattr(helpers.pane_registry, "load_registry",
                            lambda name: {"windows": {}})

        assert helpers._find_tui_pane() == (None, None)
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/original.sock"

    def test_last_resort_finds_an_unregistered_tui_pane(self, monkeypatch):
        """A live ``pm _tui`` pane with no registry entry is still found.

        The direct scan is what catches a TUI whose registry entry was
        removed (e.g. during heal testing).  It shares the pane query with
        ``_find_live_tui_pane`` and normalises a grouped session name to
        its base.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-target", "socket": "/tmp/s",
                                      "attached": 0, "shared": False}])
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        monkeypatch.setattr(
            helpers.subprocess, "run",
            lambda *a, **kw: MagicMock(
                returncode=0,
                stdout="%7 pm-target~1 pm _tui\n%8 pm-other bash\n"))

        assert helpers._find_tui_pane() == ("%7", "pm-target")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/s"

    def test_explicit_session_selects_its_server(self, monkeypatch, tmp_path):
        from pm_core.cli import helpers
        from pm_core import pane_registry

        # Empty (falsy) and restored to absent by monkeypatch.
        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: True)
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists", lambda p: True)
        monkeypatch.setattr(
            pane_registry, "load_registry",
            lambda name: {"windows": {"@1": {"panes": [
                {"id": "%9", "role": "tui"}]}}})

        pane_id, session = helpers._find_tui_pane("pm-target~2")
        assert (pane_id, session) == ("%9", "pm-target")
        assert os.environ["PM_TMUX_SOCKET"] == str(
            tmp_path / "pm-target")


# ---------------------------------------------------------------------------
# CLI: server selection for a session (private vs legacy)
# ---------------------------------------------------------------------------

class TestResolveSessionSocket:
    def test_private_socket_selected_and_exported(self, monkeypatch, tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "session_exists",
                            lambda *a, **kw: False)

        sock, legacy = session_mod._resolve_session_socket("pm-repo-abc",
                                                           False)
        assert sock == str(tmp_path / "pm-repo-abc")
        assert legacy is False
        assert os.environ["PM_TMUX_SOCKET"] == sock

    def test_legacy_default_server_is_preserved(self, monkeypatch, tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)

        def exists(name, socket_path=None, use_env=True):
            # No private session; a legacy session exists on default.
            return socket_path is None and not use_env

        monkeypatch.setattr(session_mod.tmux_mod, "session_exists", exists)

        sock, legacy = session_mod._resolve_session_socket("pm-repo-abc",
                                                           False)
        assert sock is None
        assert legacy is True
        # Not merely cleared: the tmux binary follows $TMUX when no -S is
        # given, so the default server has to be addressed explicitly or
        # the legacy session looks missing from inside another pm pane.
        assert os.environ["PM_TMUX_SOCKET"] == str(paths.default_socket_path())

    def test_shared_never_falls_back_to_legacy(self, monkeypatch, tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "session_exists",
                            lambda *a, **kw: False)

        sock, legacy = session_mod._resolve_session_socket("pm-repo-abc",
                                                           True)
        assert sock == str(tmp_path / "pm-repo-abc")
        assert legacy is False

    def test_refuses_socket_owned_by_another_user(self, monkeypatch, tmp_path):
        """The socket dir is world-writable; never connect to a planted one."""
        from pm_core.cli import session as session_mod

        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        (sock_dir / "pm-repo-abc").write_text("")
        real_uid = os.getuid()
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", sock_dir)
        monkeypatch.setattr(session_mod.os, "getuid", lambda: real_uid + 1)

        with pytest.raises(SystemExit):
            session_mod._resolve_session_socket("pm-repo-abc", False)

    def test_refuses_a_symlink_planted_at_the_socket_path(self, monkeypatch,
                                                          tmp_path):
        """A dangling symlink must be refused, not followed.

        ``stat()`` follows the link, so a link to a path that does not exist
        yet raises ``OSError`` and the check would treat the socket as ours;
        tmux would then create a server socket at the attacker-chosen
        target.  The ownership check inspects the directory entry itself.
        """
        from pm_core.cli import session as session_mod

        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        (sock_dir / "pm-repo-abc").symlink_to(tmp_path / "attacker-chosen")
        real_uid = os.getuid()
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", sock_dir)
        monkeypatch.setattr(session_mod.os, "getuid", lambda: real_uid + 1)

        with pytest.raises(SystemExit):
            session_mod._resolve_session_socket("pm-repo-abc", False)
        assert not (tmp_path / "attacker-chosen").exists()


class TestSessionKillServerSelection:
    """``pm session kill`` must target the server that hosts the session."""

    def _invoke(self, monkeypatch, tmp_path, hosting, *, ambient=None,
                ambient_share_mode=None, hosting_for=None, alive=False,
                args=("kill",)):
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod
        from pm_core import container, push_proxy

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(session_mod.tmux_mod, "server_alive",
                            lambda sock: alive)
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-repo-abc")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: ambient)
        # Never query a real tmux server from a unit test.
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: ambient_share_mode)
        if hosting_for is None:
            monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                                lambda name: hosting)
        else:
            # Per-name hosting, so the cwd session can be absent while the
            # ambient one is live.
            monkeypatch.setattr(
                session_mod.tmux_mod, "find_session_server",
                lambda name: hosting_for.get(name, (None, False)))
        killed: list[tuple[str, str | None]] = []
        monkeypatch.setattr(
            session_mod.tmux_mod, "list_grouped_sessions",
            lambda name, socket_path=None: [f"{name}~1"])
        monkeypatch.setattr(
            session_mod.tmux_mod, "kill_session",
            lambda name, socket_path=None: killed.append((name, socket_path)))
        monkeypatch.setattr(session_mod.pane_layout, "set_force_mobile",
                            lambda *a, **k: None)
        monkeypatch.setattr(container, "cleanup_session_containers",
                            lambda tag: 0)
        monkeypatch.setattr(push_proxy, "stop_session_proxies", lambda tag: 0)

        result = CliRunner().invoke(session_mod.session, list(args))
        return result, killed

    def test_private_session_kills_on_its_own_socket(self, monkeypatch,
                                                     tmp_path):
        sock = str(tmp_path / "pm-repo-abc")
        result, killed = self._invoke(monkeypatch, tmp_path, (sock, True))

        assert result.exit_code == 0, result.output
        assert killed == [("pm-repo-abc~1", sock), ("pm-repo-abc", sock)]

    def test_private_kill_keeps_a_socket_a_server_still_answers_on(
            self, monkeypatch, tmp_path):
        """Same rule as the legacy branch: never unlink a live server.

        The kill removes this session's group, but a server can survive it
        (a stray or hand-made session on the same socket, or a kill that
        failed).  Removing its socket then would strand those clients.
        """
        sock = tmp_path / "pm-repo-abc"
        sock.write_text("")
        result, killed = self._invoke(monkeypatch, tmp_path,
                                      (str(sock), True), alive=True)

        assert result.exit_code == 0, result.output
        assert killed == [("pm-repo-abc~1", str(sock)),
                          ("pm-repo-abc", str(sock))]
        assert sock.exists()

    def test_private_kill_removes_the_emptied_socket(self, monkeypatch,
                                                     tmp_path):
        """The normal case: the server exited, so the file is removed."""
        sock = tmp_path / "pm-repo-abc"
        sock.write_text("")
        result, killed = self._invoke(monkeypatch, tmp_path,
                                      (str(sock), True), alive=False)

        assert result.exit_code == 0, result.output
        assert killed
        assert not sock.exists()

    def test_legacy_session_kills_on_explicit_default_socket(
            self, monkeypatch, tmp_path):
        default = str(paths.default_socket_path())
        result, killed = self._invoke(monkeypatch, tmp_path, (default, False))

        assert result.exit_code == 0, result.output
        # The default server is addressed by path, never by omitting -S.
        assert killed == [("pm-repo-abc~1", default),
                          ("pm-repo-abc", default)]

    def test_missing_session_unlinks_stale_socket(self, monkeypatch, tmp_path):
        stale = tmp_path / "pm-repo-abc"
        stale.write_text("")
        result, killed = self._invoke(monkeypatch, tmp_path, (None, False))

        assert result.exit_code == 1
        assert killed == []
        assert not stale.exists()

    def test_missing_session_keeps_a_live_socket(self, monkeypatch, tmp_path):
        """A live server may host only grouped sessions; keep its socket.

        ``find_session_server`` reports "not found" when the base session is
        gone, but the server can still be running (``pm-x~1`` survived).
        Unlinking its socket would strand every client attached to it.
        """
        sock = tmp_path / "pm-repo-abc"
        sock.write_text("")
        result, killed = self._invoke(monkeypatch, tmp_path, (None, False),
                                      alive=True)

        assert result.exit_code == 1
        assert killed == []
        assert sock.exists()

    def test_legacy_kill_keeps_a_live_private_socket(self, monkeypatch,
                                                     tmp_path):
        """Killing a default-server session must not unlink another server.

        A file at the private socket path can belong to a live server that
        hosts only grouped sessions of a different name; unlinking it would
        strand every client attached there.
        """
        private = tmp_path / "pm-repo-abc"
        private.write_text("")
        result, killed = self._invoke(
            monkeypatch, tmp_path, (str(paths.default_socket_path()), False),
            alive=True)

        assert result.exit_code == 0, result.output
        assert killed  # the legacy session was still killed
        assert private.exists()

    def test_legacy_kill_removes_a_stale_private_socket(self, monkeypatch,
                                                        tmp_path):
        stale = tmp_path / "pm-repo-abc"
        stale.write_text("")
        result, killed = self._invoke(
            monkeypatch, tmp_path, (str(paths.default_socket_path()), False),
            alive=False)

        assert result.exit_code == 0, result.output
        assert killed
        assert not stale.exists()

    def test_kills_the_ambient_session_when_the_cwd_one_is_absent(
            self, monkeypatch, tmp_path):
        """A workdir clone must kill the session that hosts it (R3.2).

        The clone's git-root hash gives a different name from the session
        it runs inside, so the cwd-derived candidate does not exist and the
        ambient session has to be chosen — and killed on its own server.
        """
        sock = str(tmp_path / "pm-ambient")
        result, killed = self._invoke(
            monkeypatch, tmp_path, (None, False),
            ambient="pm-ambient",
            hosting_for={"pm-ambient": (sock, True)},
        )

        assert result.exit_code == 0, result.output
        assert killed == [("pm-ambient~1", sock), ("pm-ambient", sock)]

    def test_ignores_an_ambient_session_this_home_does_not_know(
            self, monkeypatch, tmp_path):
        """A foreign HOME's inherited session must never be killed (R5b)."""
        foreign = str(tmp_path / "pm-live")
        result, killed = self._invoke(
            monkeypatch, tmp_path, (None, False),
            ambient=None,
            hosting_for={"pm-live": (foreign, True)},
        )

        assert result.exit_code == 1
        assert killed == []

    def test_shared_kill_never_falls_back_to_a_private_ambient(
            self, monkeypatch, tmp_path):
        """``pm session kill --global`` must not kill the private session.

        Share mode is mixed into the tag, so the shared session the user
        asked about is a *different* session from the private one hosting
        the pane.  When it is not running there is nothing to kill.
        """
        sock = str(tmp_path / "pm-ambient")
        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        result, killed = self._invoke(
            monkeypatch, tmp_path, (None, False),
            ambient="pm-ambient",
            ambient_share_mode=None,        # the ambient session is private
            hosting_for={"pm-ambient": (sock, True)},
            args=("kill", "--global"),
        )

        assert result.exit_code == 1, result.output
        assert killed == []

    def test_shared_kill_still_falls_back_to_a_shared_ambient(
            self, monkeypatch, tmp_path):
        """A workdir clone inside a shared session kills that session."""
        sock = str(tmp_path / "pm-ambient")
        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        result, killed = self._invoke(
            monkeypatch, tmp_path, (None, False),
            ambient="pm-ambient",
            ambient_share_mode="global",    # same mode as --global
            hosting_for={"pm-ambient": (sock, True)},
            args=("kill", "--global"),
        )

        assert result.exit_code == 0, result.output
        assert killed == [("pm-ambient~1", sock), ("pm-ambient", sock)]


class TestResolveTargetSession:
    """``pm session kill``/``mobile`` share one candidate list."""

    def test_falls_back_to_a_known_ambient_session(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-cwd")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: "pm-ambient")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: None)
        monkeypatch.setattr(session_mod, "_pick_existing_session",
                            lambda cands: cands[-1])
        assert session_mod._resolve_target_session() == "pm-ambient"

    def test_ambient_share_mode_reads_the_session_environment(
            self, monkeypatch):
        """The mode comes from the session env, not from the name."""
        from pm_core.cli import session as session_mod

        seen: list[tuple[str, str]] = []

        def fake_env(name, key):
            seen.append((name, key))
            return "group:staff" if name == "pm-x" else None

        monkeypatch.setattr(session_mod.tmux_mod, "get_session_environment",
                            fake_env)
        assert session_mod._ambient_share_mode("pm-x") == "group:staff"
        assert seen == [("pm-x", "PM_SHARE_MODE")]

    def test_ambient_session_with_a_different_share_mode_is_ignored(
            self, monkeypatch):
        """A private ambient session is not a target for a shared kill."""
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_SHARE_MODE", "global")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-shared")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: "pm-private")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: None)
        seen: list[list[str]] = []
        monkeypatch.setattr(session_mod, "_pick_existing_session",
                            lambda cands: seen.append(cands) or cands[0])
        assert session_mod._resolve_target_session() == "pm-shared"
        assert seen == [["pm-shared"]]

    def test_never_uses_an_unknown_ambient_session(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-cwd")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: None)
        seen: list[list[str]] = []
        monkeypatch.setattr(session_mod, "_pick_existing_session",
                            lambda cands: seen.append(cands) or cands[0])
        assert session_mod._resolve_target_session() == "pm-cwd"
        assert seen == [["pm-cwd"]]

    def test_does_not_duplicate_the_cwd_candidate(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-same")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: "pm-same")
        seen: list[list[str]] = []
        monkeypatch.setattr(session_mod, "_pick_existing_session",
                            lambda cands: seen.append(cands) or cands[0])
        session_mod._resolve_target_session()
        assert seen == [["pm-same"]]


class TestSessionMobileServerSelection:
    """``pm session mobile`` must address the server hosting the session.

    The session name is the same on either server, so without selecting the
    hosting server the status query would hit the default one and report a
    live private session as "not running".
    """

    def test_status_queries_the_hosting_server(self, monkeypatch, tmp_path):
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        sock = str(tmp_path / "pm-abc")
        # Restored by monkeypatch; _use_tmux_socket assigns os.environ
        # directly, so the test must not leak it.
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(session_mod, "_resolve_target_session",
                            lambda: "pm-abc")
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (sock, True))
        monkeypatch.setattr(session_mod.pane_layout, "mobile_flag_path",
                            lambda name: tmp_path / "pm-abc.mobile")
        seen: dict[str, str | None] = {}

        def fake_session_exists(name, socket_path=None, use_env=True):
            seen["env"] = os.environ.get("PM_TMUX_SOCKET")
            return False

        monkeypatch.setattr(session_mod.tmux_mod, "session_exists",
                            fake_session_exists)

        result = CliRunner().invoke(session_mod.session, ["mobile"])

        assert result.exit_code == 0, result.output
        assert seen["env"] == sock
        assert "not running" in result.output


class TestPickExistingSession:
    def test_prefers_the_first_running_candidate(self, monkeypatch, tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(
            session_mod.tmux_mod, "session_exists",
            lambda name, socket_path=None, use_env=True:
            name == "pm-ambient" and socket_path is None and not use_env)

        assert session_mod._pick_existing_session(
            ["pm-cwd", "pm-ambient"]) == "pm-ambient"

    def test_falls_back_to_first_candidate_when_none_run(self, monkeypatch,
                                                         tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "session_exists",
                            lambda *a, **kw: False)

        assert session_mod._pick_existing_session(
            ["pm-cwd", "pm-ambient"]) == "pm-cwd"


# ---------------------------------------------------------------------------
# Regression: ambient $TMUX_PANE + a different HOME must not adopt a session
#
# A smoke test once inherited the live session's TMUX/TMUX_PANE while running
# under a temporary HOME.  The empty pane registry made `pm session` think the
# live TUI was missing, so it split a stray TUI pane into the live session's
# main window.  `_resolve_start_session_name` must only trust an ambient
# session that this HOME knows about.
# ---------------------------------------------------------------------------

class TestStartSessionName:
    def test_foreign_ambient_session_without_registry_is_ignored(
            self, monkeypatch, tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod, "_get_current_pm_session",
                            lambda: "pm-live")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-fresh")
        monkeypatch.setattr(session_mod.pane_registry, "registry_path",
                            lambda name: tmp_path / f"{name}.json")

        # Temporary HOME: no registry for the inherited session.
        assert session_mod._known_ambient_session() is None
        assert session_mod._resolve_start_session_name() == "pm-fresh"

    def test_ambient_session_with_registry_is_adopted(
            self, monkeypatch, tmp_path):
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod, "_get_current_pm_session",
                            lambda: "pm-live")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-fresh")
        monkeypatch.setattr(session_mod.pane_registry, "registry_path",
                            lambda name: tmp_path / f"{name}.json")
        (tmp_path / "pm-live.json").write_text("{}")

        assert session_mod._known_ambient_session() == "pm-live"
        assert session_mod._resolve_start_session_name() == "pm-live"

    def test_shared_start_never_adopts_a_private_ambient_session(
            self, monkeypatch, tmp_path):
        """``pm session --global`` inside a private session starts the shared one.

        Share mode is mixed into the tag, so the ambient private session is
        a different session: adopting it would attach without sharing and
        leave the socket at 0600 (observed before the share-mode check).
        """
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_SHARE_MODE", "global")
        monkeypatch.setattr(session_mod, "_get_current_pm_session",
                            lambda: "pm-live")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-shared")
        monkeypatch.setattr(session_mod.pane_registry, "registry_path",
                            lambda name: tmp_path / f"{name}.json")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: None)      # private session
        (tmp_path / "pm-live.json").write_text("{}")

        assert session_mod._resolve_start_session_name(shared=True) == "pm-shared"

    def test_shared_start_reuses_a_shared_ambient_session(
            self, monkeypatch, tmp_path):
        """A workdir clone inside a shared session reattaches to it."""
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_SHARE_MODE", "global")
        monkeypatch.setattr(session_mod, "_get_current_pm_session",
                            lambda: "pm-live")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-clone")
        monkeypatch.setattr(session_mod.pane_registry, "registry_path",
                            lambda name: tmp_path / f"{name}.json")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: "global")
        (tmp_path / "pm-live.json").write_text("{}")

        assert session_mod._resolve_start_session_name(shared=True) == "pm-live"


# ---------------------------------------------------------------------------
# TUI quit/restart use no server-wide tmux operations
# ---------------------------------------------------------------------------

class TestTuiQuitRestart:
    @patch("pm_core.tui.pane_ops.tmux_mod.detach_current_client",
           return_value=True)
    @patch("pm_core.tui.pane_ops.tmux_mod.in_tmux", return_value=True)
    def test_quit_detaches_precisely(self, _in_tmux, detach):
        from pm_core.tui import pane_ops

        app = MagicMock()
        pane_ops.quit_app(app)
        detach.assert_called_once_with()
        app.exit.assert_not_called()

    @patch("pm_core.tui.pane_ops.os.execvp")
    @patch("pm_core.tui.pane_ops.tmux_mod.detach_current_client")
    @patch("pm_core.tui.pane_ops.tmux_mod.kill_session")
    def test_restart_touches_no_tmux_sessions(self, kill, detach, _execvp):
        from pm_core.tui import pane_ops

        app = MagicMock()
        app._write_queue = None
        pane_ops.restart_app(app)
        detach.assert_not_called()
        kill.assert_not_called()


# ---------------------------------------------------------------------------
# CLI: `pm session --print-connect`
# ---------------------------------------------------------------------------

class TestPrintConnect:
    def _invoke(self, monkeypatch, tmp_path, hosting):
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        # ``shared`` reflects --global/--group; this invocation passes none.
        monkeypatch.setattr(session_mod, "_resolve_start_session_name",
                            lambda shared=False: "pm-repo-abc")
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: hosting)
        return CliRunner().invoke(session_mod.session, ["--print-connect"])

    def test_private_session_prints_socket_command(self, monkeypatch,
                                                   tmp_path):
        sock = str(tmp_path / "pm-repo-abc")
        result = self._invoke(monkeypatch, tmp_path, (sock, True))

        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"tmux -S {sock} attach"

    def test_legacy_session_prints_default_socket_attach(self, monkeypatch,
                                                         tmp_path):
        """A legacy session is named *and* its server addressed explicitly.

        A bare `tmux attach -t` follows $TMUX, so pasting it into another
        pm pane would reach that pane's private server.
        """
        default = str(paths.default_socket_path())
        result = self._invoke(monkeypatch, tmp_path, (default, False))

        assert result.exit_code == 0, result.output
        assert result.output.strip() == (
            f"tmux -S {default} attach -t pm-repo-abc")

    def test_dir_without_share_flags_is_rejected(self, monkeypatch, tmp_path):
        """`--dir` only means "join a shared session", as for `pm session`."""
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        result = CliRunner().invoke(
            session_mod.session, ["--print-connect", "--dir", str(tmp_path)])

        assert result.exit_code == 1
        assert "--dir requires --global or --group" in result.output


# ---------------------------------------------------------------------------
# CLI: `pm session list`
# ---------------------------------------------------------------------------

class TestSessionListCommand:
    def _invoke(self, monkeypatch, rows):
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(session_mod.tmux_mod, "list_pm_sessions",
                            lambda: rows)
        return CliRunner().invoke(session_mod.session, ["list"])

    def test_renders_private_legacy_and_shared_rows(self, monkeypatch):
        result = self._invoke(monkeypatch, [
            {"name": "pm-a", "socket": "/tmp/pm-sessions/pm-a",
             "attached": 2, "shared": False},
            {"name": "pm-legacy", "socket": None, "attached": 1,
             "shared": False},
            {"name": "pm-shared", "socket": "/tmp/pm-sessions/pm-shared",
             "attached": 0, "shared": True},
        ])

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0].split() == ["SESSION", "CLIENTS", "SOCKET"]
        assert "/tmp/pm-sessions/pm-a" in lines[1]
        assert "(default server)" in lines[2]
        assert "(shared)" in lines[3]

    def test_empty_listing(self, monkeypatch):
        result = self._invoke(monkeypatch, [])

        assert result.exit_code == 0, result.output
        assert "No pm sessions found." in result.output


# ---------------------------------------------------------------------------
# TUI: the connect screen names this session's server
# ---------------------------------------------------------------------------

class TestShowConnect:
    def test_private_session_shows_socket_command(self, monkeypatch):
        from pm_core.tui import pane_ops

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-x")
        app = MagicMock()
        app._session_name = "pm-x"

        pane_ops.show_connect(app)

        screen = app.push_screen.call_args[0][0]
        assert screen._command == "tmux -S /tmp/pm-sessions/pm-x attach"

    def test_legacy_session_shows_default_socket_attach(self, monkeypatch):
        from pm_core.tui import pane_ops

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(pane_ops.tmux_mod, "find_session_server",
                            lambda name: (str(paths.default_socket_path()),
                                          False))
        app = MagicMock()
        app._session_name = "pm-x"

        pane_ops.show_connect(app)

        screen = app.push_screen.call_args[0][0]
        assert screen._command == (
            f"tmux -S {paths.default_socket_path()} attach -t pm-x")

    def test_private_session_without_env_shows_its_socket(self, monkeypatch):
        """No PM_TMUX_SOCKET (e.g. a hand-started TUI): probe the server."""
        from pm_core.tui import pane_ops

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(pane_ops.tmux_mod, "find_session_server",
                            lambda name: ("/tmp/pm-sessions/pm-x", True))
        app = MagicMock()
        app._session_name = "pm-x"

        pane_ops.show_connect(app)

        screen = app.push_screen.call_args[0][0]
        assert screen._command == "tmux -S /tmp/pm-sessions/pm-x attach"

    def test_no_session_reports_instead_of_a_command(self, monkeypatch):
        from pm_core.tui import pane_ops

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        app = MagicMock()
        app._session_name = None

        pane_ops.show_connect(app)

        app.push_screen.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: disposable servers
# ---------------------------------------------------------------------------

@pytest.fixture
def short_sock_dir(tmp_path):
    """A directory short enough for AF_UNIX socket paths.

    A Unix socket path is limited to ~108 bytes; ``tmp_path`` can exceed
    that under a deep pytest root or a long user name, so fall back to a
    short disposable directory under /tmp.
    """
    if len(str(tmp_path / "pm-iso-test.sock")) <= 100:
        yield tmp_path
        return
    short = Path(tempfile.mkdtemp(prefix="pmiso-", dir="/tmp"))
    try:
        yield short
    finally:
        shutil.rmtree(short, ignore_errors=True)


def _tmux(sock, *args):
    return subprocess.run(
        ["tmux", "-S", str(sock), *args],
        capture_output=True, text=True,
    )


def _tmux_out(sock, *args) -> str:
    r = _tmux(sock, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _make_server(sock, session="pm-iso-test", hook="true"):
    r = _tmux(sock, "new-session", "-d", "-s", session, "-n", "main",
              "sleep 300")
    assert r.returncode == 0, r.stderr
    _tmux(sock, "new-window", "-d", "-t", f"{session}:", "-n", "extra",
          "sleep 300")
    _tmux(sock, "set-hook", "-g", "after-kill-pane",
          f"run-shell '{hook}'")
    return session


def _attach_client(sock, session):
    """Attach a real tmux client under a pty; return (proc, tty)."""
    proc = subprocess.Popen(
        ["script", "-qec",
         f"tmux -S {shlex.quote(str(sock))} attach -t {shlex.quote(session)}",
         "/dev/null"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        r = _tmux(sock, "list-clients", "-F", "#{client_tty}")
        if r.returncode == 0 and r.stdout.strip():
            return proc, r.stdout.strip().splitlines()[0]
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    proc.kill()
    pytest.skip("could not attach a tmux client in this environment")


def _close(proc, sock):
    """Tear down one disposable server (and its attached client, if any)."""
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    _tmux(sock, "kill-server")
    try:
        Path(sock).unlink(missing_ok=True)
    except OSError:
        pass


@pytest.mark.skipif(not tmux.has_tmux(), reason="tmux not installed")
class TestSessionStartCreatesPrivateServer:
    """R1 end to end: a new session is created on its own server.

    The manual smoke script (``pm/specs/pr-073910f/session_start_smoke.py``)
    covers this too, but nothing in the suite asserted that
    ``_session_start`` actually creates the private server and propagates
    ``PM_TMUX_SOCKET`` to every surface (the TUI command, the session
    environment, the server's global environment) while leaving the
    default server alone.
    """

    def test_session_start_wires_every_surface_to_the_private_server(
            self, short_sock_dir, tmp_path, monkeypatch):
        from pm_core.cli import session as session_mod
        from pm_core import hook_install

        # Isolated HOME so the pane registry, pidfiles and pane_layout
        # state land in tmp_path, never in the real ~/.pm.
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        # Pre-register the variables _session_start writes directly (or
        # pops) so monkeypatch restores them after the test: an untracked
        # set would leak PM_TMUX_SOCKET into every later test in the run.
        for var in ("PM_TMUX_SOCKET", "PM_SHARE_MODE"):
            monkeypatch.setenv(var, "")
        for var in ("TMUX", "TMUX_PANE", "PM_IN_TMUX_SESSION", "PM_PROJECT"):
            monkeypatch.delenv(var, raising=False)
        # A disposable socket directory and a disposable "default server":
        # the real one is never addressed.
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", short_sock_dir)
        default_sock = short_sock_dir / "default"
        monkeypatch.setattr(paths, "default_socket_path",
                            lambda: default_sock)
        monkeypatch.setattr(hook_install, "ensure_hooks_installed",
                            lambda: None)
        monkeypatch.setattr(session_mod, "state_root",
                            MagicMock(side_effect=FileNotFoundError()))
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-iso-start")

        # Keep the pane alive instead of launching a real TUI, but still
        # create it on the socket _session_start chose.
        created: dict = {}
        real_create = tmux.create_session

        def fake_create(name, cwd, cmd, socket_path=None, env=None):
            created.update(name=name, cmd=cmd, socket_path=socket_path)
            real_create(name, cwd, "sleep 300", socket_path=socket_path,
                        env=env)

        monkeypatch.setattr(tmux, "create_session", fake_create)
        attached: list[tuple[str, str | None]] = []
        monkeypatch.setattr(
            tmux, "attach",
            lambda name, socket_path=None: attached.append(
                (name, socket_path)))

        sock = str(short_sock_dir / "pm-iso-start")
        try:
            session_mod._session_start()

            # The session was created on the deterministic private socket,
            # with the socket exported into the TUI's own command.
            assert created["name"] == "pm-iso-start"
            assert created["socket_path"] == sock
            assert (f"PM_TMUX_SOCKET={shlex.quote(sock)} pm _tui"
                    in created["cmd"])
            assert os.environ["PM_TMUX_SOCKET"] == sock

            sessions = _tmux_out(sock, "list-sessions", "-F",
                                 "#{session_name}").split()
            assert "pm-iso-start" in sessions
            assert "pm-iso-start~1" in sessions

            # Every propagation surface names the private socket.
            assert _tmux_out(sock, "show-environment", "-t", "pm-iso-start",
                             "PM_TMUX_SOCKET").strip() == \
                f"PM_TMUX_SOCKET={sock}"
            assert _tmux_out(sock, "show-environment", "-g",
                             "PM_TMUX_SOCKET").strip() == \
                f"PM_TMUX_SOCKET={sock}"
            # Hooks were installed on the private server (R1 implicit).
            assert "after-kill-pane" in _tmux_out(sock, "show-hooks", "-g")

            # The client attaches to the grouped session, on that socket.
            assert attached == [("pm-iso-start~1", sock)]

            # Nothing was created on the default server.
            assert _tmux(default_sock, "has-session", "-t",
                         "pm-iso-start").returncode != 0
            assert not default_sock.exists()
        finally:
            _tmux(sock, "kill-server")
            Path(sock).unlink(missing_ok=True)


@pytest.mark.skipif(not tmux.has_tmux(), reason="tmux not installed")
class TestServerIsolationIntegration:
    def test_detach_and_cleanup_in_one_server_leaves_other_intact(
            self, short_sock_dir, monkeypatch):
        if not subprocess.run(["which", "script"],
                              capture_output=True).returncode == 0:
            pytest.skip("`script` not available for attaching a client")

        sock_a = short_sock_dir / "a.sock"
        sock_b = short_sock_dir / "b.sock"
        sess_a = _make_server(sock_a, "pm-iso-a", "true")
        sess_b = _make_server(sock_b, "pm-iso-b", "true")
        proc_a, _ = _attach_client(sock_a, sess_a)
        proc_b, _ = _attach_client(sock_b, sess_b)
        try:
            # B's state before A does anything.
            b_panes_before = _tmux_out(sock_b, "list-panes", "-a", "-F",
                                       "#{pane_id}").split()
            b_hooks_before = _tmux_out(sock_b, "show-hooks", "-g")

            # Simulate the TUI's quit (Ctrl-Q) in server A.
            pane_a = _tmux_out(sock_a, "list-panes", "-t", sess_a,
                               "-F", "#{pane_id}").split()[0]
            monkeypatch.setenv("PM_TMUX_SOCKET", str(sock_a))
            monkeypatch.setenv("TMUX_PANE", pane_a)
            assert tmux.detach_current_client() is True

            # A's client is gone; B's client is still attached.
            assert _tmux(sock_a, "list-clients", "-F", "#{client_tty}"
                         ).stdout.strip() == ""
            assert len(_tmux_out(sock_b, "list-clients", "-F",
                                 "#{client_tty}").strip().splitlines()) == 1

            # Kill A's session (cleanup path) — B is untouched.
            for g in tmux.list_grouped_sessions(sess_a,
                                                socket_path=str(sock_a)):
                tmux.kill_session(g, socket_path=str(sock_a))
            tmux.kill_session(sess_a, socket_path=str(sock_a))

            assert _tmux(sock_b, "has-session", "-t", sess_b).returncode == 0
            assert (_tmux_out(sock_b, "list-panes", "-a", "-F", "#{pane_id}")
                    .split() == b_panes_before)
            assert _tmux_out(sock_b, "show-hooks", "-g") == b_hooks_before
            assert len(_tmux_out(sock_b, "list-clients", "-F",
                                 "#{client_tty}").strip().splitlines()) == 1
        finally:
            _close(proc_a, sock_a)
            _close(proc_b, sock_b)

    def test_detach_targets_client_of_grouped_session(self, short_sock_dir,
                                                      monkeypatch):
        """The production shape: TUI in the base session, client on ``~1``.

        ``pm session`` always attaches to a grouped session, so the client
        the TUI must detach is attached to ``base~N``, not to the base
        session the TUI pane belongs to.
        """
        if not subprocess.run(["which", "script"],
                              capture_output=True).returncode == 0:
            pytest.skip("`script` not available for attaching a client")

        sock = short_sock_dir / "g.sock"
        base = _make_server(sock, "pm-iso-g")
        r = _tmux(sock, "new-session", "-d", "-t", base, "-s", f"{base}~1")
        assert r.returncode == 0, r.stderr
        proc, _ = _attach_client(sock, f"{base}~1")
        try:
            pane = _tmux_out(sock, "list-panes", "-t", base,
                             "-F", "#{pane_id}").split()[0]
            monkeypatch.setenv("PM_TMUX_SOCKET", str(sock))
            monkeypatch.setenv("TMUX_PANE", pane)

            assert tmux.detach_current_client() is True

            # The grouped client is gone; both sessions still exist.
            assert _tmux(sock, "list-clients", "-F", "#{client_tty}"
                         ).stdout.strip() == ""
            assert _tmux(sock, "has-session", "-t", base).returncode == 0
            assert _tmux(sock, "has-session",
                         "-t", f"{base}~1").returncode == 0
        finally:
            _close(proc, sock)

    def test_session_environment_comes_from_the_named_server(
            self, short_sock_dir):
        """Share mode is read from the session env, on that session's server."""
        sock = short_sock_dir / "env.sock"
        _make_server(sock, "pm-iso-env")
        try:
            assert tmux.get_session_environment(
                "pm-iso-env", "PM_SHARE_MODE", socket_path=str(sock)) is None
            _tmux(sock, "set-environment", "-t", "pm-iso-env",
                  "PM_SHARE_MODE", "global")
            assert tmux.get_session_environment(
                "pm-iso-env", "PM_SHARE_MODE",
                socket_path=str(sock)) == "global"
        finally:
            _close(None, sock)

    def test_server_alive_distinguishes_stale_from_live(self, short_sock_dir):
        """Only a socket no server answers on may be removed."""
        sock = short_sock_dir / "alive.sock"
        assert tmux.server_alive(str(sock)) is False  # no server, no file
        _make_server(sock, "pm-iso-live")
        try:
            assert tmux.server_alive(str(sock)) is True
        finally:
            _tmux(sock, "kill-server")
        # tmux leaves the socket file behind; the server is gone.
        assert Path(sock).exists()
        assert tmux.server_alive(str(sock)) is False
        Path(sock).unlink(missing_ok=True)

    def test_hooks_are_per_server(self, short_sock_dir):
        sock_a = short_sock_dir / "a.sock"
        sock_b = short_sock_dir / "b.sock"
        _make_server(sock_a, "pm-iso-a", "true")
        _make_server(sock_b, "pm-iso-b", "false")
        try:
            hooks_a = _tmux_out(sock_a, "show-hooks", "-g")
            hooks_b = _tmux_out(sock_b, "show-hooks", "-g")
            # tmux strips the shell quotes when rendering show-hooks.
            assert "run-shell true" in hooks_a
            assert "run-shell false" not in hooks_a
            assert "run-shell false" in hooks_b
            assert "run-shell true" not in hooks_b
        finally:
            _close(None, sock_a)
            _close(None, sock_b)
