"""Tests for PR enhancements: auto-start, beginner mode, merge, window kill."""

from pathlib import Path
from unittest import mock
from unittest.mock import patch, MagicMock

import click
import pytest
from click.testing import CliRunner

from pm_core import store, paths
from pm_core.cli import pr as pr_mod
from pm_core.cli.helpers import kill_pr_windows


# ---------------------------------------------------------------------------
# kill_pr_windows shared helper
# ---------------------------------------------------------------------------

class TestKillPrWindows:
    def test_kills_work_and_review_windows(self):
        """kill_pr_windows kills work, review, and QA windows."""
        pr = {"id": "pr-001"}
        with patch("pm_core.tmux.find_window_by_name", side_effect=lambda sess, name: {"id": f"@{name}"}) as mock_find, \
             patch("pm_core.tmux.kill_window") as mock_kill, \
             patch("pm_core.tmux.list_windows", return_value=[]):
            killed = kill_pr_windows("test-session", pr)
        assert killed == ["pr-001", "review-pr-001", "merge-pr-001",
                          "qa-pr-001", "signoff-pr-001"]
        assert mock_kill.call_count == 5

    def test_skips_missing_windows(self):
        """kill_pr_windows skips windows that don't exist."""
        pr = {"id": "pr-001"}
        with patch("pm_core.tmux.find_window_by_name", return_value=None), \
             patch("pm_core.tmux.kill_window") as mock_kill, \
             patch("pm_core.tmux.list_windows", return_value=[]):
            killed = kill_pr_windows("test-session", pr)
        assert killed == []
        mock_kill.assert_not_called()

    def test_uses_gh_pr_number_for_display_id(self):
        """kill_pr_windows uses GitHub PR number as display ID when available."""
        pr = {"id": "pr-001", "gh_pr_number": 42}
        with patch("pm_core.tmux.find_window_by_name", side_effect=lambda sess, name: {"id": f"@{name}"}), \
             patch("pm_core.tmux.kill_window"), \
             patch("pm_core.tmux.list_windows", return_value=[]):
            killed = kill_pr_windows("test-session", pr)
        assert killed == ["#42", "review-#42", "merge-#42", "qa-#42",
                          "signoff-#42"]


# ---------------------------------------------------------------------------
# autostart_state.transitive_deps
# ---------------------------------------------------------------------------

class TestTransitiveDeps:
    def test_linear_chain(self):
        """Finds all transitive deps in a linear chain."""
        from pm_core.autostart_state import transitive_deps as _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        deps = _transitive_deps(prs, "c")
        assert deps == {"a", "b"}

    def test_diamond_deps(self):
        """Handles diamond-shaped dependency graphs."""
        from pm_core.autostart_state import transitive_deps as _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["a"]},
            {"id": "d", "depends_on": ["b", "c"]},
        ]
        deps = _transitive_deps(prs, "d")
        assert deps == {"a", "b", "c"}

    def test_no_deps(self):
        """PR with no deps returns empty set."""
        from pm_core.autostart_state import transitive_deps as _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
        ]
        deps = _transitive_deps(prs, "a")
        assert deps == set()

    def test_missing_pr(self):
        """Missing PR ID in the list is handled gracefully."""
        from pm_core.autostart_state import transitive_deps as _transitive_deps
        prs = [
            {"id": "a", "depends_on": ["nonexistent"]},
        ]
        deps = _transitive_deps(prs, "a")
        assert deps == {"nonexistent"}

    def test_does_not_include_target(self):
        """Target itself is not in the returned set."""
        from pm_core.autostart_state import transitive_deps as _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
        ]
        deps = _transitive_deps(prs, "b")
        assert "b" not in deps


# ---------------------------------------------------------------------------
# auto_start.is_enabled / get_targets
# ---------------------------------------------------------------------------

