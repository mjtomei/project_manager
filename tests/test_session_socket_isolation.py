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

    def test_tolerates_a_sticky_dir_it_does_not_own(self, tmp_path,
                                                    monkeypatch):
        """Another user's 1777 dir is usable; chmod failing is expected."""
        fake = tmp_path / "pm-sessions"
        fake.mkdir()
        fake.chmod(0o1777)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", fake)

        def _denied(self, mode):
            raise PermissionError("not the owner")

        monkeypatch.setattr(Path, "chmod", _denied)

        paths.ensure_socket_dir()  # must not raise

    def test_refuses_a_sticky_dir_it_cannot_write(self, tmp_path,
                                                  monkeypatch):
        """A sticky dir we cannot create sockets in is not usable either.

        Another user's 1755 ``/tmp/pm-sessions`` passes the sticky-bit
        test but tmux then fails to bind with an opaque error.  The
        guard's contract is "it already has the mode we need" (1777), so
        refuse here and let `pm session` report the actionable message.
        """
        fake = tmp_path / "pm-sessions"
        fake.mkdir()
        fake.chmod(0o1755)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", fake)

        def _denied(self, mode):
            raise PermissionError("not the owner")

        monkeypatch.setattr(Path, "chmod", _denied)

        with pytest.raises(PermissionError):
            paths.ensure_socket_dir()

    def test_refuses_a_non_sticky_dir_it_cannot_fix(self, tmp_path,
                                                    monkeypatch):
        """A world-writable dir without the sticky bit is not safe to use.

        Any user could unlink another user's socket there, which the
        per-socket uid check on `pm session` start cannot prevent (it runs
        once, before tmux binds).  Fail closed instead of proceeding.
        """
        fake = tmp_path / "pm-sessions"
        fake.mkdir()
        fake.chmod(0o777)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", fake)

        def _denied(self, mode):
            raise PermissionError("not the owner")

        monkeypatch.setattr(Path, "chmod", _denied)

        with pytest.raises(PermissionError):
            paths.ensure_socket_dir()

    def test_refuses_a_symlinked_socket_dir(self, tmp_path, monkeypatch):
        """A link at the well-known path is refused, not followed.

        ``/tmp`` is world-writable, so another local user can plant
        ``/tmp/pm-sessions`` as a symlink to a 1777 directory they own.
        The ``chmod`` then fails (we are not the target's owner), and the
        old mode fallback used ``stat`` — the *target's* mode — and
        accepted it, so every socket pm bound lived in a directory whose
        owner can unlink it (the sticky bit does not protect a file from
        the directory's owner) and could be replaced by their own server.
        pm always creates a real directory, so a link is never ours: refuse
        it even when its target happens to be ours and 1777.
        """
        real = tmp_path / "attacker"
        real.mkdir()
        real.chmod(0o1777)
        fake = tmp_path / "pm-sessions"
        fake.symlink_to(real)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", fake)

        with pytest.raises(OSError) as exc:
            paths.ensure_socket_dir()

        assert "symbolic link" in str(exc.value)
        # Nothing was created through the link.
        assert list(real.iterdir()) == []


# ---------------------------------------------------------------------------
# tmux: session name -> socket path
# ---------------------------------------------------------------------------

class TestSessionSocketFor:
    """One definition of "the socket of this session" (tmux.session_socket_for).

    The three call sites that derive a session's socket from its name
    (`_resolve_session_socket`, `--print-connect`, `session kill`) and
    `find_session_server`'s private probe all use it, so they cannot drift
    apart the way the "which server hosts this session" lookups once did.
    """

    def test_derives_from_the_session_tag(self):
        assert (tmux.session_socket_for("pm-repo-abcd1234")
                == str(paths.session_socket_path("repo-abcd1234")))

    def test_strips_a_grouped_suffix(self):
        """A grouped view resolves to the base session's server."""
        assert (tmux.session_socket_for("pm-repo-abcd1234~3")
                == tmux.session_socket_for("pm-repo-abcd1234"))

    def test_long_names_use_the_hashed_path(self):
        sock = tmux.session_socket_for("pm-" + "x" * 200)
        assert len(sock) <= 100
        assert sock.startswith(str(paths.SHARED_SOCKET_DIR / "pm-"))


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

    def test_pm_only_false_accepts_any_server(self, tmp_path):
        """A caller that already identified a pm session needs its server.

        A legacy session's panes carry no ``PM_TMUX_SOCKET`` and its server
        is the default one, so discovery must be able to resolve it from
        ``$TMUX`` to scope its scan (review-loop b48f i6).
        """
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path / "pm-sessions"):
            env = {"TMUX": "/tmp/tmux-1000/default,1234,0"}
            assert tmux.socket_path_from_tmux_env(env, pm_only=False) == \
                "/tmp/tmux-1000/default"
            assert tmux.resolve_ambient_socket(env, pm_only=False) == \
                "/tmp/tmux-1000/default"

    def test_pm_only_false_keeps_the_explicit_socket(self, tmp_path):
        with patch.object(paths, "SHARED_SOCKET_DIR", tmp_path):
            env = {"PM_TMUX_SOCKET": "/explicit",
                   "TMUX": "/tmp/tmux-1000/default,1,0"}
            assert tmux.resolve_ambient_socket(env, pm_only=False) == "/explicit"

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

    @staticmethod
    def _pane_session_fake(calls, name, group, attached="1"):
        """Fake subprocess.run for a pane reported as ``name`` in ``group``."""
        class _Result:
            def __init__(self, stdout):
                self.returncode = 0
                self.stdout = stdout

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            fmt = cmd[-1]
            if fmt == "#{session_name}:#{session_group}":
                return _Result(f"{name}:{group}\n")
            if fmt == "#{session_attached}":
                return _Result(f"{attached}\n")
            return _Result("pm-x 1\n")

        return fake_run

    def test_switches_the_users_own_view(self, monkeypatch):
        """A pane in a shared window reports the *view's* name (S124).

        tmux names the most recently active session of a shared window, so
        with the user attached through their own view the pane reads
        ``zview``, not ``pm-x``.  The name test missed it and switched the
        base session's window instead — which the user's client does not
        follow (each session in a group keeps its own current window) — so
        the QA status pane could not bring its window forward.  The
        session group identifies the view as this session.
        """
        qa_status = self._module()
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-x")
        calls: list[list[str]] = []

        monkeypatch.setattr(qa_status.subprocess, "run",
                            self._pane_session_fake(calls, "zview", "pm-x"))
        qa_status._switch_to_window("pm-x", "main")

        assert calls[-1][3:] == ["select-window", "-t", "zview:main"]

    def test_ignores_a_pane_in_another_sessions_group(self, monkeypatch):
        """A view of a *different* session must not be switched."""
        qa_status = self._module()
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-x")
        calls: list[list[str]] = []

        monkeypatch.setattr(qa_status.subprocess, "run",
                            self._pane_session_fake(calls, "zview", "pm-other"))
        qa_status._switch_to_window("pm-x", "main")

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


class TestDefaultSocketPath:
    """The default server's path must match where tmux actually puts it.

    tmux uses ``$TMUX_TMPDIR`` only when it is an absolute path to an
    existing directory; a missing or relative value makes it put the
    default server at ``/tmp/tmux-<uid>/default`` (verified on tmux 3.2a).
    Computing the value verbatim would look for legacy pre-isolation
    sessions where no server ever lives, so `pm session` would start a
    duplicate private session, and `pm session kill` / `list` would not
    see the legacy one (review-loop b48f i7).
    """

    @staticmethod
    def _expected(base: Path) -> Path:
        return base / f"tmux-{os.getuid()}" / "default"

    def test_uses_an_existing_absolute_tmux_tmpdir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))
        assert paths.default_socket_path() == self._expected(tmp_path)

    def test_falls_back_when_the_directory_does_not_exist(
            self, monkeypatch, tmp_path):
        monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "missing"))
        assert paths.default_socket_path() == self._expected(Path("/tmp"))

    def test_falls_back_for_a_relative_value(self, monkeypatch):
        monkeypatch.setenv("TMUX_TMPDIR", "relative")
        assert paths.default_socket_path() == self._expected(Path("/tmp"))

    def test_falls_back_when_unset_or_empty(self, monkeypatch):
        for value in (None, ""):
            if value is None:
                monkeypatch.delenv("TMUX_TMPDIR", raising=False)
            else:
                monkeypatch.setenv("TMUX_TMPDIR", value)
            assert paths.default_socket_path() == self._expected(Path("/tmp"))


