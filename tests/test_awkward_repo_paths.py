"""Repo paths and names that tmux or a shell would rewrite (QA scenario 28).

Three defects found driving every Claude launch surface from a project whose
directory is ``it's my `touch PWNED` $HOME repo``:

1. tmux stores a session name differently from how pm passes it.
   ``new-session -s`` expands the name as a format (``#(cmd)`` runs *cmd*),
   then turns ``.``/``:`` into ``_`` and backslash-escapes ``\\``, control
   characters and a ``$`` before a letter, ``_`` or ``{``.  ``pm session``
   then failed with "Failed to detect TUI pane after session creation." and
   a second ``pm session`` died with "duplicate session".  The tag is now
   made tmux-safe at its source (``paths.tmux_safe_name``).
2. ``-c <cwd>`` (and ``display-popup -d``) are format-expanded too: a repo
   path containing ``#(cmd)`` ran *cmd* on every session and window start,
   and the pane opened elsewhere.  ``tmux.format_literal`` escapes ``#``.
3. The TUI's ``s``/``d`` passed an unquoted ``--transcript <repo>/...`` to
   ``run_command``'s ``shlex.split``; a ``'`` in the repo path raised
   ``ValueError: No closing quotation`` and took the TUI (and, as the
   window's only pane, the session's server) down.

Plus one registry gap seen on the way: a window killed from outside pm
stayed in the pane registry until the TUI restarted.
"""

import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import paths
from pm_core import tmux as tmux_mod
from pm_core.paths import tmux_safe_name

TMUX = shutil.which("tmux")

AWKWARD = [
    "it's my `touch PWNED` $HOME repo",
    "next.js", "a:b", "a\\b", "a\tb", "a\nb", "a\x7fb",
    "a$$HOME", "a$_x", "a${x}", "a$.b", "a$1b", "a$(x)", "a$$ b", "a$",
    "a#(touch PWNED)b", "a#{host}b", "a##b", "a#Sb", "c#",
    "日本語~²", "~tilde", "q'uote", "sp ace", 'dq"x', "%pct",
]


class TestTmuxSafeName:
    @pytest.mark.parametrize("name,expected", [
        ("it's my `touch PWNED` $HOME repo-1e5c28de",
         "it's my `touch PWNED` _HOME repo-1e5c28de"),
        ("next.js-ab12cd34", "next_js-ab12cd34"),
        ("a:b", "a_b"), ("a\\b", "a_b"), ("a\tb", "a_b"), ("a\x7fb", "a_b"),
        ("a#(touch X)b", "a_(touch X)b"),
        # a $ is judged on its successor's final text
        ("a$$HOME", "a__HOME"), ("a$.b", "a__b"), ("a${x}", "a_{x}"),
        ("a$_x", "a__x"),
        # what tmux keeps is kept
        ("a$1b", "a$1b"), ("a$(x)", "a$(x)"), ("a$$ b", "a$$ b"),
        ("a$'b", "a$'b"), ("a$-b", "a$-b"), ("a$é", "a$é"),
        ("日本語~²", "日本語~²"), ("q'uote `x` ~y", "q'uote `x` ~y"),
    ])
    def test_rewrites_only_what_tmux_rewrites(self, name, expected):
        assert tmux_safe_name(name) == expected

    def test_idempotent(self):
        for n in AWKWARD:
            assert tmux_safe_name(tmux_safe_name(n)) == tmux_safe_name(n)

    def test_session_tag_of_a_dollar_home_repo_is_tmux_safe(self, tmp_path):
        repo = tmp_path / "it's my `touch PWNED` $HOME repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        paths._session_tag_cache.clear()
        try:
            tag = paths.get_session_tag(start_path=repo,
                                        use_github_name=False)
        finally:
            paths._session_tag_cache.clear()
        assert tag.startswith("it's my `touch PWNED` _HOME repo-")
        assert tag == tmux_safe_name(tag)

    @pytest.mark.parametrize("share_mode", [None, "", "global", "group:devteam"])
    def test_wrapper_tag_equals_paths_tag(self, tmp_path, monkeypatch,
                                          share_mode):
        """The wrapper finds pm_root and a pm meta override by this tag.

        Both are written under ``paths.get_session_tag``, which makes the
        repo name tmux-safe and mixes the share mode in; a shared session's
        panes carry PM_SHARE_MODE.  The wrapper's own hand copy once left
        the share mode out (review-loop 68bd i1); it now delegates.
        """
        from pm_core import wrapper
        repo = tmp_path / "next.js"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        monkeypatch.chdir(repo)
        if share_mode is None:
            monkeypatch.delenv("PM_SHARE_MODE", raising=False)
        else:
            monkeypatch.setenv("PM_SHARE_MODE", share_mode)
        paths._session_tag_cache.clear()
        try:
            expected = paths.get_session_tag()
            paths._session_tag_cache.clear()
            actual = wrapper._get_session_tag()
        finally:
            paths._session_tag_cache.clear()
        assert expected.startswith("next_js-")
        assert actual == expected