class TestAutoStartHelpers:
    def test_is_enabled_true(self):
        from pm_core.tui.auto_start import is_enabled
        app = MagicMock()
        app._auto_start = True
        assert is_enabled(app) is True

    def test_is_enabled_false(self):
        from pm_core.tui.auto_start import is_enabled
        app = MagicMock()
        app._auto_start = False
        assert is_enabled(app) is False

    def test_is_enabled_missing(self):
        from pm_core.tui.auto_start import is_enabled
        app = MagicMock()
        app._auto_start = False
        assert is_enabled(app) is False

    def test_get_targets(self):
        from pm_core.tui.auto_start import get_targets
        app = MagicMock()
        app._auto_start_targets = {"pr-005": {}, "pr-002": {}}
        assert get_targets(app) == ["pr-005", "pr-002"]

    def test_get_targets_non_dict_is_empty(self):
        """A MagicMock/legacy attribute must read as 'no targets'."""
        from pm_core.tui.auto_start import get_targets, in_scope
        app = MagicMock()
        app._auto_start = True
        app._auto_start_all = False
        app._data = {"prs": [{"id": "pr-001"}]}
        assert get_targets(app) == []
        assert in_scope(app, "pr-001") is False


# ---------------------------------------------------------------------------
# _auto_start_qa_loops
# ---------------------------------------------------------------------------

class TestAutoStartQALoops:
    """Tests for _auto_start_qa_loops recovery and filtering."""

    def _make_app(self, prs, target=None):
        """Create a mock app with auto-start enabled."""
        app = MagicMock()
        app._auto_start = True
        app._auto_start_targets = {target: {}} if target else {}
        app._auto_start_all = not target
        app._data = {"prs": prs}
        app._qa_loops = {}
        return app

    def test_starts_qa_for_qa_status_pr(self):
        """QA loop is started for a PR in qa status with a workdir."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/w", "depends_on": []},
        ]
        app = self._make_app(prs)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        mock_start.assert_called_once_with(app, "pr-a")

    def test_skips_non_qa_status(self):
        """PRs not in qa status are ignored."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "in_review", "workdir": "/tmp/w", "depends_on": []},
            {"id": "pr-b", "status": "pending", "workdir": "/tmp/w", "depends_on": []},
            {"id": "pr-c", "status": "merged", "workdir": "/tmp/w", "depends_on": []},
        ]
        app = self._make_app(prs)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        mock_start.assert_not_called()

    def test_skips_pr_without_workdir(self):
        """PRs without a workdir are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "qa", "depends_on": []},
        ]
        app = self._make_app(prs)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        mock_start.assert_not_called()

    def test_respects_target_dependency_tree(self):
        """Only QA PRs in the target's dependency tree are started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/a", "depends_on": []},
            {"id": "pr-b", "status": "qa", "workdir": "/tmp/b", "depends_on": ["pr-a"]},
            {"id": "pr-c", "status": "qa", "workdir": "/tmp/c", "depends_on": []},  # outside tree
        ]
        app = self._make_app(prs, target="pr-b")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        # pr-a (dep of pr-b) and pr-b (target) should be started; pr-c should not
        started_ids = [c[0][1] for c in mock_start.call_args_list]
        assert "pr-a" in started_ids
        assert "pr-b" in started_ids
        assert "pr-c" not in started_ids

    def test_skips_running_qa_loop(self):
        """PRs with a running QA loop are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        from pm_core.qa_loop import QALoopState
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/w", "depends_on": []},
        ]
        app = self._make_app(prs)
        running_state = QALoopState(pr_id="pr-a")
        running_state.running = True
        app._qa_loops["pr-a"] = running_state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        mock_start.assert_not_called()

    def test_skips_completed_qa_loop_awaiting_poll(self):
        """PRs with a completed QA loop (verdict set, not yet cleaned up) are skipped.

        This prevents a race between check_and_start (triggered by sync)
        and poll_qa_state (which processes completions).
        """
        from pm_core.tui.auto_start import _auto_start_qa_loops
        from pm_core.qa_loop import QALoopState
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/w", "depends_on": []},
        ]
        app = self._make_app(prs)
        done_state = QALoopState(pr_id="pr-a")
        done_state.running = False
        done_state.latest_verdict = "PASS"
        app._qa_loops["pr-a"] = done_state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        mock_start.assert_not_called()

    def test_noop_when_auto_start_disabled(self):
        """No QA loops started when auto-start is off."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/w", "depends_on": []},
        ]
        app = MagicMock()
        app._auto_start = False
        app._qa_loops = {}

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        mock_start.assert_not_called()

    def test_no_target_starts_all_qa_prs(self):
        """Without a target, all qa-status PRs get QA started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/a", "depends_on": []},
            {"id": "pr-b", "status": "qa", "workdir": "/tmp/b", "depends_on": []},
        ]
        app = self._make_app(prs, target=None)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        assert mock_start.call_count == 2

    def test_recovery_after_restart_starts_qa(self):
        """After TUI restart (empty _qa_loops), qa-status PRs get QA started.

        Simulates the breadcrumb recovery path: auto-start is re-enabled,
        _qa_loops is empty (in-memory state lost), and _auto_start_qa_loops
        picks up qa-status PRs.
        """
        from pm_core.tui.auto_start import _auto_start_qa_loops
        prs = [
            {"id": "pr-a", "status": "qa", "workdir": "/tmp/a", "depends_on": []},
            {"id": "pr-b", "status": "qa", "workdir": "/tmp/b", "depends_on": ["pr-a"]},
            {"id": "pr-c", "status": "in_review", "workdir": "/tmp/c", "depends_on": []},
        ]
        # Simulates post-restart: auto-start enabled, empty qa_loops
        app = self._make_app(prs, target="pr-b")
        assert app._qa_loops == {}

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)
        # pr-a and pr-b are in qa status and in dep tree; pr-c is in_review
        started_ids = [c[0][1] for c in mock_start.call_args_list]
        assert set(started_ids) == {"pr-a", "pr-b"}


# ---------------------------------------------------------------------------
# _beginner_mode_guide_section
# ---------------------------------------------------------------------------

class TestBeginnerModeGuideSection:
    def test_not_configured_offers_enable(self, tmp_path):
        """When beginner-mode is never configured, prompt to ask user."""
        from pm_core.guide import _beginner_mode_guide_section
        with patch.object(paths, "pm_home", return_value=tmp_path):
            result = _beginner_mode_guide_section()
        assert "Are you new to programming" in result
        assert "pm setting beginner-mode on" in result

    def test_enabled_confirms(self, tmp_path):
        """When beginner-mode is enabled, confirm it's on."""
        from pm_core.guide import _beginner_mode_guide_section
        with patch.object(paths, "pm_home", return_value=tmp_path):
            paths.set_global_setting("beginner-mode", True)
            result = _beginner_mode_guide_section()
        assert "currently enabled" in result
        assert "pm setting beginner-mode off" in result

    def test_disabled_returns_empty(self, tmp_path):
        """When beginner-mode is explicitly disabled, return empty string."""
        from pm_core.guide import _beginner_mode_guide_section
        with patch.object(paths, "pm_home", return_value=tmp_path):
            paths.set_global_setting("beginner-mode", False)
            result = _beginner_mode_guide_section()
        assert result == ""


