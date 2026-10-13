"""Workspace-trust bootstrap and bounded trust-prompt handling (pr-b53bfe2)."""

from __future__ import annotations

import json
from contextlib import ExitStack
import os
import stat
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pm_core import workspace_trust as wt
from pm_core.claude_launcher import (
    WorkspacePromptWatch,
    WorkspaceTrustBlocked,
    build_claude_shell_cmd,
    prepare_workspace,
)

# Verbatim screen from claude 2.1.296 in a fresh checkout (pre-fix capture
# impl/pre-fix/host-planner-blocked/final-screen.txt).
TRUST_SCREEN = """
────────────────────────────────────────────────────────────────────────
 Accessing workspace:

 {path}

 Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source project, or work from
 your team). If not, take a moment to review what's in this folder first.

 Claude Code'll be able to read, edit, and execute files here.

 Security guide

 ❯ No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel
"""

# Older Claude Code layout: numbered options, "Yes, proceed" preselected.
OLD_TRUST_SCREEN = """
 Do you trust the files in this folder?

 /some/where

 ❯ 1. Yes, proceed
   2. No, exit
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME (pm settings + workdirs) and Claude config dir."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    cfg_dir = tmp_path / "claude-cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg_dir))
    return h


def _cfg() -> Path:
    return wt.get_trust_runtime().config_path()


def _projects() -> dict:
    return json.loads(_cfg().read_text()).get("projects", {})


def _git_checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _pm_workdir(home: Path, name: str = "proj-1234/pm-pr-abc") -> Path:
    return _git_checkout(home / ".pm" / "workdirs" / name)


def _write_cfg(data: dict) -> None:
    _cfg().write_text(json.dumps(data))
    os.chmod(_cfg(), 0o600)


# ---------------------------------------------------------------------------
# Bootstrap (provider config write)
# ---------------------------------------------------------------------------

class TestBootstrap:
    def test_fresh_pm_checkout_gets_trust_entry(self, home):
        wd = _pm_workdir(home)
        _write_cfg({"numStartups": 7, "projects": {"/other": {"allowedTools": ["x"]}}})

        out = wt.get_trust_runtime().bootstrap(wd)

        assert out.status == wt.TRUSTED
        data = json.loads(_cfg().read_text())
        assert data["numStartups"] == 7
        assert data["projects"]["/other"] == {"allowedTools": ["x"]}
        assert data["projects"][str(wd)]["hasTrustDialogAccepted"] is True
        assert stat.S_IMODE(_cfg().stat().st_mode) == 0o600
        assert not Path(str(_cfg()) + ".lock").exists()

    def test_keeps_existing_project_fields_and_is_idempotent(self, home):
        wd = _pm_workdir(home)
        _write_cfg({"projects": {str(wd): {"allowedTools": ["Bash"],
                                           "hasTrustDialogAccepted": False}}})
        rt = wt.get_trust_runtime()
        assert rt.bootstrap(wd).status == wt.TRUSTED
        before = _cfg().stat().st_mtime_ns
        assert rt.bootstrap(wd).status == wt.ALREADY
        assert _cfg().stat().st_mtime_ns == before
        assert _projects()[str(wd)] == {"allowedTools": ["Bash"],
                                        "hasTrustDialogAccepted": True}

    def test_missing_config_is_created(self, home):
        wd = _pm_workdir(home)
        assert wt.get_trust_runtime().bootstrap(wd).status == wt.TRUSTED
        assert _projects()[str(wd)]["hasTrustDialogAccepted"] is True

    def test_missing_config_dir_is_created(self, home, tmp_path, monkeypatch):
        # A CLAUDE_CONFIG_DIR that Claude has not created yet: the lock
        # lives inside it, so the dir must exist before locking.
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fresh-cfg"))
        wd = _pm_workdir(home)
        assert wt.get_trust_runtime().bootstrap(wd).status == wt.TRUSTED
        assert _projects()[str(wd)]["hasTrustDialogAccepted"] is True

    def test_never_trusts_parent_of_checkout(self, home):
        wd = _pm_workdir(home)
        wt.get_trust_runtime().bootstrap(wd)
        keys = set(_projects())
        assert keys == {str(wd)}
        assert str(home / ".pm" / "workdirs") not in keys
        assert str(home) not in keys

    def test_qa_scenario_clone_subdir(self, home):
        clone = _git_checkout(home / ".pm" / "workdirs" / "qa" / "pr-x-ab12" / "s-3" / "repo")
        assert wt.get_trust_runtime().bootstrap(clone).status == wt.TRUSTED
        assert _projects()[str(clone)]["hasTrustDialogAccepted"] is True

    def test_unapproved_path_left_explicit(self, home, tmp_path):
        foreign = _git_checkout(tmp_path / "someone-elses-repo")
        _write_cfg({"projects": {}})
        out = wt.get_trust_runtime().bootstrap(foreign)
        assert out.status == wt.UNAPPROVED
        assert f"pm trust add {foreign}" in out.message
        assert _projects() == {}

    def test_explicitly_authorized_path(self, home, tmp_path):
        mine = _git_checkout(tmp_path / "my-project")
        wt.set_authorized_roots([str(mine)])
        assert wt.approved_path(mine / "sub")
        assert wt.get_trust_runtime().bootstrap(mine).status == wt.TRUSTED

    def test_symlink_into_workdirs_not_approved_by_link_name(self, home, tmp_path):
        foreign = _git_checkout(tmp_path / "foreign")
        link = home / ".pm" / "workdirs" / "sneaky"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(foreign)
        assert not wt.approved_path(link)
        assert wt.get_trust_runtime().bootstrap(link).status == wt.UNAPPROVED

    def test_corrupt_config_untouched(self, home):
        wd = _pm_workdir(home)
        _cfg().write_text("{not json")
        out = wt.get_trust_runtime().bootstrap(wd)
        assert out.status == wt.ERROR
        assert _cfg().read_text() == "{not json"

    def test_waits_for_claude_lock(self, home, monkeypatch):
        wd = _pm_workdir(home)
        rt = wt.ClaudeWorkspaceTrust()
        monkeypatch.setattr(rt, "LOCK_TIMEOUT_SECONDS", 0.3)
        lock = Path(str(rt.config_path()) + ".lock")
        lock.mkdir()
        out = rt.bootstrap(wd)
        assert out.status == wt.ERROR and "lock" in out.message
        assert lock.is_dir()  # someone else's live lock is left alone

    def test_stale_lock_reclaimed(self, home):
        wd = _pm_workdir(home)
        rt = wt.ClaudeWorkspaceTrust()
        lock = Path(str(rt.config_path()) + ".lock")
        lock.mkdir()
        old = time.time() - 60
        os.utime(lock, (old, old))
        assert rt.bootstrap(wd).status == wt.TRUSTED
        assert not lock.exists()

    def test_is_trusted_mirrors_git_root_bound(self, home):
        wd = _pm_workdir(home)
        rt = wt.get_trust_runtime()
        # Trust on the parent of a git checkout does not count (Claude
        # bounds its parent walk at the git root).
        _write_cfg({"projects": {str(wd.parent): {"hasTrustDialogAccepted": True}}})
        assert not rt.is_trusted(wd)
        rt.bootstrap(wd)
        assert rt.is_trusted(wd)
        (wd / "sub").mkdir()
        assert rt.is_trusted(wd / "sub")


class TestSeedConfig:
    def test_container_copy_trusts_workspace_only(self, home, tmp_path):
        _write_cfg({"projects": {"/x": {"hasTrustDialogAccepted": False}},
                    "oauthAccount": {"a": 1}})
        dest = tmp_path / "copy.json"
        assert wt.get_trust_runtime().seed_config(_cfg(), dest, ["/workspace"])
        copy = json.loads(dest.read_text())
        assert copy["projects"]["/workspace"]["hasTrustDialogAccepted"] is True
        assert copy["oauthAccount"] == {"a": 1}
        assert "/workspace" not in _projects()  # host file untouched


# ---------------------------------------------------------------------------
# Launch boundary
# ---------------------------------------------------------------------------

class TestLaunchBoundary:
    def test_host_launch_bootstraps_fresh_checkout(self, home):
        """The #229 path: a host QA planner launched into a fresh pm
        checkout must not depend on a pre-existing trust entry."""
        wd = _pm_workdir(home)
        _write_cfg({"projects": {}})
        build_claude_shell_cmd(prompt="plan", cwd=str(wd),
                               session_id=str(uuid.uuid4()),
                               session_type="qa_planning")
        assert _projects()[str(wd)]["hasTrustDialogAccepted"] is True

    def test_host_launch_runs_in_bootstrapped_dir(self, home):
        """Claude must run where trust was established, whatever cwd the
        pane happens to start in (review pane regression)."""
        wd = _pm_workdir(home)
        cmd = build_claude_shell_cmd(prompt="p", cwd=str(wd), session_type="review")
        assert cmd.startswith(f"cd {wd} && claude")
        container = build_claude_shell_cmd(prompt="p", cwd="/workspace",
                                           write_dir=str(wd), session_type="review")
        assert not container.startswith("cd ")

    def test_resume_launch_bootstraps(self, home):
        wd = _pm_workdir(home)
        build_claude_shell_cmd(cwd=str(wd), session_id=str(uuid.uuid4()),
                               resume=True, session_type="impl")
        assert wt.get_trust_runtime().is_trusted(wd)

    def test_container_launch_does_not_touch_host_config(self, home):
        wd = _pm_workdir(home)
        _write_cfg({"projects": {}})
        build_claude_shell_cmd(prompt="p", cwd="/workspace",
                               write_dir=str(wd), session_type="review")
        assert _projects() == {}

    def test_no_bypass_flag_implied(self, home):
        wd = _pm_workdir(home)
        cmd = build_claude_shell_cmd(prompt="p", cwd=str(wd), session_type="impl")
        assert "--dangerously-skip-permissions" not in cmd

    def test_unapproved_launch_leaves_prompt_explicit(self, home, tmp_path):
        foreign = _git_checkout(tmp_path / "foreign")
        _write_cfg({"projects": {}})
        build_claude_shell_cmd(prompt="p", cwd=str(foreign), session_type="impl")
        assert _projects() == {}

    def test_fake_claude_skips_bootstrap(self, home):
        wd = _pm_workdir(home)
        with patch("pm_core.paths.fake_claude_config_for_type",
                   return_value={"verdicts": {}}):
            build_claude_shell_cmd(prompt="p", cwd=str(wd), session_type="impl")
        assert not _cfg().exists()

    def test_prepare_workspace_never_raises(self, home):
        wd = _pm_workdir(home)
        with patch.object(wt.ClaudeWorkspaceTrust, "bootstrap",
                          side_effect=RuntimeError("boom")):
            out = prepare_workspace(str(wd))
        assert out.status == wt.ERROR

    def test_other_runtime_can_supply_its_own(self, home):
        calls = []

        class Other(wt.TrustRuntime):
            name = "other"

            def bootstrap(self, path):
                calls.append(str(path))
                return wt.TrustOutcome(wt.TRUSTED, str(path))

        saved = wt._RUNTIMES["claude"]
        wt.register_trust_runtime("claude", Other())
        try:
            wd = _pm_workdir(home)
            prepare_workspace(str(wd))
        finally:
            wt.register_trust_runtime("claude", saved)
        assert calls == [str(wd)]
        assert wt.get_trust_runtime("missing").bootstrap(wd).status == wt.UNSUPPORTED


# ---------------------------------------------------------------------------
# Prompt detection / explicit handling
# ---------------------------------------------------------------------------

class TestPromptDetection:
    def test_detects_current_prompt_and_path(self):
        rt = wt.get_trust_runtime()
        assert rt.detect_prompt(TRUST_SCREEN.format(path="/a/b")) == "/a/b"
        assert rt.detect_prompt("Welcome to Claude Code\n> ") is None
        assert rt.detect_prompt("") is None

    def test_wrapped_path_is_rejoined(self):
        # A long workdir path hard-wraps in a narrow pane.
        path = "/home/u/.pm/workdirs/proj-1234/pr-abc-a-very-long-branch-name"
        screen = TRUST_SCREEN.format(path=path[:30] + "\n " + path[30:])
        assert wt.get_trust_runtime().detect_prompt(screen) == path

    def test_mention_in_conversation_is_not_a_prompt(self):
        text = "The dialog says 'Accessing workspace:' but no options here"
        assert wt.get_trust_runtime().detect_prompt(text) is None

    def test_quoted_dialog_text_is_not_a_prompt(self):
        # Source/diff output naming the option strings mid-line (e.g. a
        # reviewer viewing this module) must not look like the dialog.
        text = ('_TRUST_PROMPT_RE = re.compile(r"Accessing workspace:")\n'
                '_OPTION_RE = re.compile(r"(Yes, I trust this folder|No, exit)")')
        assert wt.get_trust_runtime().detect_prompt(text) is None

    def test_accept_keys_never_blind_enter(self):
        rt = wt.get_trust_runtime()
        # Current layout defaults to "No, exit": must move down first.
        assert rt.accept_keys(TRUST_SCREEN.format(path="/a")) == ["Down", "Enter"]
        # Older layout with "Yes, proceed" preselected.
        assert rt.accept_keys(OLD_TRUST_SCREEN) == ["Enter"]
        # Unreadable cursor -> refuse.
        assert rt.accept_keys("Yes, I trust this folder\nNo, exit") is None


class _FakePane:
    def __init__(self, screen):
        self.screen = screen
        self.keys: list[str] = []

    def capture(self, pane_id, full_scrollback=False):
        return self.screen

    def send(self, pane_id, key):
        self.keys.append(key)
        if key == "Enter":
            self.screen = "Claude is working…"


class TestPromptWatch:
    def test_approved_workdir_prompt_is_accepted(self, home):
        wd = _pm_workdir(home)
        pane = _FakePane(TRUST_SCREEN.format(path=wd))
        with patch("pm_core.tmux.capture_pane", pane.capture), \
             patch("pm_core.tmux.send_keys_literal", pane.send), \
             patch("pm_core.claude_launcher.time.sleep"):
            w = WorkspacePromptWatch("%1", str(wd), grace=0)
            assert w.check() is None
            assert pane.keys == ["Down", "Enter"]
            assert w.check(force=True) is None
            assert not w.visible

    def test_unapproved_prompt_fails_after_grace(self, home, tmp_path):
        foreign = _git_checkout(tmp_path / "foreign")
        pane = _FakePane(TRUST_SCREEN.format(path=foreign))
        with patch("pm_core.tmux.capture_pane", pane.capture), \
             patch("pm_core.tmux.send_keys_literal", pane.send):
            w = WorkspacePromptWatch("%1", str(foreign), grace=60)
            assert w.check() is None and w.visible
            msg = w.check(force=True)
            assert msg is None  # still within grace
            w._first_seen -= 61
            msg = w.check(force=True)
        assert pane.keys == []
        assert msg and f"pm trust add {foreign}" in msg
        assert "workspace-trust prompt" in msg

    def test_shown_unapproved_dir_not_accepted_via_approved_workdir(
            self, home, tmp_path):
        """The session started outside the intended (approved) workdir, as
        the pre-fix review pane did in the TUI's pm/ dir: never trust the
        shown directory by proxy."""
        wd = _pm_workdir(home)
        foreign = _git_checkout(tmp_path / "pm-root")
        pane = _FakePane(TRUST_SCREEN.format(path=foreign))
        with patch("pm_core.tmux.capture_pane", pane.capture), \
             patch("pm_core.tmux.send_keys_literal", pane.send):
            w = WorkspacePromptWatch("%1", str(wd), grace=0)
            msg = w.check()
        assert pane.keys == []
        assert msg and f"pm trust add {foreign}" in msg

    def test_container_path_falls_back_to_host_workdir(self, home):
        wd = _pm_workdir(home)
        pane = _FakePane(TRUST_SCREEN.format(path="/no-such-container-dir"))
        with patch("pm_core.tmux.capture_pane", pane.capture), \
             patch("pm_core.tmux.send_keys_literal", pane.send), \
             patch("pm_core.container._CONTAINER_WORKDIR",
                   "/no-such-container-dir"), \
             patch("pm_core.claude_launcher.time.sleep"):
            w = WorkspacePromptWatch("%1", str(wd), grace=0)
            assert w.check() is None
        assert pane.keys == ["Down", "Enter"]

    def test_unresolvable_host_path_not_accepted_via_workdir(self, home):
        """A shown path that is neither a host dir nor container-internal
        (e.g. mis-parsed) must not be trusted by proxy of the workdir."""
        wd = _pm_workdir(home)
        pane = _FakePane(TRUST_SCREEN.format(path="/home/u/proj/p"))
        with patch("pm_core.tmux.capture_pane", pane.capture), \
             patch("pm_core.tmux.send_keys_literal", pane.send), \
             patch("pm_core.container._CONTAINER_WORKDIR",
                   "/no-such-container-dir"):
            w = WorkspacePromptWatch("%1", str(wd), grace=0)
            msg = w.check()
        assert pane.keys == []
        assert msg and "pm trust add /home/u/proj/p" in msg

    def test_watch_ends_once_transcript_exists(self, home, tmp_path):
        """Claude writes the transcript only after the dialog; once it
        exists, dialog-like text later in the turn is ignored (no keys, no
        spurious block)."""
        wd = _pm_workdir(home)
        transcript = tmp_path / f"{uuid.uuid4()}.jsonl"
        pane = _FakePane("Claude is working…")
        with patch("pm_core.tmux.capture_pane", pane.capture), \
             patch("pm_core.tmux.send_keys_literal", pane.send):
            w = WorkspacePromptWatch("%1", str(wd), grace=0,
                                     transcript_path=transcript)
            assert w.check() is None
            transcript.write_text("{}\n")
            pane.screen = TRUST_SCREEN.format(path=wd)
            assert w.check(force=True) is None
            assert w.started and not w.visible
        assert pane.keys == []

    def test_grace_setting(self, home):
        assert wt.prompt_grace_seconds() == 120.0
        d = home / ".pm" / "settings"
        d.mkdir(parents=True)
        (d / "trust-prompt-grace-seconds").write_text("7\n")
        assert wt.prompt_grace_seconds() == 7.0

    def test_blocked_message_without_path_keeps_command_runnable(self):
        assert "`pm trust add /w/x`" in wt.blocked_message("/w/x", 130)
        msg = wt.blocked_message("", 130)
        assert "for the session workdir" in msg
        assert "`pm trust add <path>`" in msg


# ---------------------------------------------------------------------------
# Bounded failure in the pollers
# ---------------------------------------------------------------------------

def test_poll_for_verdict_raises_when_blocked(home, tmp_path):
    from pm_core import loop_shared
    d = home / ".pm" / "settings"
    d.mkdir(parents=True)
    (d / "trust-prompt-grace-seconds").write_text("0\n")
    transcript = tmp_path / f"{uuid.uuid4()}.jsonl"
    pane = _FakePane(TRUST_SCREEN.format(path="/not/approved"))
    with patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.tmux.capture_pane", pane.capture), \
         patch("pm_core.hook_events.wait_for_event", return_value=None):
        with pytest.raises(WorkspaceTrustBlocked, match="pm trust add /not/approved"):
            loop_shared.poll_for_verdict("%9", str(transcript), ("PASS",),
                                         workdir="/not/approved")


def test_adopted_review_polls_with_pr_workdir(tmp_path):
    """Restart handoff: an adopted in-flight review pane is watched with the
    PR workdir, so a pre-fix container dialog (/workspace) can still fall
    back to the approved host checkout."""
    from pm_core import review_loop
    transcript_dir = tmp_path / "t"
    transcript_dir.mkdir()
    sid = str(uuid.uuid4())
    (transcript_dir / "review-pr-x-i2.jsonl").symlink_to(tmp_path / f"{sid}.jsonl")
    state = review_loop.ReviewLoopState(pr_id="pr-x")
    state.iteration = 2
    pr_data = {"id": "pr-x", "workdir": "/wd/pr-x"}
    with patch("pm_core.review_loop._get_pm_session", return_value="pm-s"), \
         patch("pm_core.review_loop._find_claude_pane", return_value="%5"), \
         patch("pm_core.hook_events.read_event", return_value=None), \
         patch("pm_core.review_loop._poll_for_verdict",
               return_value="PASS") as poll:
        assert review_loop._adopt_in_flight_review(
            state, pr_data, str(transcript_dir)) == "PASS"
    assert poll.call_args.kwargs["workdir"] == "/wd/pr-x"


def test_pane_idle_reports_trust_prompt_as_waiting(home, tmp_path):
    from pm_core.pane_idle import PaneIdleTracker
    transcript = tmp_path / f"{uuid.uuid4()}.jsonl"
    pane = _FakePane(TRUST_SCREEN.format(path="/not/approved"))
    tracker = PaneIdleTracker()
    with patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.tmux.capture_pane", pane.capture), \
         patch("pm_core.hook_events.read_event", return_value=None):
        tracker.register("impl:pr-x", "%3", str(transcript))
        tracker.poll("impl:pr-x")
        assert tracker.is_waiting_for_input("impl:pr-x")
        assert not tracker.is_idle("impl:pr-x")


def test_qa_planner_blocked_fails_fast_without_finalizer(home, tmp_path):
    """#229: a planner stuck at the trust prompt must end planning with an
    actionable INPUT_REQUIRED — not wait the full planner timeout and then
    launch a finalizer into the same prompt."""
    from pm_core.qa_loop import QALoopState, VERDICT_INPUT_REQUIRED, run_qa_sync

    d = home / ".pm" / "settings"
    d.mkdir(parents=True)
    (d / "trust-prompt-grace-seconds").write_text("0\n")
    workdir = _git_checkout(tmp_path / "not-a-pm-workdir")
    pr = {"id": "pr-trust", "title": "T", "branch": "pm/t", "status": "qa",
          "workdir": str(workdir)}
    data = {"project": {"name": "t", "base_branch": "master", "backend": "local"},
            "prs": [pr], "plans": []}
    pane = _FakePane(TRUST_SCREEN.format(path=workdir))

    state = QALoopState(pr_id="pr-trust")
    started = time.monotonic()
    patches = [
        patch("pm_core.qa_loop.get_pm_session", return_value="pm-s"),
        patch("pm_core.store.load", return_value=data),
        patch("pm_core.store.get_pr", return_value=pr),
        patch("pm_core.qa_loop._resolve_qa_model", return_value=SimpleNamespace(model=None, provider=None, effort=None)),
        patch("pm_core.prompt_gen.generate_qa_planner_prompt", return_value="plan it"),
        patch("pm_core.container.is_container_mode_enabled", return_value=False),
        patch("pm_core.qa_loop._launch_scenario_0", return_value=None),
        patch("pm_core.tmux.find_window_by_name", return_value=None),
        patch("pm_core.tmux.new_window"),
        patch("pm_core.tmux.select_window"),
        patch("pm_core.qa_loop.find_claude_pane", return_value="%5"),
        patch("pm_core.tmux.pane_exists", return_value=True),
        patch("pm_core.tmux.capture_pane", pane.capture),
        patch("pm_core.tmux.send_keys_literal", pane.send),
        patch("pm_core.hook_events.wait_for_event", return_value=None),
        patch("pm_core.qa_loop.time.sleep"),
        patch("pm_core.tmux.new_window_get_pane", return_value="%6"),
        patch("pm_core.qa_loop._poll_tmux_verdicts"),
        patch("pm_core.qa_loop._persist_scenario_verdicts"),
        patch("pm_core.qa_loop._write_resume_file"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        finalize = stack.enter_context(patch("pm_core.qa_loop._run_qa_finalize_pane"))
        launch = stack.enter_context(patch("pm_core.qa_loop._launch_scenarios_in_tmux"))
        split = stack.enter_context(
            patch("pm_core.tmux.split_pane_at", return_value="%7"))
        stack.enter_context(patch("pm_core.tmux.pane_window_id", return_value="@1"))
        stack.enter_context(patch("pm_core.pane_layout.register_and_rebalance"))
        run_qa_sync(state, tmp_path / "pm", pr, lambda *a: None)

    assert time.monotonic() - started < 30
    assert not state.running
    assert state.latest_verdict == VERDICT_INPUT_REQUIRED
    assert "workspace-trust prompt" in state._error
    assert f"pm trust add {workdir}" in state._error
    assert state.scenarios == []
    finalize.assert_not_called()
    launch.assert_not_called()
    assert pane.keys == []  # unapproved: never auto-accepted
    status_path = Path(state.qa_workdir) / "qa_status.json"
    status = json.loads(status_path.read_text())
    assert "workspace-trust prompt" in status["error"]
    # The error block is shown beside the planner, not only written to disk.
    split.assert_called_once()
    planner, _direction, cmd = split.call_args.args[:3]
    assert planner == "%5"
    assert "qa_status.py" in cmd and str(status_path) in cmd


def test_zero_scenarios_skip_finalizer(tmp_path):
    from pm_core.qa_loop import QALoopState, _execute_and_finalize
    state = QALoopState(pr_id="pr-z")
    state.qa_workdir = str(tmp_path)
    state._error = "No parseable scenarios"
    with patch("pm_core.qa_loop._poll_tmux_verdicts"), \
         patch("pm_core.qa_loop._persist_scenario_verdicts"), \
         patch("pm_core.qa_loop._write_resume_file"), \
         patch("pm_core.qa_loop._run_qa_finalize_pane") as finalize:
        _execute_and_finalize(
            state, tmp_path, {"id": "pr-z", "branch": "b"}, {}, "pm-s", "qa",
            str(tmp_path), tmp_path / "qa_status.json", None,
            use_containers=False, concurrency_cap=0, queued_scenarios=[],
            notify=lambda: None)
    finalize.assert_not_called()
    assert state.latest_verdict == "INPUT_REQUIRED"


def test_trust_blocked_worker_marked_input_required(tmp_path):
    """A scenario worker that never gets past the dialog (no hook event)
    is failed with a trust reason instead of being polled forever."""
    import itertools
    from pm_core.qa_loop import QALoopState, QAScenario, _poll_tmux_verdicts
    scenario = QAScenario(index=1, title="T", focus="f")
    scenario.window_name = "qa-s1"
    scenario.session_id = "sid-trust-1"
    scenario.worktree_path = str(tmp_path)
    state = QALoopState(pr_id="pr-w")
    state.scenarios = [scenario]
    clock = itertools.count(0, 100)
    with patch("pm_core.qa_loop._get_scenario_pane", return_value="%42"), \
         patch("pm_core.qa_loop.time.sleep"), \
         patch("pm_core.qa_loop.time.monotonic", lambda: next(clock)), \
         patch("pm_core.hook_events.read_event", return_value=None), \
         patch("pm_core.tmux.pane_exists", return_value=True), \
         patch.object(WorkspacePromptWatch, "check",
                      return_value="Claude is waiting at the prompt"), \
         patch("pm_core.qa_loop._is_verification_enabled", return_value=False):
        _poll_tmux_verdicts(state, {}, {}, "sess", str(tmp_path),
                            tmp_path / "status.json", lambda *a: None)
    assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
    assert state.scenario_verdict_reasons[1] == (
        "blocked at workspace-trust prompt: Claude is waiting at the prompt")


def test_trust_blocked_worker_watched_during_verdict_grace(tmp_path):
    """The verdict grace period must not delay the trust watch: a worker
    stuck at the dialog fails within trust grace of launch, not verdict
    grace + trust grace."""
    from pm_core.qa_loop import QALoopState, QAScenario, _poll_tmux_verdicts
    scenario = QAScenario(index=1, title="T", focus="f")
    scenario.window_name = "qa-s1"
    scenario.session_id = "sid-trust-grace"
    scenario.worktree_path = str(tmp_path)
    state = QALoopState(pr_id="pr-w")
    state.scenarios = [scenario]
    ticks = []

    def _sleep(_s):
        ticks.append(_s)
        if len(ticks) > 3:
            raise RuntimeError("trust watch never ran inside verdict grace")

    with patch("pm_core.qa_loop._get_scenario_pane", return_value="%42"), \
         patch("pm_core.qa_loop.time.sleep", _sleep), \
         patch("pm_core.qa_loop.time.monotonic", return_value=0.0), \
         patch("pm_core.hook_events.read_event", return_value=None), \
         patch("pm_core.tmux.pane_exists", return_value=True), \
         patch.object(WorkspacePromptWatch, "check",
                      return_value="Claude is waiting at the prompt"), \
         patch("pm_core.qa_loop._is_verification_enabled", return_value=False):
        _poll_tmux_verdicts(state, {}, {}, "sess", str(tmp_path),
                            tmp_path / "status.json", lambda *a: None)
    assert len(ticks) == 1
    assert state.scenario_verdicts[1] == "INPUT_REQUIRED"


def test_impl_idle_sweep_keeps_qa_tracker_keys(tmp_path):
    """_poll_impl_idle must not unregister qa:<pr>:s<n> keys: re-registering
    them every poll gave each QA pane a fresh trust watch, so its two-attempt
    accept budget never ran out (an accept every ~5s, forever)."""
    from types import SimpleNamespace
    from pm_core.pane_idle import PaneIdleTracker
    from pm_core.tui import review_loop_ui
    target = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
    target.write_text("")
    link = tmp_path / "transcript-s1.jsonl"
    link.symlink_to(target)
    tracker = PaneIdleTracker()
    tracker.register("qa:pr-q:s1", "%9", str(link))
    tracker.register("pr-gone", "%8", str(link))
    app = SimpleNamespace(
        _session_name="sess", _pane_idle_tracker=tracker,
        _data={"prs": []}, _review_loops={}, _pending_merge_prs=set(),
        _merge_propagation_phase=set(), log_message=lambda *a, **k: None)
    with patch("pm_core.tui.auto_start.is_enabled", return_value=False):
        review_loop_ui._poll_impl_idle(app)
    assert tracker.is_tracked("qa:pr-q:s1")
    assert not tracker.is_tracked("pr-gone")


def test_trust_blocked_concretizer_reports_reason_not_reject(tmp_path):
    from pm_core.qa_loop import (
        QAScenario, _concretize_failure_label, _concretize_scenario,
    )
    scenario = QAScenario(index=2, title="T", focus="f")
    with patch("pm_core.qa_loop.poll_for_verdict",
               side_effect=WorkspaceTrustBlocked("stuck")) as poll:
        refined, reason = _concretize_scenario(
            scenario, {}, {}, "%7", "sid", str(tmp_path))
    assert poll.call_args.kwargs["workdir"] == str(tmp_path)
    assert refined is None
    assert _concretize_failure_label(reason) == (
        "blocked at workspace-trust prompt: stuck")
    assert _concretize_failure_label("no UI") == "refiner rejected: no UI"


# ---------------------------------------------------------------------------
# pm trust CLI
# ---------------------------------------------------------------------------

class TestTrustCli:
    def _run(self, *args):
        from click.testing import CliRunner
        from pm_core.cli import cli
        return CliRunner().invoke(cli, ["trust", *args])

    def test_add_authorizes_and_bootstraps(self, home, tmp_path):
        repo = _git_checkout(tmp_path / "mine")
        r = self._run("add", str(repo))
        assert r.exit_code == 0, r.output
        assert str(repo) in wt.authorized_roots()
        assert _projects()[str(repo)]["hasTrustDialogAccepted"] is True
        status = self._run("status", str(repo))
        assert "approved: yes" in status.output
        assert "trusted:  yes" in status.output
        assert str(repo) in self._run("list").output

    def test_add_refuses_home_and_root(self, home):
        for p in (str(home), str(home.parent), "/"):
            r = self._run("add", p)
            assert r.exit_code != 0
            assert "refusing" in r.output
        assert wt.authorized_roots() == []
        assert not _cfg().exists()

    def test_remove_drops_authorization_only(self, home, tmp_path):
        repo = _git_checkout(tmp_path / "mine")
        self._run("add", str(repo))
        r = self._run("remove", str(repo))
        assert r.exit_code == 0, r.output
        assert wt.authorized_roots() == []
        assert not wt.approved_path(repo)
        # Claude's own entry is left alone (revoking is a Claude action).
        assert _projects()[str(repo)]["hasTrustDialogAccepted"] is True
        assert self._run("remove", str(repo)).exit_code != 0

    def test_failed_add_leaves_no_authorization(self, home, tmp_path):
        """A failing bootstrap must not leave the root authorized."""
        kept = _git_checkout(tmp_path / "kept")
        assert self._run("add", str(kept)).exit_code == 0
        _cfg().write_text("{broken")
        repo = _git_checkout(tmp_path / "mine")
        r = self._run("add", str(repo))
        assert r.exit_code != 0
        assert "could not read" in r.output
        assert _cfg().read_text() == "{broken"
        # Re-adding an existing root that then fails keeps that root.
        assert self._run("add", str(kept)).exit_code != 0
        assert wt.authorized_roots() == [str(kept)]

    def test_concurrent_adds_keep_every_root(self, home, tmp_path):
        """Parallel ``pm trust add`` runs must not drop each other's roots."""
        import sys
        repos = [_git_checkout(tmp_path / f"c{i}") for i in range(12)]
        env = dict(os.environ,
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        procs = [subprocess.Popen(
            [sys.executable, "-m", "pm_core.wrapper", "trust", "add", str(r)],
            env=env, cwd=str(tmp_path),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for r in repos]
        outs = [p.communicate(timeout=120)[0] for p in procs]
        assert all(p.returncode == 0 for p in procs), outs
        assert sorted(wt.authorized_roots()) == sorted(map(str, repos))
        projects = _projects()
        assert all(projects[str(r)]["hasTrustDialogAccepted"] for r in repos)

    def test_status_unapproved_names_remedy(self, home, tmp_path):
        repo = _git_checkout(tmp_path / "other")
        r = self._run("status", str(repo))
        assert "approved: no" in r.output
        assert f"pm trust add {repo}" in r.output


def test_grace_setting_is_configurable_via_pm_set(home):
    """The grace the bounded-failure message relies on must be settable
    through ``pm set`` (it was rejected as an unknown setting)."""
    from click.testing import CliRunner
    from pm_core.cli import cli
    r = CliRunner().invoke(cli, ["set", "trust-prompt-grace-seconds", "30"])
    assert r.exit_code == 0, r.output
    assert wt.prompt_grace_seconds() == 30.0
    listed = CliRunner().invoke(cli, ["set", "list"]).output
    assert "trust-prompt-grace-seconds" in listed
    bad = CliRunner().invoke(cli, ["set", "trust-prompt-grace-seconds", "soon"])
    assert bad.exit_code != 0
    assert wt.prompt_grace_seconds() == 30.0
