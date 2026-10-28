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


class TestSessionKillServerSelection:
    """``pm session kill`` must target the server that hosts the session."""

    def _invoke(self, monkeypatch, tmp_path, hosting):
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod
        from pm_core import container, push_proxy

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-repo-abc")
        monkeypatch.setattr(session_mod, "_known_ambient_session", lambda: None)
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: hosting)
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

        result = CliRunner().invoke(session_mod.session, ["kill"])
        return result, killed

    def test_private_session_kills_on_its_own_socket(self, monkeypatch,
                                                     tmp_path):
        sock = str(tmp_path / "pm-repo-abc")
        result, killed = self._invoke(monkeypatch, tmp_path, (sock, True))

        assert result.exit_code == 0, result.output
        assert killed == [("pm-repo-abc~1", sock), ("pm-repo-abc", sock)]

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
            _close(MagicMock(poll=lambda: 0), sock_a)
            _close(MagicMock(poll=lambda: 0), sock_b)