@pytest.mark.skipif(not TMUX, reason="tmux not installed")
class TestRealTmuxStoresThePmName:
    """The name pm computes is the name tmux reports, on the real binary."""

    @pytest.fixture
    def sock(self):
        d = tempfile.mkdtemp(prefix="pm-s28-", dir="/tmp")
        s = os.path.join(d, "s")
        yield s
        subprocess.run([TMUX, "-S", s, "kill-server"], capture_output=True)
        shutil.rmtree(d, ignore_errors=True)

    def _names(self, sock):
        out = subprocess.run([TMUX, "-S", sock, "list-sessions",
                              "-F", "#{session_name}"],
                             capture_output=True, text=True).stdout
        return [n for n in out.split("\n") if n]

    def test_every_awkward_tag_round_trips(self, sock, tmp_path,
                                           monkeypatch):
        monkeypatch.chdir(tmp_path)
        canary = tmp_path / "PWNED"
        for raw in AWKWARD:
            name = "pm-" + tmux_safe_name(raw) + "-1234abcd"
            tmux_mod.create_session(name, str(tmp_path), "sleep 30",
                                    socket_path=sock)
            assert self._names(sock) == [name], raw
            subprocess.run([TMUX, "-S", sock, "kill-session", "-t",
                            "=" + name], capture_output=True)
        time.sleep(0.3)
        assert not canary.exists()

    def test_raw_names_are_rewritten_which_is_why_the_tag_is_sanitized(
            self, sock, tmp_path):
        name = "pm-it's my $HOME repo-1234abcd"
        subprocess.run([TMUX, "-S", sock, "new-session", "-d", "-s", name,
                        "sleep 30"], check=True)
        assert self._names(sock) == ["pm-it's my \\$HOME repo-1234abcd"]

    def test_start_directory_with_a_format_job_runs_nothing(
            self, sock, tmp_path, monkeypatch):
        # A format job runs in the tmux client's cwd: watch the canary there.
        monkeypatch.chdir(tmp_path)
        canary = tmp_path / "PWNED"
        cwd = tmp_path / f"r#(touch {canary.name})x #S ##"
        cwd.mkdir()
        tmux_mod.create_session("pm-x-1234abcd", str(cwd), "sleep 30",
                                socket_path=sock)
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": sock}):
            pane = tmux_mod.split_pane_at("%0", "h", "sleep 30",
                                          background=True, cwd=str(cwd))
        time.sleep(0.5)
        out = subprocess.run(
            [TMUX, "-S", sock, "list-panes", "-a", "-F",
             "#{pane_id}|#{pane_current_path}"],
            capture_output=True, text=True).stdout.split("\n")
        assert f"%0|{cwd}" in out
        assert f"{pane}|{cwd}" in out
        assert not canary.exists()


class TestFormatLiteralArgs:
    def test_create_session_escapes_name_and_cwd(self):
        with patch.object(tmux_mod, "_run_with_env") as run:
            tmux_mod.create_session("pm-a#b-1", "/r/a#(x)", "cmd",
                                    socket_path="/tmp/s")
        args = run.call_args[0][0]
        assert args[args.index("-s") + 1] == "pm-a##b-1"
        assert args[args.index("-c") + 1] == "/r/a##(x)"

    def test_new_window_escapes_cwd(self):
        with patch.object(tmux_mod, "_run_with_env") as run, \
                patch.object(tmux_mod, "find_window_by_name",
                             return_value=None):
            tmux_mod.new_window("s", "w", "cmd", "/r/#(x)", switch=False)
        args = run.call_args[0][0]
        assert args[args.index("-c") + 1] == "/r/##(x)"

    def test_ordinary_paths_unchanged(self):
        assert tmux_mod.format_literal("/home/u/my repo") == "/home/u/my repo"


def _tui_app(tmp_path):
    app = MagicMock()
    app._consume_z = MagicMock(return_value=0)
    app._data = {"prs": [{"id": "pr-001", "title": "T", "status": "pending"}]}
    app._root = None
    app._inflight_pr_action = None
    tree = MagicMock()
    tree.selected_pr_id = "pr-001"
    app.query_one.return_value = tree
    return app