class TestSharedSocketDirIsUsable:
    """The read-path counterpart of ``ensure_socket_dir``'s refusals.

    ``/tmp`` is world-writable, so another local user can plant the
    well-known path.  A caller that only *resolves* a socket (discovery,
    ``--print-connect``, ``pm session kill``) must not follow it: the
    target's owner would decide which servers look like pm sessions.
    """

    def test_missing_directory_is_the_normal_first_run_state(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path / "absent")
        assert paths.shared_socket_dir_is_usable() is True

    def test_real_directory_is_usable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        assert paths.shared_socket_dir_is_usable() is True

    def test_symlink_to_a_directory_is_not_usable(self, monkeypatch, tmp_path):
        real = tmp_path / "elsewhere"
        real.mkdir()
        link = tmp_path / "pm-sessions"
        link.symlink_to(real)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", link)
        assert paths.shared_socket_dir_is_usable() is False

    def test_regular_file_is_not_usable(self, monkeypatch, tmp_path):
        entry = tmp_path / "pm-sessions"
        entry.write_text("")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", entry)
        assert paths.shared_socket_dir_is_usable() is False


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

    def test_does_not_probe_a_symlink_at_the_socket_path(
            self, monkeypatch, tmp_path):
        """A planted link is skipped, not followed.

        ``/tmp/pm-sessions`` is world-writable, so another user can create
        the deterministic path as a symlink to a server they run before
        ours exists; ``tmux -S <link>`` follows it, so probing would adopt
        their server — and discovery, ``pm session --print-connect`` and
        ``pm session kill`` all resolve through here.  The listing already
        skips non-socket entries; this is the single-entry probe
        (review-loop b48f i7).
        """
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        link = tmp_path / "pm-repo-abc"
        link.symlink_to(tmp_path / "attacker-server")
        monkeypatch.setattr(
            tmux, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path == str(link))

        assert tmux.find_session_server("pm-repo-abc") == (None, False)

    def test_symlinked_socket_dir_is_not_probed(self, monkeypatch, tmp_path):
        """A symlinked socket *directory* hides its servers from discovery.

        ``/tmp`` is world-writable, so another user can create
        ``/tmp/pm-sessions`` as a link to a directory they own and run a
        server there under a pm session's deterministic socket name.
        ``pm session`` refuses the directory outright
        (``paths.ensure_socket_dir``, review-loop 2caf i8) and
        ``pm session list`` will not enumerate it (2caf i10); the
        single-entry read path must fail closed the same way — probe
        nothing through the link and fall back to the default server —
        or discovery would adopt their server and hand its TUI pane to
        ``pm tui send`` (QA scenario 17).
        """
        real = tmp_path / "elsewhere"
        real.mkdir()
        # A *real* socket at the deterministic name, so the per-entry check
        # (which skips non-sockets) would pass and only the directory guard
        # can stop the probe.
        planted = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            planted.bind(str(real / "pm-repo-abc"))
        finally:
            planted.close()
        link = tmp_path / "pm-sessions"
        link.symlink_to(real)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", link)
        probed: list[str | None] = []

        def exists(name, socket_path=None, use_env=True):
            probed.append(socket_path)
            # Only the explicit default server answers.
            return socket_path is None and not use_env

        monkeypatch.setattr(tmux, "session_exists", exists)

        sock, private = tmux.find_session_server("pm-repo-abc")
        # The private path was never probed through the link; the answer
        # comes from the default server.
        assert probed == [None]
        assert (sock, private) == (str(paths.default_socket_path()), False)

    @staticmethod
    def _prefix_matching_exists(alive: set[str]):
        """Emulate tmux target resolution: a bare name is a prefix match,
        ``=name`` is exact."""
        def exists(name, socket_path=None, use_env=True):
            exact = name.startswith("=")
            n = name[1:] if exact else name
            if exact:
                return n in alive
            return any(a.startswith(n) for a in alive)
        return exists

    def test_discovery_still_prefix_matches_a_surviving_group(
            self, monkeypatch, tmp_path):
        """Discovery keeps tmux's prefix rule: the group shares the panes.

        `pm tui view -s pm-x` should still reach the TUI after the base was
        killed elsewhere, so `find_session_server` must accept ``pm-x~1``
        for ``pm-x``.
        """
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(tmux, "session_exists",
                            self._prefix_matching_exists({"pm-repo-abc~1"}))
        sock, private = tmux.find_session_server("pm-repo-abc")
        assert (sock, private) == (str(tmp_path / "pm-repo-abc"), True)

    def test_exact_match_rejects_a_surviving_group(self, monkeypatch,
                                                   tmp_path):
        """A surviving ``pm-x~1`` must not make ``pm-x`` look alive to kill.

        ``tmux has-session -t pm-x`` also matches ``pm-x~1``.  With prefix
        matching, `pm session kill` found the "session", killed the grouped
        session (detaching its client) and unlinked a live server's socket
        when the base had already been killed elsewhere — R8 requires "no
        session found" and leaves the server alone.
        """
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(tmux, "session_exists",
                            self._prefix_matching_exists({"pm-repo-abc~1"}))
        assert tmux.find_exact_session_server("pm-repo-abc") == (None, False)

    def test_exact_match_accepts_the_session_itself(self, monkeypatch,
                                                    tmp_path):
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(tmux, "session_exists",
                            self._prefix_matching_exists({"pm-repo-abc"}))
        sock, private = tmux.find_exact_session_server("pm-repo-abc")
        assert (sock, private) == (str(tmp_path / "pm-repo-abc"), True)

    def test_does_not_probe_a_symlinked_socket_dir(self, monkeypatch,
                                                   tmp_path):
        """Discovery must not follow a planted ``/tmp/pm-sessions`` symlink.

        ``/tmp`` is world-writable, so another local user can create the
        well-known path as a link to a directory they own and run a server
        there under a pm session's *own* deterministic socket name.  The
        create path refuses the link (``ensure_socket_dir``); resolving a
        socket must too, or `pm tui view` adopts the planted TUI.
        """
        target = tmp_path / "attacker"
        target.mkdir()
        (target / "pm-repo-abc").write_text("")  # planted socket file
        link = tmp_path / "pm-sessions"
        link.symlink_to(target)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", link)

        probes: list[str | None] = []

        def exists(name, socket_path=None, use_env=True):
            probes.append(socket_path)
            # A server answers at the planted path; the default server is
            # empty.
            return socket_path is not None

        monkeypatch.setattr(tmux, "session_exists", exists)

        assert tmux.find_session_server("pm-repo-abc") == (None, False)
        # Only the default-server probe ran: the private socket inside the
        # linked directory was never contacted.
        assert probes == [None]

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
    def test_resolves_the_pm_base_through_the_session_group(
            self, mock_run, monkeypatch):
        """A user's own grouped view must not become the detach base.

        tmux reports the most recently active view's name for a pane in a
        shared window, and S118/S121/S124 let that view be named anything
        (here ``myview``).  Splitting the name at ``~`` would take
        ``myview`` for the base, so only that view's client would be a
        candidate: the client that pressed Ctrl-Q (attached to ``pm-x~1``
        and viewing the TUI window) would stay attached while the view's
        client was dropped.  ``#{session_group}`` names the pm base in
        both cases, which is the candidate set R5.2 defines (base +
        ``base~N``).
        """
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "#{session_group}" in cmd:
                target = cmd[cmd.index("-t") + 1]
                return MagicMock(
                    returncode=0,
                    stdout="pm-x\n" if target in ("=myview:", "=pm-x~1:")
                    else "")
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\npm-x~1\n")
            if "list-clients" in cmd:
                # The view's client is the most recently active one; the
                # client that pressed Ctrl-Q is the ~1 one.
                return MagicMock(
                    returncode=0,
                    stdout="/dev/pts/9|900|90|myview\n"
                           "/dev/pts/1|100|10|pm-x~1\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{window_id}" in cmd:
                return MagicMock(returncode=0, stdout="@1\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="myview\n")
            return MagicMock(returncode=0, stdout="0\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-1] == "/dev/pts/1"

    @patch("pm_core.tmux.subprocess.run")
    def test_falls_back_to_one_group_client(self, mock_run, monkeypatch):
        """No client views the TUI window: detach one group client by TTY.

        The client is attached to a grouped session whose active window is
        a *different* window (e.g. a review window), so the precise
        per-window match finds nothing and the group fallback has to fire.
        It must still name a single client: ``detach-client -s <session>``
        would drop every client of that session.
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
        assert detaches[0][-2:] == ["-t", "/dev/pts/1"]

    @patch("pm_core.tmux.subprocess.run")
    def test_two_clients_on_the_base_lose_only_one(self, mock_run,
                                                   monkeypatch):
        """One Ctrl-Q must never detach two clients of the same session.

        Both clients are attached to the base session while the base's
        current window is a shell window (so neither "views the TUI
        window").  The old fallback ran ``detach-client -s pm-x``, which
        drops *every* client of that session — both lost their terminal on
        one Ctrl-Q.  The fallback must pick one TTY.
        """
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "list-sessions" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-clients" in cmd:
                return MagicMock(
                    returncode=0,
                    stdout="/dev/pts/1|100|10|pm-x\n"
                           "/dev/pts/2|200|20|pm-x\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{window_id}" in cmd:
                # The TUI pane lives in @1; the base session's current
                # window is the shell window @5.
                target = cmd[cmd.index("-t") + 1]
                return MagicMock(returncode=0,
                                 stdout="@1\n" if target == "%7" else "@5\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-2:] == ["-t", "/dev/pts/2"]
        assert "-s" not in detaches[0]

    @patch("pm_core.tmux.subprocess.run")
    def test_failed_detach_is_not_reported_as_success(self, mock_run,
                                                      monkeypatch):
        """A non-zero detach-client must not be claimed as a detach.

        The fake must resolve the session *group* (``#{session_group}``) to
        ``pm-x``, not leave it to the generic fallback: with a different
        base the client is not a candidate, nothing is detached, and the
        test would pass without ever reaching the failure branch it is
        named for.
        """
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
            if "#{session_group}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "#{window_id}" in cmd:
                return MagicMock(returncode=0, stdout="@1\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            return MagicMock(returncode=0, stdout="0\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is False

        # The detach was actually attempted (and rejected) — that is the
        # branch under test.
        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-2:] == ["-t", "/dev/pts/1"]

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
            if "#{session_group}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
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
            if "#{session_group}" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            return MagicMock(returncode=0, stdout="@1\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

    @patch("pm_core.tmux.subprocess.run")
    def test_detaches_a_client_viewing_through_the_users_own_view(
            self, mock_run, monkeypatch):
        """Ctrl-Q in a user's own view must detach that client.

        A view created with ``tmux new-session -t pm-x -s myview``
        (S118/S121/S124) shares the TUI window, so its client is the one
        viewing the TUI — but its name is neither the base nor ``pm-x~N``.
        Enumerating candidates by name found none and the key did nothing
        (with other clients attached it detached a *different* client of
        the same session).  Membership comes from tmux's session group.
        """
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "list-sessions" in cmd:
                if any("#{session_group}" in a for a in cmd):
                    return MagicMock(returncode=0,
                                     stdout="pm-x:pm-x\nmyview:pm-x\n")
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "list-clients" in cmd:
                return MagicMock(returncode=0,
                                 stdout="/dev/pts/9|900|90|myview\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{session_group}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="myview\n")
            return MagicMock(returncode=0, stdout="@1\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-2:] == ["-t", "/dev/pts/9"]

    @patch("pm_core.tmux.subprocess.run")
    def test_view_client_viewing_the_tui_wins_over_other_group_clients(
            self, mock_run, monkeypatch):
        """The view's client is chosen when it is the one viewing the TUI."""
        monkeypatch.setenv("TMUX_PANE", "%7")
        monkeypatch.setenv("PM_TMUX_SOCKET", "")

        def fake_run(cmd, **kwargs):
            if "list-sessions" in cmd:
                if any("#{session_group}" in a for a in cmd):
                    return MagicMock(
                        returncode=0,
                        stdout="pm-x:pm-x\npm-x~1:pm-x\nmyview:pm-x\n")
                return MagicMock(returncode=0, stdout="pm-x\npm-x~1\n")
            if "list-clients" in cmd:
                # The view's client views the TUI window (@1); the ~1
                # client is more recently active but views @2.
                return MagicMock(
                    returncode=0,
                    stdout="/dev/pts/9|100|10|myview\n"
                           "/dev/pts/1|900|90|pm-x~1\n")
            if "detach-client" in cmd:
                return MagicMock(returncode=0, stdout="")
            if "#{session_group}" in cmd:
                return MagicMock(returncode=0, stdout="pm-x\n")
            if "#{session_name}" in cmd:
                return MagicMock(returncode=0, stdout="myview\n")
            if "#{window_id}" in cmd:
                target = cmd[cmd.index("-t") + 1]
                return MagicMock(returncode=0,
                                 stdout="@1\n" if target in ("%7", "myview")
                                 else "@2\n")
            return MagicMock(returncode=0, stdout="0\n")

        mock_run.side_effect = fake_run
        assert tmux.detach_current_client() is True

        detaches = [c[0][0] for c in mock_run.call_args_list
                    if "detach-client" in c[0][0]]
        assert len(detaches) == 1
        assert detaches[0][-2:] == ["-t", "/dev/pts/9"]


# ---------------------------------------------------------------------------
# tmux: session-group membership
# ---------------------------------------------------------------------------

class TestSessionsInGroup:
    @patch("pm_core.tmux.subprocess.run")
    def test_includes_a_view_named_anything(self, mock_run):
        def fake_run(cmd, **kwargs):
            if any("#{session_group}" in a for a in cmd):
                return MagicMock(
                    returncode=0,
                    stdout="pm-x:pm-x\npm-x~1:pm-x\nmyview:pm-x\nother:\n")
            return MagicMock(returncode=0, stdout="pm-x\npm-x~1\n")

        mock_run.side_effect = fake_run
        assert tmux.sessions_in_group("pm-x") == ["myview", "pm-x", "pm-x~1"]

    @patch("pm_core.tmux.subprocess.run")
    def test_includes_a_view_whose_name_contains_the_old_separator(
            self, mock_run):
        """Fields are ``:``-separated, so a ``|`` in a view's name is data.

        With the old ``|`` separator a view named ``my|view`` was split at
        its own ``|`` and its client was not a candidate for the quit key.
        """
        def fake_run(cmd, **kwargs):
            if any("#{session_group}" in a for a in cmd):
                return MagicMock(returncode=0,
                                 stdout="pm-x:pm-x\nmy|view:pm-x\n")
            return MagicMock(returncode=0, stdout="pm-x\n")

        mock_run.side_effect = fake_run
        assert tmux.sessions_in_group("pm-x") == ["my|view", "pm-x"]

    @patch("pm_core.tmux.subprocess.run")
    def test_ungrouped_session_is_alone(self, mock_run):
        def fake_run(cmd, **kwargs):
            if any("#{session_group}" in a for a in cmd):
                return MagicMock(returncode=0, stdout="pm-x:\n")
            return MagicMock(returncode=0, stdout="pm-x\n")

        mock_run.side_effect = fake_run
        assert tmux.sessions_in_group("pm-x") == ["pm-x"]

    @patch("pm_core.tmux.subprocess.run")
    def test_group_query_failure_keeps_the_named_group(self, mock_run):
        """An older/failing server still yields base + ``base~N``."""
        def fake_run(cmd, **kwargs):
            if any("#{session_group}" in a for a in cmd):
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="pm-x\npm-x~1\n")

        mock_run.side_effect = fake_run
        assert tmux.sessions_in_group("pm-x") == ["pm-x", "pm-x~1"]

    def test_tmux_missing_returns_the_base(self, monkeypatch):
        monkeypatch.setattr(tmux, "_run",
                            MagicMock(side_effect=OSError("no tmux")))
        assert tmux.sessions_in_group("pm-x") == ["pm-x"]


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
                    "pm-repo-abc:pm-repo-abc:0\n"
                    "pm-repo-abc~1:pm-repo-abc:2\n"
                ))
            if str(paths.default_socket_path()) in cmd:
                return MagicMock(returncode=0, stdout="pm-legacy-1::1\n")
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
    def test_skips_a_users_view_of_a_pm_session(self, mock_run, tmp_path):
        """A view grouped with a pm session is not a session of its own.

        S118/S121/S124 let a user's own view be named anything — including
        ``pm-laptop``, which looks like a pm session.  Listing it would
        report a phantom second session on the same socket (R3: one row
        per session), and its clients are not counted (``tmux
        list-clients`` is authoritative for a view's client).
        """
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
                    "pm-laptop:pm-repo-abc:1\n"
                    "pm-repo-abc:pm-repo-abc:0\n"
                    "pm-repo-abc~1:pm-repo-abc:2\n"
                ))
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            rows = tmux.list_pm_sessions()

        assert [r["name"] for r in rows] == ["pm-repo-abc"]
        assert rows[0]["attached"] == 2  # base + ~1; the view's client not counted

    @patch("pm_core.tmux.subprocess.run")
    def test_lists_a_session_whose_name_contains_a_pipe(self, mock_run,
                                                        tmp_path):
        """A repo directory name may contain ``|``, so a session name may.

        The old ``|``-separated query split the name at its own ``|``; the
        group field holds the same name, so ``rsplit`` did not save it and
        the live session was silently dropped from the listing.
        """
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        sock = sock_dir / "pm-my|repo-abc"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(sock))
        finally:
            s.close()

        def fake_run(cmd, **kwargs):
            if str(sock) in cmd:
                return MagicMock(returncode=0, stdout=(
                    "pm-my|repo-abc:pm-my|repo-abc:0\n"
                    "pm-my|repo-abc~1:pm-my|repo-abc:2\n"
                ))
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            rows = tmux.list_pm_sessions()

        assert [r["name"] for r in rows] == ["pm-my|repo-abc"]
        assert rows[0]["attached"] == 2

    @patch("pm_core.tmux.subprocess.run")
    def test_skips_dead_socket(self, mock_run, tmp_path):
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        (sock_dir / "pm-dead").write_text("")  # not a socket
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            assert tmux.list_pm_sessions() == []

    @patch("pm_core.tmux.subprocess.run")
    def test_skips_a_symlink_planted_in_the_socket_dir(self, mock_run,
                                                       tmp_path):
        """The 1777 socket dir must not let another user point us elsewhere.

        ``is_socket()`` follows symlinks, so a link planted at ``pm-<tag>``
        would be listed (and its mode read) as if it were one of our
        servers.  ``lstat`` sees the link itself and skips it.
        """
        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        target = tmp_path / "elsewhere"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(target))
        finally:
            s.close()
        (sock_dir / "pm-evil").symlink_to(target)

        def fake_run(cmd, **kwargs):
            if str(sock_dir / "pm-evil") in cmd:
                return MagicMock(returncode=0,
                                 stdout="pm-evil-session::1\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch.object(paths, "SHARED_SOCKET_DIR", sock_dir):
            assert tmux.list_pm_sessions() == []

    @patch("pm_core.tmux.subprocess.run")
    def test_does_not_follow_a_symlinked_socket_dir(self, mock_run, tmp_path):
        """A symlinked socket directory is refused, not enumerated.

        ``/tmp`` is world-writable, so another local user can create
        ``/tmp/pm-sessions`` as a link to a directory they own.  ``pm
        session`` refuses that outright (``ensure_socket_dir``), so the
        read path must not treat the target's servers as ours either: the
        listing would show their sessions, and discovery would scan them.
        """
        target = tmp_path / "elsewhere"
        target.mkdir(mode=0o1777)
        link = tmp_path / "pm-sessions"
        link.symlink_to(target)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(target / "pm-planted"))
        finally:
            s.close()

        def fake_run(cmd, **kwargs):
            if str(target) in " ".join(cmd):
                return MagicMock(returncode=0,
                                 stdout="pm-planted:pm-planted:1\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch.object(paths, "SHARED_SOCKET_DIR", link):
            rows = tmux.list_pm_sessions()

        # Only the default server was probed; the planted directory's
        # socket was never connected to.
        probed = [c[0][0][c[0][0].index("-S") + 1]
                  for c in mock_run.call_args_list if "-S" in c[0][0]]
        assert probed == [str(paths.default_socket_path())]
        assert rows == []

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
                                 stdout=f"{sock.name}::0\n")
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


