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
    def test_local_merge_calls_git(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge for local backend should run git checkout + merge + push."""
        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean workdir
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        # Should have called: status --porcelain, rev-parse, checkout, merge, merge-base --is-ancestor, push
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("status", "--porcelain") == git_calls[0][:2]  # dirty check
        assert ("rev-parse", "pm/pr-001") == git_calls[1][:2]  # capture tip
        assert ("checkout", "master") == git_calls[2][:2]
        assert git_calls[3][0] == "merge"
        assert ("merge-base", "--is-ancestor") == git_calls[4][:2]  # post-merge verify
        assert git_calls[5][:3] == ("push", "origin", "master")
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_dirty_workdir_aborts_merge(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge should abort if the workdir has uncommitted changes."""
        # Make status --porcelain return dirty output
        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M some_file.py\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code != 0
        assert "uncommitted changes" in result.output
        mock_finalize.assert_not_called()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    def test_post_merge_verification_warns_on_failure(self, mock_git_ops, mock_finalize, tmp_merge_project):
        """pr merge should warn (but not fail) when post-merge verification fails."""
        call_count = [0]
        def run_git_side_effect(*args, **kwargs):
            call_count[0] += 1
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            if args[0] == "checkout":
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[0] == "merge":
                return MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ("merge-base", "--is-ancestor"):
                return MagicMock(returncode=1, stdout="", stderr="")  # verification fails
            if args[0] == "push":
                return MagicMock(returncode=0, stdout="", stderr="")
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
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean workdir
            if args[0] == "rev-parse":
                return MagicMock(returncode=0, stdout="abc1234\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # Should have: status, fetch, rev-parse, checkout, merge, merge-base, push
        assert ("status", "--porcelain") == git_calls[0][:2]
        assert ("fetch", "origin") == git_calls[1][:2]  # vanilla fetches
        mock_finalize.assert_called_once()



# ---------------------------------------------------------------------------
# GitHub merge: pull after merge with stash/unstash
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

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_pulls_base_branch(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        tmp_github_merge_project,
    ):
        """After a successful gh merge, should fetch/checkout/pull base branch."""
        # gh pr merge succeeds
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect
        mock_git_ops.pull_rebase.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        assert "merged" in result.output.lower()

        # Should have fetched and checked out base branch
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("fetch", "origin") in git_calls
        assert ("checkout", "master") in git_calls
        mock_git_ops.pull_rebase.assert_called_once()
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_github_merge_stashes_dirty_workdir(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        tmp_github_merge_project,
    ):
        """Dirty workdir should be stashed before pull, then unstashed."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M file.py\n", stderr="")  # dirty
            if args[0] == "stash" and len(args) == 1:
                return MagicMock(returncode=0, stdout="Saved working directory", stderr="")
            if args[:2] == ("stash", "pop"):
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect
        mock_git_ops.pull_rebase.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        assert "stash" in result.output.lower()

        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        assert ("stash",) in git_calls
        assert ("stash", "pop") in git_calls
        mock_finalize.assert_called_once()

    @mock.patch.object(pr_mod, "_launch_merge_window")
    @mock.patch.object(pr_mod, "_finalize_merge")
    @mock.patch("pm_core.cli.pr.git_ops")
    @mock.patch("subprocess.run")
    @mock.patch("shutil.which", return_value="/usr/bin/gh")
    def test_stash_pop_conflict_launches_merge_window(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        mock_launch_window, tmp_github_merge_project,
    ):
        """Stash pop conflicts should launch a merge resolution window."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout=" M file.py\n", stderr="")  # dirty
            if args[0] == "stash" and len(args) == 1:
                return MagicMock(returncode=0, stdout="Saved working directory", stderr="")
            if args[:2] == ("stash", "pop"):
                return MagicMock(returncode=1, stdout="CONFLICT (content): file.py",
                                 stderr="error: could not restore")
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect
        mock_git_ops.pull_rebase.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001",
                                               "--resolve-window"])

        assert result.exit_code == 0
        assert "conflict" in result.output.lower()
        mock_launch_window.assert_called_once()
        # Finalize should NOT be called — the merge window handles it
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
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect
        mock_git_ops.pull_rebase.return_value = MagicMock(returncode=0)

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
    def test_clean_workdir_skips_stash(
        self, _mock_which, mock_subprocess, mock_git_ops, mock_finalize,
        tmp_github_merge_project,
    ):
        """Clean workdir should not stash/unstash."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def run_git_side_effect(*args, **kwargs):
            if args[0] == "status":
                return MagicMock(returncode=0, stdout="", stderr="")  # clean
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_git_ops.run_git.side_effect = run_git_side_effect
        mock_git_ops.pull_rebase.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with mock.patch.object(pr_mod, "state_root",
                               return_value=tmp_github_merge_project["pm_dir"]):
            result = runner.invoke(pr_mod.pr, ["merge", "pr-001"])

        assert result.exit_code == 0
        git_calls = [c[0] for c in mock_git_ops.run_git.call_args_list]
        # Should NOT have stash or stash pop
        assert ("stash",) not in git_calls
        assert ("stash", "pop") not in git_calls
        mock_finalize.assert_called_once()


# _finalize_merge no longer manages auto-start state (it's in-memory on the TUI).
# Target-merged detection is handled by check_and_start() in auto_start.py.