# ---------------------------------------------------------------------------
# pm pr merge — CLI command
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_merge_project(tmp_path):
    """Create a project with an in_review PR for merge testing."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / ".git").mkdir()

    data = {
        "project": {
            "name": "test-project",
            "repo": str(tmp_path),
            "base_branch": "master",
            "backend": "local",
        },
        "prs": [
            {
                "id": "pr-001",
                "title": "Test PR",
                "description": "Test",
                "branch": "pm/pr-001",
                "status": "in_review",
                "workdir": str(workdir),
            }
        ],
        "plans": [],
    }
    store.save(data, pm_dir)
    return {"pm_dir": pm_dir, "workdir": workdir, "data": data}


class TestPrMerge:
    @mock.patch.object(pr_mod, "_finalize_merge")
    def test_rejects_already_merged(self, _mock_final, tmp_merge_project):
        """pr merge on an already-merged PR should fail."""
        data = store.load(tmp_merge_project["pm_dir"])
        data["prs"][0]["status"] = "merged"
        store.save(data, tmp_merge_project["pm_dir"])

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--no-signoff-check"])
        assert result.exit_code != 0
        assert "already merged" in result.output

    @mock.patch.object(pr_mod, "_finalize_merge")
    def test_rejects_pending_pr(self, _mock_final, tmp_merge_project):
        """pr merge on a pending PR should fail."""
        data = store.load(tmp_merge_project["pm_dir"])
        data["prs"][0]["status"] = "pending"
        store.save(data, tmp_merge_project["pm_dir"])

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--no-signoff-check"])
        assert result.exit_code != 0
        assert "pending" in result.output

    # The publish path itself (gate, candidate, CAS per backend) is covered
    # against real git repositories in tests/test_merge_publish.py.


@pytest.fixture
def tmp_github_merge_project(tmp_path):
    """Create a project with github backend and an in_review PR."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / ".git").mkdir()

    data = {
        "project": {
            "name": "test-project",
            "repo": str(tmp_path),
            "base_branch": "master",
            "backend": "github",
        },
        "prs": [
            {
                "id": "pr-001",
                "gh_pr_number": 42,
                "title": "Test PR",
                "description": "Test",
                "branch": "pm/pr-001",
                "status": "in_review",
                "workdir": str(workdir),
            }
        ],
        "plans": [],
    }
    store.save(data, pm_dir)
    return {"pm_dir": pm_dir, "workdir": workdir, "data": data}