class TestSelectSessionSocketReturnValue:
    """The return value names the server actually put in effect.

    No caller reads it today, but returning None for a *legacy* session —
    which does select the default server — invited a future caller to read
    it as "session not found".
    """

    def test_private_session_returns_its_socket(self, monkeypatch, tmp_path):
        from pm_core.cli import helpers

        # Register the variable so monkeypatch restores it: the code under
        # test writes os.environ directly, which would otherwise leak.
        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(
            helpers.tmux_mod, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path == str(tmp_path / "pm-target"))

        sock = str(tmp_path / "pm-target")
        assert helpers._select_session_socket("pm-target") == sock
        assert os.environ["PM_TMUX_SOCKET"] == sock

    def test_legacy_session_returns_the_default_server_path(self, monkeypatch):
        from pm_core.cli import helpers

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(
            helpers.tmux_mod, "session_exists",
            lambda name, socket_path=None, use_env=True:
            socket_path is None and not use_env)

        expected = str(paths.default_socket_path())
        assert helpers._select_session_socket("pm-legacy") == expected
        assert os.environ["PM_TMUX_SOCKET"] == expected

    def test_missing_session_returns_none_and_keeps_the_ambient_socket(
            self, monkeypatch):
        from pm_core.cli import helpers

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/ambient")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)

        assert helpers._select_session_socket("pm-gone") is None
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/pm-sessions/ambient"


# ---------------------------------------------------------------------------
# CLI: TUI pane discovery across servers
# ---------------------------------------------------------------------------

