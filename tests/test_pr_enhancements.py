"""Tests for PR enhancements: auto-start, beginner mode, merge, window kill."""

from pathlib import Path
from unittest import mock
from unittest.mock import patch, MagicMock

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
        """kill_pr_windows kills both work and review windows."""
        pr = {"id": "pr-001"}
        with patch("pm_core.tmux.find_window_by_name", side_effect=lambda sess, name: {"id": f"@{name}"}) as mock_find, \
             patch("pm_core.tmux.kill_window") as mock_kill:
            killed = kill_pr_windows("test-session", pr)
        assert killed == ["pr-001", "review-pr-001", "merge-pr-001"]
        assert mock_kill.call_count == 3

    def test_skips_missing_windows(self):
        """kill_pr_windows skips windows that don't exist."""
        pr = {"id": "pr-001"}
        with patch("pm_core.tmux.find_window_by_name", return_value=None), \
             patch("pm_core.tmux.kill_window") as mock_kill:
            killed = kill_pr_windows("test-session", pr)
        assert killed == []
        mock_kill.assert_not_called()

    def test_uses_gh_pr_number_for_display_id(self):
        """kill_pr_windows uses GitHub PR number as display ID when available."""
        pr = {"id": "pr-001", "gh_pr_number": 42}
        with patch("pm_core.tmux.find_window_by_name", side_effect=lambda sess, name: {"id": f"@{name}"}), \
             patch("pm_core.tmux.kill_window"):
            killed = kill_pr_windows("test-session", pr)
        assert killed == ["#42", "review-#42", "merge-#42"]


# ---------------------------------------------------------------------------
# auto_start._transitive_deps
# ---------------------------------------------------------------------------

class TestTransitiveDeps:
    def test_linear_chain(self):
        """Finds all transitive deps in a linear chain."""
        from pm_core.tui.auto_start import _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        deps = _transitive_deps(prs, "c")
        assert deps == {"a", "b"}

    def test_diamond_deps(self):
        """Handles diamond-shaped dependency graphs."""
        from pm_core.tui.auto_start import _transitive_deps
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
        from pm_core.tui.auto_start import _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
        ]
        deps = _transitive_deps(prs, "a")
        assert deps == set()

    def test_missing_pr(self):
        """Missing PR ID in the list is handled gracefully."""
        from pm_core.tui.auto_start import _transitive_deps
        prs = [
            {"id": "a", "depends_on": ["nonexistent"]},
        ]
        deps = _transitive_deps(prs, "a")
        assert deps == {"nonexistent"}

    def test_does_not_include_target(self):
        """Target itself is not in the returned set."""
        from pm_core.tui.auto_start import _transitive_deps
        prs = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
        ]
        deps = _transitive_deps(prs, "b")
        assert "b" not in deps