class TestPullAfterMerge:
    """Post-publication update of the main repo checkout (recovery only)."""

    def _pull(self, tmp_path, run_git, *, resolve_window=False):
        data = {"project": {"name": "p", "repo": str(tmp_path),
                            "base_branch": "master", "backend": "github"},
                "prs": [{"id": "pr-001", "title": "T",
                         "branch": "pm/pr-001", "status": "sign_off"}]}
        with mock.patch("pm_core.cli.pr.git_ops") as g, \
             mock.patch.object(pr_mod, "_launch_merge_window") as launch:
            g.run_git.side_effect = run_git
            ok = pr_mod._pull_after_merge(
                data, data["prs"][0], str(tmp_path), "master",
                resolve_window=resolve_window, background=False,
                transcript=None)
        return ok, [c[0] for c in g.run_git.call_args_list], \
            [c[1].get("cwd") for c in g.run_git.call_args_list], launch

    def test_fetches_and_fast_forwards_in_repo_dir(self, tmp_path):
        def rg(*args, **kw):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        ok, calls, cwds, launch = self._pull(tmp_path, rg)
        assert ok
        assert ("fetch", "origin") in calls
        assert ("merge", "--ff-only", "origin/master") in calls
        assert set(cwds) == {str(tmp_path)}
        launch.assert_not_called()

    def test_dirty_overlap_stashes_then_succeeds(self, tmp_path):
        n = {"merge": 0}

        def rg(*args, **kw):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M file.py\n", stderr="")
            if args[0] == "merge":
                n["merge"] += 1
                if n["merge"] == 1:
                    return MagicMock(returncode=1, stdout="", stderr=(
                        "error: Your local changes to the following files "
                        "would be overwritten by merge"))
            return MagicMock(returncode=0, stdout="", stderr="")
        ok, calls, _, launch = self._pull(tmp_path, rg)
        assert ok
        assert any(c[:2] == ("stash", "push") for c in calls)
        assert any(c[:2] == ("stash", "pop") for c in calls)
        launch.assert_not_called()

    def test_ff_failure_opens_recovery_window_in_repo_dir(self, tmp_path):
        def rg(*args, **kw):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            if args[0] == "merge":
                return MagicMock(returncode=1, stdout="",
                                 stderr="Not possible to fast-forward, aborting.")
            return MagicMock(returncode=0, stdout="", stderr="")
        ok, _, _, launch = self._pull(tmp_path, rg, resolve_window=True)
        assert ok is False
        launch.assert_called_once()
        assert launch.call_args.kwargs["cwd"] == str(tmp_path)

    def test_skips_when_repo_not_on_base_branch(self, tmp_path):
        def rg(*args, **kw):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="feature", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        ok, calls, _, _ = self._pull(tmp_path, rg)
        assert ok
        assert ("fetch", "origin") not in calls

    @pytest.mark.parametrize("repo,restarts", [
        ("https://github.com/org/project_manager", True),
        ("https://github.com/org/other", False)])
    def test_tui_restart_only_for_project_manager_repo(self, tmp_path, repo,
                                                       restarts):
        data = {"project": {"repo": repo}}
        with mock.patch.object(pr_mod, "_finalize_merge") as fin, \
             mock.patch.object(pr_mod, "trigger_tui_restart") as rs:
            pr_mod._after_publish(tmp_path, data, {"id": "pr-001"}, None)
        fin.assert_called_once()
        assert rs.called is restarts