class TestServerOwnedByUs:
    """Discovery with no session context only scans this user's servers."""

    def test_own_and_missing_sockets_are_ours(self, tmp_path):
        from pm_core.cli import helpers

        sock = tmp_path / "pm-x"
        sock.write_text("")
        # ``None`` is the default server, which is per-uid by construction.
        assert helpers._server_owned_by_us(None) is True
        assert helpers._server_owned_by_us(str(sock)) is True
        # A row that cannot be lstat-ed must not hide the user's own
        # session: the scan already talked to that server to produce it.
        assert helpers._server_owned_by_us(str(tmp_path / "gone")) is True

    def test_another_users_socket_is_not(self, tmp_path, monkeypatch):
        from pm_core.cli import helpers

        sock = tmp_path / "pm-x"
        sock.write_text("")
        monkeypatch.setattr(helpers.os, "getuid",
                            lambda: sock.stat().st_uid + 1)
        assert helpers._server_owned_by_us(str(sock)) is False


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

    def test_does_not_resolve_through_a_symlinked_socket_dir(
            self, monkeypatch, tmp_path):
        """`pm tui view` must not drive a TUI served through a planted link.

        Regression for QA scenario 17: with ``/tmp/pm-sessions`` a symlink
        and a server planted at the victim project's *own* deterministic
        socket name, the cwd branch of ``_find_tui_pane`` selected that
        server (``_select_session_socket`` -> ``find_session_server``)
        before ``list_pm_sessions``' lstat guard applied, and returned the
        planted pane.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        target = tmp_path / "attacker"
        target.mkdir()
        planted = target / "pm-victim"
        planted.write_text("")
        link = tmp_path / "pm-sessions"
        link.symlink_to(target)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", link)

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-victim")

        def exists(name, socket_path=None, use_env=True):
            # Mimic tmux: with no explicit -S it follows PM_TMUX_SOCKET.
            if socket_path is None and use_env:
                socket_path = os.environ.get("PM_TMUX_SOCKET")
            if not socket_path:
                return False
            # The planted server answers whether it is addressed through
            # the link or by the target's own path.
            return (os.path.realpath(socket_path)
                    == os.path.realpath(str(planted)))

        monkeypatch.setattr(helpers.tmux_mod, "session_exists", exists)
        # The enumeration skips the linked directory (2caf i10).
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [])
        # The planted server has a live `pm _tui` pane; it must never be
        # reached, because no server in the linked directory is scanned.
        monkeypatch.setattr(helpers, "_live_panes_and_tuis",
                            lambda: ({}, [("%0", "pm-victim")]))
        monkeypatch.setattr(helpers, "_registry_tui_pane", lambda s: None)
        monkeypatch.setattr(pane_registry, "pm_session_name", lambda n: n)

        assert helpers._find_tui_pane() == (None, None)
        assert os.environ.get("PM_TMUX_SOCKET") != str(planted)

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

    def test_recorded_pane_probe_degrades_when_tmux_cannot_be_run(
            self, monkeypatch):
        """The recorded-pane liveness probe degrades like the rest.

        ``_registry_tui_pane`` runs in the in-tmux, cwd and scan branches.
        If ``pane_exists`` raised (tmux missing/unexecutable) an implicit
        ``pm tui view`` / ``pm autostart`` would trace back instead of
        reporting no TUI.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        # No ambient socket either, so the identified-server fallback cannot
        # make the scan query a real tmux server.
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-test")
        monkeypatch.setattr(pane_registry, "pm_session_name",
                            lambda name: "pm-test")
        monkeypatch.setattr(
            pane_registry, "load_registry",
            lambda name: {"windows": {"@1": {"panes": [
                {"id": "%6", "role": "tui"}]}}})
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists",
                            MagicMock(side_effect=OSError("no tmux")))
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

    def test_cwd_session_with_a_registered_tui_pane_is_resolved(
            self, monkeypatch):
        """The everyday `pm tui view` path: a plain shell in the project dir.

        No ambient session, the cwd-derived session is running on its own
        server, and its registry records the TUI pane.  The lookup must
        return that pane *and* leave the process addressing the cwd
        session's server — the branch that makes every session-keyed
        command work outside a pm pane.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        sock = "/tmp/pm-sessions/pm-cwd"
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-cwd")
        # The real _select_session_socket runs: it must export the cwd
        # session's socket so the registry probe and the caller's later
        # tmux calls hit that server.
        monkeypatch.setattr(helpers.tmux_mod, "find_session_server",
                            lambda name: (sock, True))
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: True)
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists",
                            lambda pane: pane == "%5")
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [])
        monkeypatch.setattr(
            pane_registry, "load_registry",
            lambda name: {"windows": {"@1": {"panes": [
                {"id": "%5", "role": "tui"}]}}})

        assert helpers._find_tui_pane() == ("%5", "pm-cwd")
        assert os.environ["PM_TMUX_SOCKET"] == sock

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
                stdout="%7:pm-target~1:pm _tui\n%8:pm-other:bash\n"))

        assert helpers._find_tui_pane() == ("%7", "pm-target")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/s"

    def test_last_resort_scans_the_ambient_server_without_a_socket_file(
            self, monkeypatch):
        """A live server can outlive its socket file; the scan must see it.

        ``list_pm_sessions`` enumerates *socket files*, so a server whose
        socket was unlinked while it kept running (an old pm's kill, or a
        cleaned ``/tmp/pm-sessions``) is invisible to it — and the
        last-resort scan exists for exactly that session when its registry
        entry is gone too (heal testing).  The ambient server is still
        known, so it has to be scanned anyway.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-a")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a")
        # No socket files left to enumerate.
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [])
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(
            helpers.subprocess, "run",
            lambda *a, **kw: MagicMock(
                returncode=0, stdout="%7:pm-a~1:pm _tui\n"))

        assert helpers._find_tui_pane() == ("%7", "pm-a")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/pm-sessions/pm-a"

    def test_last_resort_resolves_a_pane_reported_under_a_view(
            self, monkeypatch):
        """A live TUI reported under the user's view name is still ours.

        ``list-panes -a`` may name a shared pane after a view (S118/S121/
        S124) — here ``zview``, which sorts after ``pm-a`` and is the name
        the last line carries.  The scan resolves through the session
        group, so it finds the pane instead of reporting no TUI.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/pm-sessions/pm-a")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a")
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [])
        monkeypatch.setattr(helpers.tmux_mod, "session_group",
                            lambda name: "pm-a" if name == "zview" else "")
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(
            helpers.subprocess, "run",
            lambda *a, **kw: MagicMock(
                returncode=0, stdout="%7:zview:pm _tui\n"))

        assert helpers._find_tui_pane() == ("%7", "pm-a")

    def test_last_resort_scans_the_cwd_server_without_a_socket_file(
            self, monkeypatch):
        """The cwd branch's server is scanned too when its socket file is gone.

        Same gap as the ambient case above, one branch earlier: from a plain
        shell whose cwd names a live private session, `list_pm_sessions`
        cannot report a server whose socket file was removed, and the
        last-resort scan is the only way to reach a TUI whose registry entry
        is gone as well.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-b")

        def select(name):
            # What the real helper does for a session it finds on its own
            # private socket.
            os.environ["PM_TMUX_SOCKET"] = "/tmp/pm-sessions/pm-b"
            return "/tmp/pm-sessions/pm-b"

        monkeypatch.setattr(helpers, "_select_session_socket", select)
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: True)
        # No socket files left to enumerate.
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [])
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        monkeypatch.setattr(
            helpers.subprocess, "run",
            lambda *a, **kw: MagicMock(
                returncode=0, stdout="%4:pm-b~2:pm _tui\n"))

        assert helpers._find_tui_pane() == ("%4", "pm-b")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/pm-sessions/pm-b"

    def test_fallback_never_crosses_to_another_pm_session(self, monkeypatch):
        """A fallback must stay on the identified session's server.

        Pane ids are only unique per tmux server and ``pm tui send``
        delivers keys unscoped, so resolving to a *different* pm session's
        live ``pm _tui`` pane would drive the wrong TUI — the cross-session
        damage this PR exists to prevent.  Here pm-a's own TUI pane is
        unregistered (heal testing) and pm-b sorts first, so an unscoped
        scan would return pm-b's pane.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        # Empty (falsy) and restored by monkeypatch, so the socket the scan
        # selects cannot leak into the next test.
        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a~1")
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-b", "socket": "/tmp/b",
                                      "attached": 0, "shared": False},
                                     {"name": "pm-a", "socket": "/tmp/a",
                                      "attached": 0, "shared": False}])
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(
            helpers.tmux_mod, "_tmux_cmd",
            lambda *a, **kw: ["tmux", os.environ.get("PM_TMUX_SOCKET", "")])

        def fake_run(cmd, **kwargs):
            if cmd[1] == "/tmp/a":
                return MagicMock(returncode=0,
                                 stdout='%2:pm-a~1:"pm _tui"\n')
            return MagicMock(returncode=0, stdout='%1:pm-b:"pm _tui"\n')

        monkeypatch.setattr(helpers.subprocess, "run", fake_run)

        assert helpers._find_tui_pane() == ("%2", "pm-a")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/a"

    def test_cwd_session_does_not_override_the_ambient_one(self, monkeypatch):
        """Inside pm-a, another repo's running session must not be resolved.

        The cwd lookup exists for a plain shell.  Inside a pm session the
        ambient session wins: pane ids are only unique per tmux server and
        ``pm tui send`` delivers keys unscoped, so returning pm-b's pane
        here would drive the wrong TUI (and aim ``pm pr merge``'s window
        cleanup at pm-b).  Here pm-a's TUI pane is unregistered (heal
        testing) while the cwd-derived pm-b is running with a live pane.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a")
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-b")
        # pm-b *is* running, with a live registered TUI pane.
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: True)
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists", lambda p: True)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-a", "socket": "/tmp/a",
                                      "attached": 0, "shared": False}])

        def registry(name):
            if name == "pm-b":
                return {"windows": {"@1": {"panes": [
                    {"id": "%9", "role": "tui"}]}}}
            return {"windows": {}}

        monkeypatch.setattr(pane_registry, "load_registry", registry)
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **kw: MagicMock(returncode=1,
                                                       stdout=""))

        assert helpers._find_tui_pane() == (None, None)
        assert os.environ["PM_TMUX_SOCKET"] == ""

    def test_last_resort_never_crosses_sessions_on_one_server(
            self, monkeypatch):
        """A server is not a session: the default server hosts several.

        Pane ids are unique per *server*, so "some pm session on this
        server has a live ``pm _tui`` pane" is not proof that the pane is
        ours.  Legacy pm sessions all live on the default server, so from
        inside pm-a (registry entry gone, e.g. heal testing) an unscoped
        last-resort scan would return pm-b's TUI and let ``pm tui send``
        drive it — the cross-session damage this PR exists to prevent.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a")
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        # Both sessions share the legacy default server (socket None).
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-a", "socket": None,
                                      "attached": 0, "shared": False},
                                     {"name": "pm-b", "socket": None,
                                      "attached": 0, "shared": False}])
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        monkeypatch.setattr(
            helpers.subprocess, "run",
            lambda *a, **kw: MagicMock(
                returncode=0, stdout='%2:pm-b:"pm _tui"\n'))

        assert helpers._find_tui_pane() == (None, None)

    def test_unscoped_scan_skips_another_users_server(self, monkeypatch):
        """A plain shell must never auto-select another user's TUI.

        ``/tmp/pm-sessions`` is world-writable and ``--global`` sockets are
        world-accessible, so the cross-server scan can see other users'
        servers.  ``pm tui send`` delivers keys to a bare pane id, so
        resolving to a stranger's TUI would drive it — the cross-session
        damage this change exists to prevent, one level up.  A shared
        session stays reachable with an explicit ``-s`` and from inside it.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: False)
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [
            {"name": "pm-theirs", "socket": "/tmp/theirs", "attached": 1,
             "shared": True},
            {"name": "pm-mine", "socket": "/tmp/mine", "attached": 1,
             "shared": False}])
        monkeypatch.setattr(helpers, "_server_owned_by_us",
                            lambda sock: sock != "/tmp/theirs")
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        monkeypatch.setattr(
            helpers.subprocess, "run",
            lambda *a, **kw: MagicMock(
                returncode=0, stdout='%1:pm-theirs:"pm _tui"\n'
                                     '%2:pm-mine:"pm _tui"\n'))

        assert helpers._find_tui_pane() == ("%2", "pm-mine")
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/mine"

    def test_own_grouped_view_resolves_the_ambient_session(self, monkeypatch):
        """A user's own view of a pm session still identifies that session.

        tmux reports the *view's* name for a shared pane while that view's
        client is the most recently active one (S118/S121/S124), and the
        view need not be named ``pm-*``.  A raw ``pm-`` prefix test misses
        the ambient session and falls through to the unscoped cross-server
        scan, which here returns pm-b's TUI pane — the cross-session damage
        this PR exists to prevent.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.setenv("PM_TMUX_SOCKET", "")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "myview")
        # The real resolver: ``pm_session_name`` resolves the view through
        # the session group tmux reports.
        monkeypatch.setattr(helpers.tmux_mod, "session_group",
                            lambda name: "pm-a" if name == "myview" else "")
        monkeypatch.setattr(helpers.tmux_mod, "pane_exists", lambda p: True)
        # The cwd is a workdir clone, so it names a session nobody runs and
        # cannot rescue the lookup.
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-elsewhere")
        monkeypatch.setattr(helpers.tmux_mod, "session_exists",
                            lambda *a, **kw: False)
        # pm-b sorts first, so an unscoped scan returns its pane.
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions",
                            lambda: [{"name": "pm-b", "socket": "/tmp/b",
                                      "attached": 0, "shared": False},
                                     {"name": "pm-a", "socket": "/tmp/a",
                                      "attached": 0, "shared": False}])

        def registry(name):
            pane = "%2" if name == "pm-a" else "%1"
            return {"windows": {"@1": {"panes": [
                {"id": pane, "role": "tui"}]}}}

        monkeypatch.setattr(pane_registry, "load_registry", registry)
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])

        assert helpers._find_tui_pane() == ("%2", "pm-a")

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

    def test_scan_stays_on_the_identified_sessions_server(self, monkeypatch):
        """A same-named session on another server must not be scanned.

        A legacy twin of a private session (an older pm binary creates one on
        the default server, which cannot see the private server) shares the
        pane-registry key, so the recorded TUI pane id may name a live,
        unrelated pane there: pane ids are only unique per *server*.  A scan
        filtered by name alone would return that twin's pane to
        ``pm tui send`` — the cross-server confusion this change exists to
        remove.  Only the server the identified session was found on is
        eligible.
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        monkeypatch.setenv("PM_TMUX_SOCKET", "/tmp/a")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a~1")
        monkeypatch.setattr(pane_registry, "pm_session_name",
                            lambda name: "pm-a")
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        # The same session name on two servers: the private one we are in,
        # and a legacy twin on the default server.
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [
            {"name": "pm-a", "socket": "/tmp/a", "attached": 0,
             "shared": False},
            {"name": "pm-a", "socket": None, "attached": 0, "shared": False},
        ])
        monkeypatch.setattr(pane_registry, "load_registry",
                            lambda name: {"windows": {}})
        monkeypatch.setattr(helpers.tmux_mod, "_tmux_cmd",
                            lambda *a, **kw: ["tmux"])
        default = str(paths.default_socket_path())

        def fake_live():
            # Only the legacy twin has a live ``pm _tui`` pane, whose id
            # would match nothing on the private server.
            if os.environ.get("PM_TMUX_SOCKET") == default:
                return {}, [("%9", "pm-a")]
            return {}, []

        monkeypatch.setattr(helpers, "_live_panes_and_tuis", fake_live)

        assert helpers._find_tui_pane() == (None, None)
        # The failed lookup leaves the process on the server it came in on.
        assert os.environ["PM_TMUX_SOCKET"] == "/tmp/a"

    def test_legacy_ambient_session_scopes_the_scan_to_the_default_server(
            self, monkeypatch):
        """Inside a legacy session the scan must not reach a same-named twin.

        A pre-isolation session lives on the default server and its panes
        carry no ``PM_TMUX_SOCKET`` (R6.1 propagates nothing into a legacy
        session), so ``resolve_ambient_socket()`` returns None even though
        ``$TMUX`` names the server the identified session is on.  Scoping
        the fallback scan by *name* alone then lets a private twin of the
        session — same pane-registry key, and pane ids are only unique per
        server — hand its live pane back to ``pm tui send``, the
        cross-server confusion this change exists to remove (review-loop
        b48f i5 closed the mirror case, a legacy twin reached from a
        private session).
        """
        from pm_core.cli import helpers
        from pm_core import pane_registry

        default = str(paths.default_socket_path())
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setenv("TMUX", f"{default},123,0")
        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(helpers.tmux_mod, "get_session_name",
                            lambda: "pm-a~1")
        monkeypatch.setattr(pane_registry, "pm_session_name",
                            lambda name: "pm-a")
        monkeypatch.setattr(helpers, "_get_session_name_for_cwd",
                            lambda: "pm-other")
        # The same session name on two servers: the legacy one we are in,
        # and a private twin on its own socket.
        monkeypatch.setattr(helpers.tmux_mod, "list_pm_sessions", lambda: [
            {"name": "pm-a", "socket": "/tmp/pm-sessions/pm-a",
             "attached": 0, "shared": False},
            {"name": "pm-a", "socket": None, "attached": 0,
             "shared": False},
        ])
        monkeypatch.setattr(
            pane_registry, "load_registry",
            lambda name: {"windows": {"@1": {"panes": [
                {"id": "%0", "role": "tui"}]}}})

        # The recorded pane id is alive only on the private twin (pane ids
        # restart per server, so %0 exists there too).  The legacy
        # session's TUI is the unregistered %7 on the default server.
        def fake_pane_exists(pane):
            return (pane == "%0" and os.environ.get("PM_TMUX_SOCKET")
                    == "/tmp/pm-sessions/pm-a")

        def fake_live():
            if os.environ.get("PM_TMUX_SOCKET") == default:
                return {"%7": "pm-a"}, [("%7", "pm-a")]
            return {}, []

        monkeypatch.setattr(helpers.tmux_mod, "pane_exists",
                            fake_pane_exists)
        monkeypatch.setattr(helpers, "_live_panes_and_tuis", fake_live)

        assert helpers._find_tui_pane() == ("%7", "pm-a")
        assert os.environ["PM_TMUX_SOCKET"] == default


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

    def test_unusable_socket_dir_reports_the_fix(self, monkeypatch, tmp_path,
                                                 capsys):
        """A directory it cannot secure is refused with actionable advice.

        ``ensure_socket_dir`` fails closed when the shared directory is
        world-writable without the sticky bit (another user could unlink
        our socket, which the uid check cannot prevent).  ``pm session``
        must report that as a message, not a traceback.
        """
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)

        def unusable():
            raise PermissionError(13, "Operation not permitted")

        monkeypatch.setattr(paths, "ensure_socket_dir", unusable)

        with pytest.raises(SystemExit) as exc:
            session_mod._resolve_session_socket("pm-repo-abc", False)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Cannot use tmux socket directory" in err
        assert str(tmp_path) in err
        assert "sticky bit" in err

    def test_refuses_a_symlinked_socket_dir(self, monkeypatch, tmp_path,
                                            capsys):
        """A symlinked socket directory is reported, not used.

        ``/tmp`` is world-writable, so another user can plant the
        well-known path as a link to a directory they own; their directory
        owner can unlink our sockets even with the sticky bit.  Fail closed
        with the actionable message, like the other unusable-directory
        states.
        """
        from pm_core.cli import session as session_mod

        real = tmp_path / "elsewhere"
        real.mkdir()
        real.chmod(0o1777)
        link = tmp_path / "pm-sessions"
        link.symlink_to(real)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", link)

        with pytest.raises(SystemExit) as exc:
            session_mod._resolve_session_socket("pm-repo-abc", False)

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Cannot use tmux socket directory" in err
        assert "symbolic link" in err
        assert "sticky bit" in err
        assert list(real.iterdir()) == []

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
        """A symlink at the socket path is refused, not followed.

        ``/tmp/pm-sessions`` is world-writable, so another user can create
        the link before pm runs; tmux connects through it to whatever
        server it points at (and a dangling link would have pm bind a
        server socket at the attacker-chosen path).  A real socket is
        never a symlink, so the entry is refused whatever its owner —
        including the private case, where the link is owned by the *same*
        uid only if this user made it.
        """
        from pm_core.cli import session as session_mod

        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        (sock_dir / "pm-repo-abc").symlink_to(tmp_path / "attacker-chosen")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", sock_dir)
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        # The refusal must precede any server probe.
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (None, False))

        with pytest.raises(SystemExit) as exc:
            session_mod._resolve_session_socket("pm-repo-abc", False)
        assert exc.value.code == 1
        assert "PM_TMUX_SOCKET" not in os.environ
        assert not (tmp_path / "attacker-chosen").exists()

    def test_refuses_a_symlink_at_a_shared_socket_path(self, monkeypatch,
                                                       tmp_path, capsys):
        """A shared start must not connect through a planted symlink.

        The ownership check is private-only — a joiner does not own the
        sharing user's socket — so a link at a shared session's path used
        to be followed: ``pm session --global`` (or a joiner) would attach
        to the attacker's server, which then sees every key typed into the
        session.  A real socket is never a symlink, so both modes refuse
        it.
        """
        from pm_core.cli import session as session_mod

        sock_dir = tmp_path / "pm-sessions"
        sock_dir.mkdir()
        (sock_dir / "pm-repo-abc").symlink_to(tmp_path / "attacker-server")
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", sock_dir)
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (None, False))

        with pytest.raises(SystemExit) as exc:
            session_mod._resolve_session_socket("pm-repo-abc", True)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "symbolic link" in err
        assert "pm-repo-abc" in err
        assert "PM_TMUX_SOCKET" not in os.environ