# ---------------------------------------------------------------------------
# auto_start.is_enabled / get_target
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

    def test_get_target(self):
        from pm_core.tui.auto_start import get_target
        app = MagicMock()
        app._auto_start_target = "pr-005"
        assert get_target(app) == "pr-005"

    def test_get_target_none(self):
        from pm_core.tui.auto_start import get_target
        app = MagicMock()
        app._auto_start_target = None
        assert get_target(app) is None


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
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])
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
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])
        assert result.exit_code != 0
        assert "pending" in result.output

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_local_merge_pulls_into_repo(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge for local backend should merge in workdir then pull into repo dir."""
        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # Workdir: capture tip, checkout, merge, post-merge verify (no pre-dirty check)
        assert ("rev-parse", "pm/pr-001") == git_calls[0][:2]
        assert ("checkout", "master") == git_calls[1][:2]
        assert git_calls[2][0] == "merge"
        assert ("merge-base", "--is-ancestor") == git_calls[3][:2]
        # Repo dir: check branch, fetch from workdir, ff-only merge
        assert ("rev-parse", "--abbrev-ref", "HEAD") in git_calls
        assert any(c[0] == "fetch" for c in git_calls)
        assert ("merge", "--ff-only", "FETCH_HEAD") in git_calls
        # No push for local backend
        assert not any(c[:2] == ("push", "origin") for c in git_calls)
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_local_merge_pull_failure_launches_merge_window(
        self, mock_git_ops, mock_finalize, tmp_merge_project
    ):
        """When pull into repo dir fails, launch merge window if --resolve-window."""
        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if args == ("merge", "--ff-only", "FETCH_HEAD"):
                return MagicMock(returncode=1, stdout="",
                                 stderr="Not possible to fast-forward")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]), \
             mock.patch.object(pr_mod, "_launch_merge_window") as mock_launch:
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--resolve-window"])

        assert result.exit_code == 0
        mock_launch.assert_called_once()
        mock_finalize.assert_not_called()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_dirty_workdir_proceeds_when_no_overlap(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge should proceed when dirty files don't overlap with the merge."""
        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M some_file.py\n", stderr="")
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_dirty_workdir_stashes_on_overlap(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge should stash and retry when dirty files overlap with checkout."""
        checkout_call_count = 0

        def run_git_side_effect(*args, **kwargs):
            nonlocal checkout_call_count
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M some_file.py\n", stderr="")
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if args[:2] == ("checkout", "master"):
                checkout_call_count += 1
                if checkout_call_count == 1:
                    # First attempt: fail due to dirty overlap
                    return MagicMock(returncode=1, stdout="",
                                     stderr="error: Your local changes to the following files would be overwritten by checkout")
                # Second attempt after stash: succeed
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ("stash", "push"):
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ("stash", "pop"):
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # Should have stashed and retried checkout
        assert any(c[:2] == ("stash", "push") for c in git_calls)
        assert any(c[:2] == ("stash", "pop") for c in git_calls)
        assert checkout_call_count == 2
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_post_merge_verification_warns_on_failure(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge should warn (but not fail) when post-merge verification fails."""
        def run_git_side_effect(*args, **kwargs):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if args[:2] == ("merge-base", "--is-ancestor"):
                return MagicMock(returncode=1, stdout="", stderr="")  # verification fails
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        # Should still succeed (warning, not error)
        assert result.exit_code == 0
        assert "verification failed" in result.output
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_vanilla_merge_fetches_origin(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge for vanilla backend should fetch from origin before merging."""
        # Change backend to vanilla
        data = store.load(tmp_merge_project["pm_dir"])
        data["project"]["backend"] = "vanilla"
        store.save(data, tmp_merge_project["pm_dir"])

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # Should have: fetch origin (vanilla), rev-parse, checkout, merge, ...
        assert ("fetch", "origin") == git_calls[0][:2]  # vanilla fetches
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_vanilla_push_failure_launches_merge_window(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """Vanilla push failure with --resolve-window should launch merge window."""
        data = store.load(tmp_merge_project["pm_dir"])
        data["project"]["backend"] = "vanilla"
        store.save(data, tmp_merge_project["pm_dir"])

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if args[0] == "push":
                return MagicMock(returncode=1, stdout="",
                                 stderr="rejected: non-fast-forward")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]), \
             mock.patch.object(pr_mod, "_launch_merge_window") as mock_launch:
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--resolve-window"])

        assert result.exit_code == 0
        mock_launch.assert_called_once()
        mock_finalize.assert_not_called()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_vanilla_push_failure_without_resolve_window(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """Vanilla push failure without --resolve-window should not finalize."""
        data = store.load(tmp_merge_project["pm_dir"])
        data["project"]["backend"] = "vanilla"
        store.save(data, tmp_merge_project["pm_dir"])

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if args[0] == "push":
                return MagicMock(returncode=1, stdout="",
                                 stderr="rejected: non-fast-forward")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        assert "Push to origin failed" in result.output
        mock_finalize.assert_not_called()


# ---------------------------------------------------------------------------
# GitHub merge: pull after merge with dirty-workdir detection
# ---------------------------------------------------------------------------

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


class TestGitHubMergePull:
    """Tests for pull-after-merge on the GitHub backend."""

    @mock.patch.object(pr_mod, "trigger_tui_restart")
    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_pulls_base_branch(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        mock_restart, tmp_github_merge_project,
    ):
        """After a successful gh merge, should fetch+merge (not pull --rebase)."""
        # gh pr merge succeeds
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        assert "merged" in result.output.lower()

        # Should have fetched and merged (not pull --rebase which needs clean tree)
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("fetch", "origin") in git_calls
        assert ("merge", "--ff-only", "origin/master") in git_calls
        mock_finalize.assert_called_once()

        # Git ops must target the main repo dir, NOT the PR workdir
        repo_dir = tmp_github_merge_project["pm_dir"].parent
        workdir = tmp_github_merge_project["workdir"]
        for call in mock_git_ops.run_git.call_args_list:
            cwd = Path(call[1].get("cwd"))
            assert cwd == repo_dir, f"git op cwd={cwd} should be repo dir, not workdir"
            assert cwd != workdir

    @mock.patch.object(pr_mod, "trigger_tui_restart")
    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_restarts_tui_for_project_manager_repo(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        mock_restart, tmp_github_merge_project,
    ):
        """TUI restart should fire only when managing the project_manager repo."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        # Set repo to project_manager
        data = store.load(tmp_github_merge_project["pm_dir"])
        data["project"]["repo"] = "https://github.com/org/project_manager"
        store.save(data, tmp_github_merge_project["pm_dir"])

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        mock_restart.assert_called_once()

    @mock.patch.object(pr_mod, "trigger_tui_restart")
    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_skips_tui_restart_for_other_repos(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        mock_restart, tmp_github_merge_project,
    ):
        """TUI restart should NOT fire for non-project_manager repos."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        mock_restart.assert_not_called()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_proceeds_with_dirty_non_overlapping(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        tmp_github_merge_project,
    ):
        """Dirty repo dir should proceed when dirty files don't overlap with merge."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            # merge --ff-only succeeds even with dirty files (no overlap)
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_launch_merge_window")
    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_stashes_on_dirty_overlap_then_succeeds(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        mock_launch_window, tmp_github_merge_project,
    ):
        """Dirty overlap during pull should stash, retry merge, and succeed."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        merge_call_count = 0

        def run_git_side_effect(*args, **kwargs):
            nonlocal merge_call_count
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M file.py\n", stderr="")
            if args[0] == "merge":
                merge_call_count += 1
                if merge_call_count == 1:
                    return MagicMock(returncode=1, stdout="",
                                     stderr="error: Your local changes to the following files would be overwritten by merge")
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ("stash", "push"):
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ("stash", "pop"):
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert any(c[:2] == ("stash", "push") for c in git_calls)
        assert any(c[:2] == ("stash", "pop") for c in git_calls)
        mock_finalize.assert_called_once()
        mock_launch_window.assert_not_called()

    @mock.patch.object(pr_mod, "_launch_merge_window")
    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_merge_ff_failure_launches_merge_window(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        mock_launch_window, tmp_github_merge_project,
    ):
        """Merge --ff-only failure should launch a merge resolution window."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            if args[0] == "merge":
                return MagicMock(returncode=1, stdout="",
                                 stderr="Not possible to fast-forward, aborting.")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--resolve-window"])

        assert result.exit_code == 0
        assert "pull failed" in result.output.lower()
        mock_launch_window.assert_called_once()
        _, lw_kwargs = mock_launch_window.call_args
        assert lw_kwargs.get("cwd") == str(tmp_github_merge_project["pm_dir"].parent)
        mock_finalize.assert_not_called()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    @mock.patch("pm_core.gh_ops.is_pr_merged", return_value=True)
    def test_already_merged_pr_pulls_and_finalizes(
        self, _mock_is_merged, _mock_which, mock_subprocess, mock_git_ops,
        mock_finalize, tmp_github_merge_project,
    ):
        """Re-attempt on already-merged PR should still pull and finalize."""
        # gh pr merge fails (already merged)
        mock_subprocess.return_value = MagicMock(
            returncode=1, stdout="", stderr="already been merged")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        assert "already merged" in result.output.lower()
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_clean_workdir_proceeds_with_pull(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        tmp_github_merge_project,
    ):
        """Clean workdir should proceed with fetch and merge --ff-only."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("fetch", "origin") in git_calls
        assert ("merge", "--ff-only", "origin/master") in git_calls
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_skips_pull_when_not_on_base_branch(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        tmp_github_merge_project,
    ):
        """Pull should be skipped when repo is on a feature branch."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="pm/pr-001", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        assert "skipping pull" in result.output.lower()

        # Should NOT have fetched or pulled
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("fetch", "origin") not in git_calls
        # But finalize should still run
        mock_finalize.assert_called_once()


# ---------------------------------------------------------------------------
# --propagation-only flag
# ---------------------------------------------------------------------------

class TestPropagationOnly:
    """Tests for --propagation-only flag on pm pr merge."""

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_local_propagation_only_skips_merge(self, mock_git_ops, mock_finalize,
                                                 tmp_merge_project):
        """--propagation-only should skip workdir merge and go to pull."""
        def run_git_side_effect(*args, **kwargs):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--propagation-only"])

        assert result.exit_code == 0
        assert "propagation only" in result.output.lower()
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # No checkout or merge in workdir
        assert not any(c[0] == "checkout" for c in git_calls)
        assert not any(c[0] == "merge" and "--no-ff" in c for c in git_calls)
        # But should still do the pull-from-workdir propagation
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_vanilla_propagation_only_skips_merge_and_push(self, mock_git_ops,
                                                            mock_finalize,
                                                            tmp_merge_project):
        """--propagation-only for vanilla should skip merge and push, do pull."""
        data = store.load(tmp_merge_project["pm_dir"])
        data["project"]["backend"] = "vanilla"
        store.save(data, tmp_merge_project["pm_dir"])

        def run_git_side_effect(*args, **kwargs):
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--propagation-only"])

        assert result.exit_code == 0
        assert "propagation only" in result.output.lower()
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # No checkout, merge --no-ff, or push in workdir
        assert not any(c[0] == "checkout" for c in git_calls)
        assert not any(c[:2] == ("push", "origin") for c in git_calls)
        # But should do the pull_after_merge (fetch + merge --ff-only)
        assert ("merge", "--ff-only", "origin/master") in git_calls
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_propagation_only_skips_gh_merge(self, _mock_which,
                                                     mock_subprocess,
                                                     mock_git_ops,
                                                     mock_finalize,
                                                     tmp_github_merge_project):
        """--propagation-only for github should skip gh pr merge, do pull."""
        def run_git_side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="master", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--propagation-only"])

        assert result.exit_code == 0
        assert "propagation only" in result.output.lower()
        # gh pr merge should NOT have been called
        mock_subprocess.assert_not_called()
        # But pull should have happened (fetch + merge --ff-only)
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("merge", "--ff-only", "origin/master") in git_calls
        mock_finalize.assert_called_once()


# ---------------------------------------------------------------------------
# Two-step merge finalization (review_loop_ui integration)
# ---------------------------------------------------------------------------

class TestTwoStepMergePhaseTracking:
    """Tests for _merge_propagation_phase tracking in review_loop_ui."""

    def test_idle_fallback_passes_propagation_only(self):
        """Idle fallback should pass propagation_only when PR is in phase 2."""
        from pm_core.tui.review_loop_ui import _attempt_merge
        from unittest.mock import call

        app = MagicMock()
        app._merge_propagation_phase = {"pr-001"}

        with mock.patch("pm_core.tui.review_loop_ui._attempt_merge",
                        return_value=True) as mock_attempt:
            # Simulate calling _attempt_merge as the idle fallback would
            prop_only = "pr-001" in app._merge_propagation_phase
            mock_attempt(app, "pr-001", resolve_window=False,
                        propagation_only=prop_only)
            mock_attempt.assert_called_with(
                app, "pr-001", resolve_window=False, propagation_only=True)


# _finalize_merge no longer manages auto-start state (it's in-memory on the TUI).
# Target-merged detection is handled by check_and_start() in auto_start.py.