# _finalize_merge no longer manages auto-start state (it's in-memory on the TUI).
# Target-merged detection is handled by check_and_start() in auto_start.py.


# ---------------------------------------------------------------------------
# pr start: spec_pending blocking gate
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_start_project(tmp_path):
    """Create a project with a pending PR for start testing."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()

    data = {
        "project": {
            "name": "test-project",
            "repo": str(tmp_path),
            "base_branch": "master",
            "backend": "local",
        },
        "prs": [
            {
                "id": "pr-001",
                "title": "Test PR",
                "description": "Test",
                "branch": "pm/pr-001",
                "status": "pending",
            }
        ],
        "plans": [],
    }
    store.save(data, pm_dir)
    return {"pm_dir": pm_dir, "data": data}


class TestPrStartSpecGate:
    def test_blocks_when_spec_pending(self, tmp_start_project):
        """pr start should exit non-zero when spec_pending is set."""
        data = store.load(tmp_start_project["pm_dir"])
        data["prs"][0]["spec_pending"] = {
            "phase": "impl",
            "generated_at": "2026-01-01T00:00:00",
        }
        store.save(data, tmp_start_project["pm_dir"])

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert result.exit_code != 0
        assert "pending review" in result.output or "spec-approve" in result.output

    def test_allows_start_when_no_spec_pending(self, tmp_start_project, tmp_path):
        """pr start should proceed normally when no spec is pending."""
        import yaml as _yaml
        committed_yaml = _yaml.dump({
            "project": {"name": "test", "repo": str(tmp_path), "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "Test", "status": "pending"}],
        })
        git_show_result = MagicMock(returncode=0, stdout=committed_yaml)

        # We just need to verify the gate doesn't block — mock everything after
        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]), \
             mock.patch("pm_core.cli.pr.git_ops") as mock_git, \
             mock.patch("pm_core.cli.pr.find_claude", return_value=None), \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None), \
             mock.patch("pm_core.cli.pr.store.locked_update"), \
             mock.patch("pm_core.cli.pr.trigger_tui_refresh"), \
             mock.patch("pm_core.cli.pr._resolve_repo_id"), \
             mock.patch("pm_core.cli.pr.prompt_gen.generate_prompt", return_value="prompt"):
            mock_git.clone.return_value = None
            mock_git.run_git.return_value = MagicMock(returncode=0, stdout="abc12345\n")
            mock_git.run_git.side_effect = [
                git_show_result,  # git show for committed check
                MagicMock(returncode=0, stdout="abc12345\n"),  # rev-parse for base hash
            ]
            mock_git.is_git_repo.return_value = False
            mock_git.checkout_branch.return_value = None
            # Should not exit with error 1 (spec gate)
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        # Should NOT fail with the spec gate message
        assert "pending review" not in result.output


# ---------------------------------------------------------------------------
# pr start: committed-state gate
# ---------------------------------------------------------------------------

class TestPrStartCommittedGate:
    """pr start should refuse if the PR is not in the committed project.yaml."""

    def test_blocks_when_pr_not_committed(self, tmp_start_project):
        """pr start should exit non-zero when PR is not in committed project.yaml."""
        runner = CliRunner()
        # git show returns the file content but without the PR
        git_show_result = MagicMock(returncode=0, stdout="project:\n  name: test\nprs: []\n")
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]), \
             mock.patch("pm_core.cli.pr.git_ops.run_git", return_value=git_show_result), \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert result.exit_code != 0
        assert "not committed" in result.output

    def test_blocks_when_git_show_fails(self, tmp_start_project):
        """pr start should exit non-zero when git show fails (e.g. no commits)."""
        runner = CliRunner()
        git_show_result = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo")
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]), \
             mock.patch("pm_core.cli.pr.git_ops.run_git", return_value=git_show_result), \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert result.exit_code != 0
        assert "not committed" in result.output

    def test_blocks_when_committed_yaml_invalid(self, tmp_start_project):
        """pr start should exit non-zero when committed project.yaml is invalid YAML."""
        runner = CliRunner()
        git_show_result = MagicMock(returncode=0, stdout=": {invalid yaml\n  - [broken")
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]), \
             mock.patch("pm_core.cli.pr.git_ops.run_git", return_value=git_show_result), \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert result.exit_code != 0
        assert "not committed" in result.output

    def test_blocks_when_committed_yaml_empty(self, tmp_start_project):
        """Empty committed project.yaml (yaml.safe_load returns None) should not crash."""
        runner = CliRunner()
        git_show_result = MagicMock(returncode=0, stdout="")
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]), \
             mock.patch("pm_core.cli.pr.git_ops.run_git", return_value=git_show_result), \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert result.exit_code != 0
        assert "not committed" in result.output
        assert "NoneType" not in (result.output + (result.stderr if hasattr(result, 'stderr') and result.stderr else ""))

    def test_allows_start_when_pr_committed(self, tmp_start_project, tmp_path):
        """pr start should proceed when PR exists in committed project.yaml."""
        import yaml as _yaml
        committed_yaml = _yaml.dump({
            "project": {"name": "test", "repo": str(tmp_path), "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "Test", "status": "pending"}],
        })
        git_show_result = MagicMock(returncode=0, stdout=committed_yaml)

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_start_project["pm_dir"]), \
             mock.patch("pm_core.cli.pr.git_ops") as mock_git, \
             mock.patch("pm_core.cli.pr.find_claude", return_value=None), \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None), \
             mock.patch("pm_core.cli.pr.store.locked_update"), \
             mock.patch("pm_core.cli.pr.trigger_tui_refresh"), \
             mock.patch("pm_core.cli.pr._resolve_repo_id"), \
             mock.patch("pm_core.cli.pr.prompt_gen.generate_prompt", return_value="prompt"):
            # First call is the committed-state check (git show); rest are clone ops
            mock_git.run_git.return_value = MagicMock(returncode=0, stdout="abc12345\n")
            mock_git.run_git.side_effect = [
                git_show_result,  # git show for committed check
                MagicMock(returncode=0, stdout="abc12345\n"),  # rev-parse for base hash
            ]
            mock_git.clone.return_value = None
            mock_git.is_git_repo.return_value = False
            mock_git.checkout_branch.return_value = None
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert "not committed" not in (result.output or "")

    def test_standalone_dir_uses_correct_git_show_path(self, tmp_path):
        """When is_internal_pm_dir returns False, git show uses project.yaml and cwd=root."""
        standalone = tmp_path / "standalone"
        standalone.mkdir()

        data = {
            "project": {
                "name": "test-project",
                "repo": str(tmp_path),
                "base_branch": "master",
                "backend": "local",
            },
            "prs": [
                {
                    "id": "pr-001",
                    "title": "Test PR",
                    "description": "Test",
                    "branch": "pm/pr-001",
                    "status": "pending",
                }
            ],
            "plans": [],
        }
        store.save(data, standalone)

        runner = CliRunner()
        git_show_result = MagicMock(returncode=0, stdout="project:\n  name: test\nprs: []\n")
        with mock.patch.object(pr_mod, "state_root", return_value=standalone), \
             mock.patch("pm_core.cli.pr.git_ops.run_git", return_value=git_show_result) as mock_run_git, \
             mock.patch("pm_core.cli.pr._get_pm_session", return_value=None):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        assert result.exit_code != 0
        assert "not committed" in result.output
        mock_run_git.assert_called_once_with(
            "show", "master:project.yaml", cwd=str(standalone), check=False
        )


class TestGitHubCloseResilience:
    """`pm pr close` must still clean up local state when gh is unavailable."""

    @mock.patch("pm_core.gh_ops.close_pr", side_effect=SystemExit(1))
    def test_close_continues_local_cleanup_on_gh_systemexit(
        self, _mock_close, tmp_github_merge_project,
    ):
        """gh missing/unauthed (SystemExit from _check_gh via run_gh) must not
        abort close: warn, then still remove the workdir and the PR entry."""
        pm_dir = tmp_github_merge_project["pm_dir"]
        workdir = tmp_github_merge_project["workdir"]
        assert workdir.exists()

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=pm_dir):
            result = runner.invoke(pr_mod.pr, ["close", "pr-001"])

        assert result.exit_code == 0, result.output
        assert "Warning: Could not close GitHub PR" in result.output
        # Local cleanup still happened despite the gh failure.
        assert not workdir.exists()
        data = store.load(pm_dir)
        assert all(p["id"] != "pr-001" for p in data.get("prs", []))


class TestFinalizeMergeOutput:
    """The merged line is printed last (the TUI ``g`` log line shows only
    the final stdout line) and names only the PRs this merge unblocked."""

    def _finalize(self, tmp_path, prs):
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        store.save({"project": {"name": "p", "repo": str(tmp_path),
                                "base_branch": "master"},
                    "prs": prs, "plans": []}, pm_dir)
        entry = next(p for p in prs if p["id"] == "pr-a")

        @click.command()
        def run():
            pr_mod._finalize_merge(pm_dir, entry, "pr-a")

        with mock.patch.object(pr_mod, "trigger_tui_refresh"), \
                mock.patch("pm_core.cli.helpers._find_tui_pane",
                           return_value=(None, None)):
            result = CliRunner().invoke(run)
        assert result.exit_code == 0, result.output
        return result.output.strip().splitlines()

    def test_last_line_names_only_unblocked_dependents(self, tmp_path):
        lines = self._finalize(tmp_path, [
            {"id": "pr-a", "title": "A", "status": "sign_off"},
            {"id": "pr-b", "title": "B", "status": "pending",
             "depends_on": ["pr-a"]},
            {"id": "pr-x", "title": "X", "status": "pending"},
        ])
        assert lines[-1] == "PR pr-a marked as merged (newly ready: pr-b)."
        assert "Newly ready PRs:" in lines

    def test_no_dependents_plain_merged_line(self, tmp_path):
        lines = self._finalize(tmp_path, [
            {"id": "pr-a", "title": "A", "status": "sign_off"},
            {"id": "pr-x", "title": "X", "status": "pending"},
        ])
        assert lines[-1] == "PR pr-a marked as merged."


# ---------------------------------------------------------------------------
# pr start fast path: printed session names the grouped session it switched
# ---------------------------------------------------------------------------

class TestPrStartFastPathSessionMessage:
    """`pr start` on an existing window reports the session it targeted.

    select_window targets the calling client's grouped session
    (<base>~N), not the base session, so the message must name that one
    — QA S24 observed the popup print the base name while the grouped
    client switched.
    """

    def _invoke(self, tmp_path, grouped_session):
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        workdir = tmp_path / "work"
        workdir.mkdir()
        store.save({
            "project": {"name": "test", "repo": str(tmp_path),
                        "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "Test", "branch": "pm/pr-001",
                     "status": "in_progress", "workdir": str(workdir)}],
        }, pm_dir)

        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "state_root", return_value=pm_dir), \
             patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"):
            mock_tmux.session_exists.return_value = True
            mock_tmux.find_window_by_name.return_value = {
                "id": "@1", "index": "1", "name": "pr-001"}
            mock_tmux.current_or_base_session.return_value = grouped_session
            result = CliRunner().invoke(pr_mod.pr, ["start", "pr-001"])
        return result

    def test_names_grouped_session_not_base(self, tmp_path):
        result = self._invoke(tmp_path, "pm-sess~2")
        assert result.exit_code == 0, result.output
        assert ("Switched to existing window 'pr-001' (session: pm-sess~2)"
                in result.output)
        assert "(session: pm-sess)" not in result.output