class TestSessionKillServerSelection:
    """``pm session kill`` must target the server that hosts the session."""

    def _invoke(self, monkeypatch, tmp_path, hosting, *, ambient=None,
                ambient_share_mode=None, hosting_for=None, alive=False,
                args=("kill",), members=None):
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod
        from pm_core import container, push_proxy

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        # The candidate list depends on the share mode this process runs
        # under; the fixture is a plain (private) invocation.
        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
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
        # Candidate selection uses find_session_server; the kill itself uses
        # the exact-match variant (a bare target would also match a grouped
        # session).  Stub both against the same fixture.
        if hosting_for is None:
            resolver = lambda name: hosting  # noqa: E731
        else:
            # Per-name hosting, so the cwd session can be absent while the
            # ambient one is live.
            resolver = lambda name: hosting_for.get(name, (None, False))  # noqa: E731
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            resolver)
        monkeypatch.setattr(session_mod.tmux_mod, "find_exact_session_server",
                            resolver)
        killed: list[tuple[str, str | None]] = []
        # The kill enumerates the whole session group (base + ~N + a
        # user's own view); the base is killed last.  Default fixture: the
        # base and its ~1 grouped session.
        monkeypatch.setattr(
            session_mod.tmux_mod, "sessions_in_group",
            lambda name, socket_path=None: (
                list(members) if members is not None else [f"{name}~1", name]))
        monkeypatch.setattr(
            session_mod.tmux_mod, "kill_session",
            lambda name, socket_path=None, exact=False:
            killed.append((name, socket_path)))
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

    def test_requires_tmux(self, monkeypatch):
        """Without tmux nothing can be resolved or killed: say so, exit 1."""
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: False)
        resolver = MagicMock()
        monkeypatch.setattr(session_mod.tmux_mod,
                            "find_exact_session_server", resolver)

        result = CliRunner().invoke(session_mod.session, ["kill"])

        assert result.exit_code == 1
        assert "tmux is not installed." in result.output
        resolver.assert_not_called()

    def test_kill_also_tears_down_a_users_view(self, monkeypatch, tmp_path):
        """A user's own view of the session is a group member: kill it too.

        ``list_grouped_sessions`` matches ``base~N`` by name, so a view
        (``tmux new-session -t base -s myview``, S118/S121/S124) survived
        ``pm session kill``: its client stayed attached, the old TUI pane
        and the server stayed alive, and the socket could not be removed.
        The kill enumerates tmux's session *group*, so the view is torn
        down as well and nothing of the session is left behind (R8).
        """
        sock = str(tmp_path / "pm-repo-abc")
        result, killed = self._invoke(
            monkeypatch, tmp_path, (sock, True),
            members=["myview", "pm-repo-abc", "pm-repo-abc~1"])

        assert result.exit_code == 0, result.output
        assert killed == [("myview", sock), ("pm-repo-abc~1", sock),
                          ("pm-repo-abc", sock)]

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

    def test_kill_uses_the_exact_matcher_not_prefix(self, monkeypatch,
                                                    tmp_path):
        """A surviving ``pm-x~1`` must not make ``pm-x`` look killable.

        ``_invoke`` stubs ``find_session_server`` and
        ``find_exact_session_server`` with the same resolver, so it cannot
        catch a revert of the kill path to prefix matching.  Here they
        disagree the way tmux would: prefix matching finds the grouped
        session, exact matching finds nothing (QA scenario 6).
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        # A live server: the socket file must be left alone.
        monkeypatch.setattr(session_mod.tmux_mod, "server_alive",
                            lambda sock: True)
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-repo-abc")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: None)
        sock = tmp_path / "pm-repo-abc"
        sock.write_text("")
        # Prefix matching resolves the surviving grouped session ...
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (str(sock), True))
        # ... but the exact name is gone.
        monkeypatch.setattr(session_mod.tmux_mod,
                            "find_exact_session_server",
                            lambda name: (None, False))
        killed: list[tuple[str, str | None]] = []
        monkeypatch.setattr(
            session_mod.tmux_mod, "kill_session",
            lambda name, socket_path=None, exact=False:
            killed.append((name, socket_path)))

        result = CliRunner().invoke(session_mod.session, ["kill"])

        assert result.exit_code == 1
        assert "No session 'pm-repo-abc' found." in result.output
        assert killed == []          # the grouped session survives
        assert sock.exists()         # and so does its live server's socket

    def test_kill_targets_are_exact(self, monkeypatch, tmp_path):
        """The kill itself must be exact, not only the existence check.

        A bare ``kill-session -t pm-x`` is a *prefix* match.  The lookup is
        exact (``find_exact_session_server``), but if the base — or a group
        member — disappears between that lookup and the kill, tmux resolves
        the bare name to whichever remaining session starts with it
        (verified on tmux 3.2a: with only ``pm-xyz`` running,
        ``kill-session -t pm-x`` kills ``pm-xyz``).  On the legacy default
        server, which hosts every pre-isolation pm session, that can be
        another pm session's TUI: R8 requires the kill to tear down only
        the named session.
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod
        from pm_core import container, push_proxy

        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", tmp_path)
        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: True)
        # A live server: the socket file is left alone (not under test).
        monkeypatch.setattr(session_mod.tmux_mod, "server_alive",
                            lambda sock: True)
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-repo-abc")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: None)
        sock = str(tmp_path / "pm-repo-abc")
        monkeypatch.setattr(session_mod.tmux_mod,
                            "find_exact_session_server",
                            lambda name: (sock, True))
        monkeypatch.setattr(
            session_mod.tmux_mod, "sessions_in_group",
            lambda name, socket_path=None: ["myview", f"{name}~1", name])
        killed: list[tuple[str, str | None, bool]] = []
        monkeypatch.setattr(
            session_mod.tmux_mod, "kill_session",
            lambda name, socket_path=None, exact=False:
            killed.append((name, socket_path, exact)))
        monkeypatch.setattr(session_mod.pane_layout, "set_force_mobile",
                            lambda *a, **k: None)
        monkeypatch.setattr(container, "cleanup_session_containers",
                            lambda tag: 0)
        monkeypatch.setattr(push_proxy, "stop_session_proxies", lambda tag: 0)

        result = CliRunner().invoke(session_mod.session, ["kill"])

        assert result.exit_code == 0, result.output
        assert killed == [("myview", sock, True),
                          ("pm-repo-abc~1", sock, True),
                          ("pm-repo-abc", sock, True)]

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

    def test_dir_without_a_session_tag_is_refused(self, monkeypatch, tmp_path):
        """``--dir`` names the target; never fall back to the caller's cwd.

        A directory that is not a git repo has no session tag.  The old
        fallback computed the *caller's* cwd session, so a mistyped
        ``pm session kill --dir`` could kill a different project's session.
        """
        monkeypatch.setattr(
            "pm_core.paths.get_session_tag",
            lambda start_path=None, use_github_name=True: None)
        result, killed = self._invoke(monkeypatch, tmp_path, (None, False),
                                      args=("kill", "--dir", str(tmp_path)))

        assert result.exit_code == 1
        assert "Cannot determine session" in result.output
        assert killed == []

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

    def test_an_empty_share_mode_counts_as_unset(self, monkeypatch):
        """An exported empty ``PM_SHARE_MODE`` must not hide the ambient
        session.

        Every other reader of the variable tests it for truthiness (and
        ``_set_share_mode_env`` pops it when no flag is given), so ``""``
        means "private".  Comparing the raw value against the recorded
        mode made ``PM_SHARE_MODE= pm session kill`` inside a private
        session report "no session" instead of killing it.
        """
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_SHARE_MODE", "")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-cwd")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: "pm-ambient")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: None)
        seen: list[list[str]] = []
        monkeypatch.setattr(session_mod, "_pick_existing_session",
                            lambda cands: seen.append(cands) or cands[-1])
        assert session_mod._resolve_target_session() == "pm-ambient"
        assert seen == [["pm-cwd", "pm-ambient"]]

    def test_no_flag_targets_a_shared_ambient_session(self, monkeypatch):
        """A plain ``pm session kill``/``mobile`` inside a shared session
        targets that session.

        A grouped session (``base~N``) does not inherit the base session's
        environment (tmux copies no session environment into a grouped
        session), so a shell pane the user opens in the view they are
        attached to has no ``PM_SHARE_MODE``.  Treating "no mode
        requested" as "private wanted" rejected the ambient session and
        the command reported "No session found" for the session it was
        running in — while a plain ``pm session`` (see
        ``_resolve_start_session_name``) does adopt a shared ambient
        session.
        """
        from pm_core.cli import session as session_mod

        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-private-tag")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: "pm-shared-tag")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: "global")
        seen: list[list[str]] = []
        monkeypatch.setattr(session_mod, "_pick_existing_session",
                            lambda cands: seen.append(cands) or cands[-1])
        assert session_mod._resolve_target_session() == "pm-shared-tag"
        assert seen == [["pm-private-tag", "pm-shared-tag"]]

    def test_a_requested_share_mode_still_rejects_a_mismatched_ambient(
            self, monkeypatch):
        """The guard still applies when a mode *is* requested."""
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_SHARE_MODE", "group:staff")
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-shared")
        monkeypatch.setattr(session_mod, "_known_ambient_session",
                            lambda: "pm-global")
        monkeypatch.setattr(session_mod, "_ambient_share_mode",
                            lambda name: "global")
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

    def test_tmux_missing_inside_a_pane_degrades_to_no_session(
            self, monkeypatch):
        """``pm session mobile`` / ``--print-connect`` must not crash.

        ``$TMUX`` is set in a forwarded pane environment or a container
        where the tmux binary is missing; the ambient lookup then reports
        "not inside a pm session" instead of raising, like every other
        probe in the module.
        """
        from pm_core.cli import helpers

        monkeypatch.setattr(helpers.tmux_mod, "in_tmux", lambda: True)

        def missing():
            raise FileNotFoundError(2, "No such file or directory: 'tmux'")

        monkeypatch.setattr(helpers.tmux_mod, "get_session_name", missing)
        assert helpers._get_current_pm_session() is None


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

    def test_requires_tmux(self, monkeypatch):
        """Without tmux the status query has nothing to ask: say so, exit 1.

        Previously the query raised ``FileNotFoundError`` out of the command
        and the CLI's generic handler printed ``Error: [Errno 2] ... 'tmux'``
        — unlike ``pm session list`` / ``kill``, which name the remedy.
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: False)

        result = CliRunner().invoke(session_mod.session, ["mobile"])

        assert result.exit_code == 1
        assert "tmux is not installed." in result.output


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


class TestSessionIsShared:
    """Shared-ness comes from the session, not only from this call's flags.

    ``_session_start`` clears ``PM_SHARE_MODE`` when no ``--global``/
    ``--group`` was passed, yet a plain ``pm session`` may still adopt an
    already-shared ambient session.  The session environment records the
    mode at creation, so the window-size/bindings gate has to consult it —
    otherwise the grouped session such a reattach creates keeps tmux's
    default ``window-size`` and the smallest client sees a clipped layout.
    """

    def test_process_flag_is_enough(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.setenv("PM_SHARE_MODE", "global")
        monkeypatch.setattr(
            tmux, "get_session_environment",
            lambda *a, **k: pytest.fail("must not query for an explicit flag"))
        assert session_mod._session_is_shared("pm-x") is True

    def test_reads_the_session_environment(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        calls = []

        def _env(session, key, socket_path=None):
            calls.append((session, key))
            return "group:staff"

        monkeypatch.setattr(tmux, "get_session_environment", _env)
        assert session_mod._session_is_shared("pm-x") is True
        assert calls == [("pm-x", "PM_SHARE_MODE")]

    def test_private_session_is_not_shared(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        monkeypatch.setattr(tmux, "get_session_environment",
                            lambda *a, **k: None)
        assert session_mod._session_is_shared("pm-x") is False

    def test_bindings_apply_smallest_from_the_session_env(self, monkeypatch):
        """The wiring: a reattached shared session still gets the option."""
        from pm_core.cli import session as session_mod

        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        monkeypatch.setattr(tmux, "get_session_environment",
                            lambda *a, **k: "global")
        monkeypatch.setattr(tmux, "list_grouped_sessions",
                            lambda *a, **k: ["pm-x~1"])
        opts = []
        monkeypatch.setattr(
            tmux, "set_session_option",
            lambda s, opt, val, socket_path=None: opts.append((s, opt, val)))
        with patch("pm_core.cli.session.subprocess.run"):
            session_mod._register_tmux_bindings("pm-x")
        assert ("pm-x", "window-size", "smallest") in opts
        assert ("pm-x~1", "window-size", "smallest") in opts

    def test_bindings_leave_a_private_session_alone(self, monkeypatch):
        from pm_core.cli import session as session_mod

        monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        monkeypatch.setattr(tmux, "get_session_environment",
                            lambda *a, **k: None)
        opts = []
        monkeypatch.setattr(
            tmux, "set_session_option",
            lambda s, opt, val, socket_path=None: opts.append((s, opt, val)))
        with patch("pm_core.cli.session.subprocess.run"):
            session_mod._register_tmux_bindings("pm-x")
        assert opts == []


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
# TUI pane operations key the registry by the pm base, not a view name
# ---------------------------------------------------------------------------

class TestPaneOpsSessionResolution:
    """Pane launches are keyed by the pm base session.

    tmux reports the most recently created session of a shared window for a
    pane, so with a user's own view (``tmux new-session -t pm-x -s myview``,
    S118/S121/S124) the raw name is the view's.  The registry/pidfile/layout
    files are keyed by the base, so a pane launched through the raw name
    landed in a phantom ``myview.json`` registry the TUI never reads.
    """

    def _app(self, session_name=None):
        from types import SimpleNamespace

        app = SimpleNamespace(log_message=lambda *a, **k: None)
        if session_name is not None:
            app._session_name = session_name
        return app

    def test_get_session_and_window_resolves_a_users_view(self, monkeypatch):
        from pm_core.tui import pane_ops

        app = self._app("pm-base")
        monkeypatch.setattr(pane_ops.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(pane_ops.tmux_mod, "get_session_name",
                            lambda: "myview")
        seen = []

        def fake_window_id(session):
            seen.append(session)
            return "@7"

        monkeypatch.setattr(pane_ops.tmux_mod, "get_window_id",
                            fake_window_id)

        assert pane_ops.get_session_and_window(app) == ("pm-base", "@7")
        # The window still comes from the session tmux reports for the pane
        # (the user's view), so the new pane opens where the user looks.
        assert seen == ["myview"]

    def test_get_session_and_window_resolves_without_an_app_session(
            self, monkeypatch):
        from pm_core.tui import pane_ops

        app = self._app()
        monkeypatch.setattr(pane_ops.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(pane_ops.tmux_mod, "get_session_name",
                            lambda: "myview")
        monkeypatch.setattr(pane_ops.pane_registry, "pm_session_name",
                            lambda name: "pm-base")
        monkeypatch.setattr(pane_ops.tmux_mod, "get_window_id",
                            lambda session: "@7")

        assert pane_ops.get_session_and_window(app) == ("pm-base", "@7")

    def test_session_resolution_degrades_when_tmux_cannot_be_queried(
            self, monkeypatch):
        """A missing tmux must not crash a pane launch from the TUI.

        ``_pm_session_for`` asks tmux for the pane's session when the app
        has none yet; that probe has to degrade to "no session" like every
        other one in this change, not raise out of the key handler.
        """
        from pm_core.tui import pane_ops

        app = self._app()
        monkeypatch.setattr(pane_ops.tmux_mod, "get_session_name",
                            MagicMock(side_effect=OSError("no tmux")))

        assert pane_ops._pm_session_for(app) is None

    def test_session_resolution_falls_back_to_the_base_name(self, monkeypatch):
        """Without a group query, the plain base name is the best answer."""
        from pm_core.tui import pane_ops

        app = self._app()
        monkeypatch.setattr(pane_ops.pane_registry, "pm_session_name",
                            MagicMock(side_effect=OSError("no tmux")))

        assert pane_ops._pm_session_for(app, "myview") == "myview"

    def test_plan_window_registers_under_the_pm_base(self, monkeypatch):
        from pm_core.tui import pane_ops

        app = self._app("pm-base")
        app._root = None
        monkeypatch.setattr(pane_ops.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(pane_ops.tmux_mod, "get_session_name",
                            lambda: "myview")
        seen: dict[str, str] = {}
        state = {"created": False}

        def fake_find(session, name):
            # First lookup: no window yet; second: the window just created.
            return {"id": "@9"} if state["created"] else None

        def fake_new_window(session, name, cmd, cwd, switch=False):
            state["created"] = True
            seen["session"] = session
            return "%9"

        monkeypatch.setattr(pane_ops.tmux_mod, "find_window_by_name",
                            fake_find)
        monkeypatch.setattr(pane_ops.tmux_mod, "new_window_get_pane",
                            fake_new_window)
        monkeypatch.setattr(pane_ops.pane_registry, "load_registry",
                            lambda session: {"generation": "0"})
        registered: dict = {}

        def fake_register(session, window, panes):
            registered.update(session=session, window=window, panes=panes)

        monkeypatch.setattr(pane_ops.pane_layout, "register_and_rebalance",
                            fake_register)
        monkeypatch.setattr(pane_ops, "_focus_plans_window",
                            lambda app, plan_id: None)

        pane_ops._launch_in_plans_window(app, "plan-1", "less", "plan")

        assert seen["session"] == "pm-base"
        assert registered["session"] == "pm-base"

    def test_focus_plans_window_targets_the_pm_base(self, monkeypatch):
        """``select_window`` must get a real session name, not a view.

        It resolves the attached client's grouped session from the group;
        handed a view's name it would switch the view's window, which a
        client attached to ``pm-x~1`` does not follow.
        """
        from pm_core.tui import pane_ops

        app = self._app("pm-base")
        seen = []
        monkeypatch.setattr(pane_ops.tmux_mod, "in_tmux", lambda: True)
        monkeypatch.setattr(pane_ops.tmux_mod, "get_session_name",
                            lambda: "myview")
        monkeypatch.setattr(pane_ops.tmux_mod, "select_window",
                            lambda session, window: seen.append(
                                (session, window)))

        pane_ops._focus_plans_window(app, "plan-1")

        assert seen == [("pm-base", pane_ops._plans_window_name("plan-1"))]


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

    def test_dir_without_a_session_tag_is_rejected(self, monkeypatch,
                                                   tmp_path):
        """A `--dir` that names no session must not print a cwd command.

        Same refusal as `pm session kill --dir`: the flag names the target,
        so silently falling back to the caller's cwd would print a command
        for a different project's session.
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        # Record the value so the group callback's mutation is undone.
        monkeypatch.setenv("PM_SHARE_MODE", "")
        monkeypatch.setattr(paths, "get_session_tag",
                            lambda start_path=None, use_github_name=True: None)

        result = CliRunner().invoke(
            session_mod.session,
            ["--global", "--dir", str(tmp_path), "--print-connect"])

        assert result.exit_code == 1
        assert "Cannot determine session from directory" in result.output
        assert "tmux " not in result.output

    def test_dir_with_share_flags_prints_the_shared_socket(
            self, monkeypatch, tmp_path):
        """`--dir --global` prints the socket of the session it would join.

        The tag is computed from the *target* directory with the share mode
        mixed in (get_session_tag), so the command names the owner's shared
        session rather than a private session for that path.
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        sock = "/tmp/pm-sessions/pm-shared-abc12345"
        # Record the value so the group callback's mutation is undone.
        monkeypatch.setenv("PM_SHARE_MODE", "")
        seen = {}

        def fake_tag(start_path=None, use_github_name=True):
            seen["start_path"] = start_path
            seen["share_mode"] = os.environ.get("PM_SHARE_MODE")
            return "shared-abc12345"

        monkeypatch.setattr(paths, "get_session_tag", fake_tag)
        monkeypatch.setattr(session_mod.tmux_mod, "session_socket_for",
                            lambda name: sock)
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (sock, True))

        result = CliRunner().invoke(
            session_mod.session,
            ["--global", "--dir", str(tmp_path), "--print-connect"])

        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"tmux -S {sock} attach"
        assert seen["start_path"] == Path(str(tmp_path))
        assert seen["share_mode"] == "global"

    def test_global_and_group_are_mutually_exclusive(self, monkeypatch):
        """Nothing is printed for a combination `pm session` would reject."""
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        # Record the value so the group callback's mutation is undone.
        monkeypatch.setenv("PM_SHARE_MODE", "")

        result = CliRunner().invoke(
            session_mod.session,
            ["--global", "--group", "staff", "--print-connect"])

        assert result.exit_code == 1
        assert "--global and --group are mutually exclusive" in result.output
        assert "tmux " not in result.output

    def test_command_is_shell_quoted(self, monkeypatch, tmp_path):
        """The printed command must paste cleanly for a repo name with a space.

        A session tag is derived from the repo directory name, which may
        contain a space; unquoted, the pasted ``tmux -S …`` would split the
        path.  Ordinary paths are unchanged (shlex.quote leaves them bare).
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        sock = "/tmp/pm-sessions/pm-my repo-abc12345"
        monkeypatch.setattr(session_mod, "_resolve_start_session_name",
                            lambda shared=False: "pm-my repo-abc12345")
        monkeypatch.setattr(session_mod.tmux_mod, "session_socket_for",
                            lambda name: sock)
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (sock, True))

        result = CliRunner().invoke(session_mod.session, ["--print-connect"])

        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"tmux -S '{sock}' attach"

    def test_legacy_command_quotes_a_session_name_with_a_space(
            self, monkeypatch, tmp_path):
        """The legacy form names the session with ``-t``; quote that too.

        The session name is derived from the repo directory name, so it
        may contain a space.  ``shlex.quote`` leaves ordinary names bare,
        so the existing exact-output assertions still hold.
        """
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        default = str(paths.default_socket_path())
        monkeypatch.setattr(session_mod, "_resolve_start_session_name",
                            lambda shared=False: "pm-my repo-abc12345")
        monkeypatch.setattr(
            session_mod.tmux_mod, "session_socket_for",
            lambda name: "/tmp/pm-sessions/pm-my repo-abc12345")
        monkeypatch.setattr(session_mod.tmux_mod, "find_session_server",
                            lambda name: (default, False))

        result = CliRunner().invoke(session_mod.session, ["--print-connect"])

        assert result.exit_code == 0, result.output
        assert result.output.strip() == (
            f"tmux -S {default} attach -t 'pm-my repo-abc12345'")


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

    def test_requires_tmux(self, monkeypatch):
        """Without tmux there is nothing to enumerate: say so, exit 1."""
        from click.testing import CliRunner
        from pm_core.cli import session as session_mod

        monkeypatch.setattr(session_mod.tmux_mod, "has_tmux", lambda: False)

        result = CliRunner().invoke(session_mod.session, ["list"])

        assert result.exit_code == 1
        assert "tmux is not installed." in result.output


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

    def test_legacy_session_with_the_default_socket_in_the_env(self,
                                                               monkeypatch):
        """The rollout path exports the default socket for a legacy session.

        That skips the no-env probe, so the session must still be named:
        one default server can host several legacy pm sessions.
        """
        from pm_core.tui import pane_ops

        monkeypatch.setenv("PM_TMUX_SOCKET",
                           str(paths.default_socket_path()))
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

    def test_command_is_shell_quoted(self, monkeypatch):
        """The modal shows a command that pastes cleanly (repo names may
        contain a space); ordinary paths stay unquoted."""
        from pm_core.tui import pane_ops

        monkeypatch.setenv("PM_TMUX_SOCKET",
                           "/tmp/pm-sessions/pm-my repo-abc12345")
        app = MagicMock()
        app._session_name = "pm-my repo-abc12345"

        pane_ops.show_connect(app)

        screen = app.push_screen.call_args[0][0]
        assert screen._command == (
            "tmux -S '/tmp/pm-sessions/pm-my repo-abc12345' attach")

    def test_legacy_command_quotes_a_session_name_with_a_space(
            self, monkeypatch):
        """The connect popup's legacy form quotes the ``-t`` name too.

        The popup tells the user what to paste, so a session name with a
        space must not split into two arguments.
        """
        from pm_core.tui import pane_ops

        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        default = str(paths.default_socket_path())
        monkeypatch.setattr(pane_ops.tmux_mod, "find_session_server",
                            lambda name: (default, False))
        app = MagicMock()
        app._session_name = "pm-my repo-abc12345"

        pane_ops.show_connect(app)

        screen = app.push_screen.call_args[0][0]
        assert screen._command == (
            f"tmux -S {default} attach -t 'pm-my repo-abc12345'")


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
class TestSessionStartAttachesToLegacySession:
    """R6.1 / acceptance 4: a pre-isolation session is attached, not migrated.

    ``TestResolveSessionSocket`` covers the legacy *decision*; nothing ran
    ``_session_start`` itself against a legacy session, so the two halves
    that matter to the user — "no private session is created" and "the
    legacy session and its grouped sessions are neither killed nor moved" —
    were only asserted piecemeal.
    """

    def test_attaches_to_the_legacy_session_without_creating_a_private_one(
            self, short_sock_dir, tmp_path, monkeypatch, capsys):
        from pm_core.cli import session as session_mod
        from pm_core import hook_install, pane_registry

        # Isolated HOME so the pane registry and pane_layout state land in
        # tmp_path, never in the real ~/.pm.
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        # Track the variables _session_start writes directly (or pops) so
        # monkeypatch restores them after the test, and keep them out of the
        # disposable server's inherited environment so the global-env
        # assertions below mean what they say.
        for var in ("PM_TMUX_SOCKET", "PM_SHARE_MODE", "TMUX", "TMUX_PANE",
                    "PM_IN_TMUX_SESSION", "PM_PROJECT"):
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
                            lambda: "pm-iso-legacy")
        # The rebalance helper spawns a detached process, and attach needs a
        # client tty; neither is what this test is about.
        monkeypatch.setattr(session_mod, "_schedule_rebalance",
                            lambda name: None)
        attached: list[tuple[str, str | None]] = []
        monkeypatch.setattr(
            tmux, "attach",
            lambda name, socket_path=None: attached.append(
                (name, socket_path)))

        private_sock = short_sock_dir / "pm-iso-legacy"
        try:
            # The pre-isolation session lives on the disposable default
            # server, with its TUI pane registered so the "TUI missing"
            # heal path does not fire (it would respawn a pane instead of
            # exercising the attach).
            _make_server(default_sock, session="pm-iso-legacy")
            window_id = _tmux_out(default_sock, "display-message", "-p", "-t",
                                  "pm-iso-legacy", "#{window_id}").strip()
            tui_pane = _tmux_out(default_sock, "list-panes", "-t",
                                 "pm-iso-legacy:0", "-F",
                                 "#{pane_id}").strip()
            pane_registry.register_pane("pm-iso-legacy", window_id, tui_pane,
                                        "tui", "pm _tui")

            session_mod._session_start()

            out = capsys.readouterr().out
            # The rollout note explains the state and the migration route.
            assert "started before per-session tmux servers" in out
            assert "pm session kill" in out

            # The process addresses the default server *explicitly*: with no
            # ``-S`` the tmux binary follows ``$TMUX``, and from inside
            # another pm pane that names that session's private server — the
            # legacy session would look missing and be duplicated on the
            # wrong server (R6.1).
            assert os.environ["PM_TMUX_SOCKET"] == str(default_sock)

            # The client attaches to a grouped session of the legacy
            # session, created on the default server.
            assert attached == [("pm-iso-legacy~1", None)]
            sessions = _tmux_out(default_sock, "list-sessions", "-F",
                                 "#{session_name}").split()
            assert "pm-iso-legacy" in sessions
            assert "pm-iso-legacy~1" in sessions

            # Nothing was migrated: no private socket, no private server,
            # and neither the session nor the server environment was given
            # a PM_TMUX_SOCKET (``socket_path`` is None for a legacy
            # session, so nothing is propagated into it).
            assert not private_sock.exists()
            assert _tmux(default_sock, "show-environment", "-t",
                         "pm-iso-legacy", "PM_TMUX_SOCKET").returncode != 0
            assert _tmux(default_sock, "show-environment", "-g",
                         "PM_TMUX_SOCKET").returncode != 0
        finally:
            _tmux(default_sock, "kill-server")
            Path(default_sock).unlink(missing_ok=True)

    def test_a_vanished_legacy_session_is_created_on_its_private_socket(
            self, short_sock_dir, tmp_path, monkeypatch, capsys):
        """R6.1's lookup is a snapshot; the create path must not inherit it.

        The rollout check runs ``find_session_server`` and then, a moment
        later, asks whether the session is running.  A concurrent
        ``pm session kill`` (or anything else removing the legacy session)
        can make the second answer "no" while the process is still pointed
        at the *default* server.  Creating there would leave a brand-new
        session outside its own server (R1), and every later ``pm session``
        would see it as legacy again.  The vanished case re-resolves, so
        the session is created on its deterministic private socket and no
        rollout note is printed for a session that does not exist.
        """
        from pm_core.cli import session as session_mod
        from pm_core import hook_install

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        for var in ("PM_TMUX_SOCKET", "PM_SHARE_MODE", "TMUX", "TMUX_PANE",
                    "PM_IN_TMUX_SESSION", "PM_PROJECT"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(paths, "SHARED_SOCKET_DIR", short_sock_dir)
        default_sock = short_sock_dir / "default"
        monkeypatch.setattr(paths, "default_socket_path",
                            lambda: default_sock)
        monkeypatch.setattr(hook_install, "ensure_hooks_installed",
                            lambda: None)
        monkeypatch.setattr(session_mod, "state_root",
                            MagicMock(side_effect=FileNotFoundError()))
        monkeypatch.setattr(session_mod, "_get_session_name_for_cwd",
                            lambda: "pm-iso-gone")
        monkeypatch.setattr(session_mod, "_schedule_rebalance",
                            lambda name: None)
        # First lookup (inside _resolve_session_socket) sees a legacy
        # session on the default server; the session is gone by the time
        # _session_start asks whether it is running, and the re-resolution
        # finds nothing.  No server is bound for it, so the real
        # session_exists below answers "no".
        lookups: list[str] = []

        def vanished_legacy(name):
            lookups.append(name)
            return (str(default_sock), False) if len(lookups) == 1 \
                else (None, False)

        monkeypatch.setattr(tmux, "find_session_server", vanished_legacy)

        created: dict = {}
        real_create = tmux.create_session

        def fake_create(name, cwd, cmd, socket_path=None, env=None):
            created.update(name=name, socket_path=socket_path)
            real_create(name, cwd, "sleep 300", socket_path=socket_path,
                        env=env)

        monkeypatch.setattr(tmux, "create_session", fake_create)
        attached: list[tuple[str, str | None]] = []
        monkeypatch.setattr(
            tmux, "attach",
            lambda name, socket_path=None: attached.append(
                (name, socket_path)))

        private_sock = str(short_sock_dir / "pm-iso-gone")
        try:
            session_mod._session_start()

            # The create path ran on the private socket, not the default
            # server the vanished legacy lookup had selected.
            assert created == {"name": "pm-iso-gone",
                               "socket_path": private_sock}
            assert os.environ["PM_TMUX_SOCKET"] == private_sock
            assert attached == [("pm-iso-gone~1", private_sock)]
            # No rollout note for a session that was not attached.
            assert "started before per-session tmux servers" not in \
                capsys.readouterr().out
            # Nothing was created on the default server.
            assert not default_sock.exists()
        finally:
            _tmux(private_sock, "kill-server")
            Path(private_sock).unlink(missing_ok=True)


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

    def test_detach_through_the_users_own_view(self, short_sock_dir,
                                               monkeypatch):
        """R5: a client viewing through a user's own view is a candidate.

        ``tmux new-session -t <base> -s myview`` groups the view with the
        pm session, so its client sees the same panes and can press the
        same keys — but its name says nothing about the session.  Ctrl-Q
        pressed from such a view must detach exactly that client and leave
        both sessions running (the name-prefix candidate set detached
        nothing here).
        """
        if not subprocess.run(["which", "script"],
                              capture_output=True).returncode == 0:
            pytest.skip("`script` not available for attaching a client")

        sock = short_sock_dir / "v.sock"
        base = _make_server(sock, "pm-iso-v")
        r = _tmux(sock, "new-session", "-d", "-t", base, "-s", "myview")
        assert r.returncode == 0, r.stderr
        proc, _ = _attach_client(sock, "myview")
        try:
            pane = _tmux_out(sock, "list-panes", "-t", base,
                             "-F", "#{pane_id}").split()[0]
            monkeypatch.setenv("PM_TMUX_SOCKET", str(sock))
            monkeypatch.setenv("TMUX_PANE", pane)

            assert tmux.detach_current_client() is True

            # The view's client is gone; both sessions still exist.
            assert _tmux(sock, "list-clients", "-F", "#{client_tty}"
                         ).stdout.strip() == ""
            assert _tmux(sock, "has-session", "-t", base).returncode == 0
            assert _tmux(sock, "has-session",
                         "-t", "myview").returncode == 0
        finally:
            _close(proc, sock)

    def test_kill_tears_down_the_whole_group_including_a_view(
            self, short_sock_dir):
        """R8 end to end: base + ``~1`` + a user's view all go, server exits.

        The kill enumerates ``sessions_in_group``; a name-prefix list
        (``list_grouped_sessions``) cannot see the view, which kept the
        server — and the old TUI pane in the shared window — alive after a
        kill, so the socket could not be removed.
        """
        sock = short_sock_dir / "k.sock"
        base = _make_server(sock, "pm-iso-k")
        try:
            assert _tmux(sock, "new-session", "-d", "-t", base,
                         "-s", f"{base}~1").returncode == 0
            assert _tmux(sock, "new-session", "-d", "-t", base,
                         "-s", "myview").returncode == 0

            members = tmux.sessions_in_group(base, socket_path=str(sock))
            assert sorted(members) == sorted([base, f"{base}~1", "myview"])

            # The kill path: group members first, then the base.
            for member in members:
                if member != base:
                    tmux.kill_session(member, socket_path=str(sock))
            tmux.kill_session(base, socket_path=str(sock))

            # Nothing of the session is left: the server exits with its
            # last session (tmux leaves the socket file for pm to unlink).
            assert tmux.server_alive(str(sock)) is False
        finally:
            _close(None, sock)

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