class TestTuiTranscriptArgQuoted:
    """``s``/``d`` must survive a repo path with a quote, space or ``$``."""

    TDIR = Path("/r/it's my `touch PWNED` $HOME repo/pm/transcripts/manual-1")

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    @patch("pm_core.tui.auto_start.get_transcript_dir", return_value=TDIR)
    def test_start_pr(self, _tdir, _setting, _guard, mock_run, tmp_path):
        from pm_core.tui import pr_view
        pr_view.start_pr(_tui_app(tmp_path))
        parts = shlex.split(mock_run.call_args[0][1])
        assert parts[parts.index("--transcript") + 1] == \
            f"{self.TDIR}/impl-pr-001.jsonl"
        assert parts[-1] == "pr-001"

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.loop_shared.get_pm_session", return_value=None)
    @patch("pm_core.tui.auto_start.get_transcript_dir", return_value=TDIR)
    def test_review_pr(self, _tdir, _sess, _guard, mock_run, tmp_path):
        from pm_core.tui import pr_view
        pr_view.review_pr(_tui_app(tmp_path))
        parts = shlex.split(mock_run.call_args[0][1])
        assert parts[parts.index("--transcript") + 1] == \
            f"{self.TDIR}/review-pr-001.jsonl"
        assert parts[-1] == "pr-001"

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.auto_start.get_transcript_dir", return_value=TDIR)
    def test_auto_merge(self, _tdir, mock_run, tmp_path):
        from pm_core.tui import review_loop_ui
        app = MagicMock()
        app._root = tmp_path
        with patch.object(review_loop_ui.store, "load", return_value={}):
            review_loop_ui._attempt_merge(app, "pr-001")
        parts = shlex.split(mock_run.call_args[0][1])
        assert parts[parts.index("--transcript") + 1] == \
            f"{self.TDIR}/merge-pr-001.jsonl"

    def test_unparsable_command_is_logged_not_raised(self):
        from pm_core.tui import pr_view
        app = MagicMock()
        app._inflight_pr_action = "Starting pr-001"
        pr_view.run_command(app, "pr start --transcript /r/it's/x pr-001",
                            working_message="Starting pr-001",
                            action_key="Starting pr-001")
        msg = app.log_message.call_args[0][0]
        assert msg.startswith("Error: cannot parse command")
        assert app._inflight_pr_action is None
        app.run_worker.assert_not_called()

    @pytest.mark.parametrize("cmd", [
        "pr note add pr-001 don't forget",   # plain command
        "pr start 'pr-001",                  # takes the in-flight guard
    ])
    def test_unparsable_command_bar_line_is_logged_not_raised(self, cmd):
        """A typed or queued line with an unbalanced quote.

        It raised ValueError out of the command-bar handler (exiting the
        TUI); for a PR action it did so after taking the in-flight guard.
        """
        from pm_core.tui import pr_view
        app = MagicMock()
        app._inflight_pr_action = None
        app._plans_visible = False
        pr_view.handle_command_submitted(app, cmd)
        msg = app.log_message.call_args[0][0]
        assert msg.startswith("Error: cannot parse command")
        assert app._inflight_pr_action is None
        app.run_worker.assert_not_called()
        app.query_one.return_value.focus.assert_called_once()


class TestAttachPrunesWindowsKilledOutsidePm:
    def test_registry_only_window_is_rebalanced(self):
        from pm_core.cli import session as session_mod
        with patch.object(session_mod.tmux_mod, "list_windows",
                          return_value=[{"id": "@0"}]), \
                patch("pm_core.pane_registry.load_registry",
                      return_value={"windows": {"@0": {}, "@3": {}}}), \
                patch.object(session_mod.subprocess, "Popen") as popen:
            session_mod._schedule_rebalance("pm-x")
        code = popen.call_args[0][0][-1]
        assert "rebalance('pm-x', '@0')" in code
        assert "rebalance('pm-x', '@3')" in code

    def test_unreadable_registry_still_rebalances_live_windows(self):
        from pm_core.cli import session as session_mod
        with patch.object(session_mod.tmux_mod, "list_windows",
                          return_value=[{"id": "@0"}]), \
                patch("pm_core.pane_registry.load_registry",
                      side_effect=OSError("boom")), \
                patch.object(session_mod.subprocess, "Popen") as popen:
            session_mod._schedule_rebalance("pm-x")
        code = popen.call_args[0][0][-1]
        assert "rebalance('pm-x', '@0')" in code
        assert "'@3'" not in code
