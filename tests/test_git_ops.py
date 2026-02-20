"""Tests for pm_core.git_ops — git operations (run_git, clone, checkout, etc.).

Note: get_git_root, get_github_repo_name are tested in test_dedup.py.
      select_remote, list_remotes are tested in test_git_remote_detection.py.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

from pm_core.git_ops import (
    run_git,
    is_git_repo,
    clone,
    checkout_branch,
    pull_rebase,
    commit_and_push,
    sync_state,
    auto_commit_state,
    push_pm_branch,
    _checkout_and_restore_pm,
)


# ---------------------------------------------------------------------------
# run_git
# ---------------------------------------------------------------------------

class TestRunGit:
    @patch("pm_core.git_ops.subprocess.run")
    @patch("pm_core.git_ops.log_shell_command")
    def test_success(self, mock_log, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = run_git("status")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "status"]
        assert result.returncode == 0

    @patch("pm_core.git_ops.subprocess.run")
    @patch("pm_core.git_ops.log_shell_command")
    def test_failure_logs_returncode(self, mock_log, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = run_git("push", check=False)
        assert result.returncode == 1
        # Should log twice: once for the command, once for the failure
        assert mock_log.call_count == 2

    @patch("pm_core.git_ops.subprocess.run")
    @patch("pm_core.git_ops.log_shell_command")
    def test_passes_cwd(self, mock_log, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        run_git("status", cwd="/tmp/test")
        assert mock_run.call_args[1]["cwd"] == "/tmp/test"

    @patch("pm_core.git_ops.subprocess.run")
    @patch("pm_core.git_ops.log_shell_command")
    def test_multiple_args(self, mock_log, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        run_git("commit", "-m", "message")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "commit", "-m", "message"]


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------

class TestIsGitRepo:
    @patch("pm_core.git_ops.subprocess.run")
    def test_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert is_git_repo(Path("/tmp")) is True

    @patch("pm_core.git_ops.subprocess.run")
    def test_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128)
        assert is_git_repo(Path("/tmp")) is False


# ---------------------------------------------------------------------------
# clone
# ---------------------------------------------------------------------------

class TestClone:
    @patch("pm_core.git_ops.run_git")
    def test_basic_clone(self, mock_rg):
        mock_rg.return_value = MagicMock(returncode=0)
        clone("https://github.com/org/repo.git", Path("/tmp/dest"))
        mock_rg.assert_called_once_with("clone", "https://github.com/org/repo.git", "/tmp/dest", check=False)

    @patch("pm_core.git_ops.run_git")
    def test_clone_with_branch(self, mock_rg):
        mock_rg.return_value = MagicMock(returncode=0)
        clone("url", Path("/tmp/dest"), branch="main")
        args = mock_rg.call_args_list[0][0]
        assert "--branch" in args
        assert "main" in args

    @patch("pm_core.git_ops.run_git")
    def test_clone_with_branch_fallback(self, mock_rg):
        """When clone with --branch fails, retries without it."""
        mock_rg.side_effect = [
            MagicMock(returncode=128),  # clone with --branch fails
            MagicMock(returncode=0),    # clone without --branch succeeds
        ]
        clone("url", Path("/tmp/dest"), branch="main")
        assert mock_rg.call_count == 2
        # Second call should not have --branch
        second_args = mock_rg.call_args_list[1][0]
        assert "--branch" not in second_args


# ---------------------------------------------------------------------------
# checkout_branch
# ---------------------------------------------------------------------------

class TestCheckoutBranch:
    @patch("pm_core.git_ops.run_git")
    def test_simple_checkout(self, mock_rg):
        checkout_branch(Path("/tmp"), "main")
        mock_rg.assert_called_once_with("checkout", "main", cwd=Path("/tmp"))

    @patch("pm_core.git_ops.run_git")
    def test_create_branch_new(self, mock_rg):
        """When branch doesn't exist locally or on remote, creates with -b."""
        mock_rg.return_value = MagicMock(stdout="", returncode=1)
        checkout_branch(Path("/tmp"), "feature", create=True)
        # First call: rev-parse (local check), second: ls-remote, third: checkout -b
        calls = mock_rg.call_args_list
        assert calls[0][0][:2] == ("rev-parse", "--verify")
        assert calls[1][0][0] == "ls-remote"
        assert calls[2][0] == ("checkout", "-b", "feature")

    @patch("pm_core.git_ops.run_git")
    def test_create_branch_exists_local(self, mock_rg):
        """When branch exists locally, checks it out directly."""
        mock_rg.return_value = MagicMock(stdout="abc123", returncode=0)
        checkout_branch(Path("/tmp"), "feature", create=True)
        calls = mock_rg.call_args_list
        assert calls[0][0][:2] == ("rev-parse", "--verify")
        assert calls[1][0] == ("checkout", "feature")

    @patch("pm_core.git_ops.run_git")
    def test_create_branch_exists_remote(self, mock_rg):
        """When branch exists on remote, fetches then checks out."""
        def side_effect(*args, **kwargs):
            if args[0] == "rev-parse":
                return MagicMock(returncode=1, stdout="")
            return MagicMock(stdout="abc123\trefs/heads/feature", returncode=0)
        mock_rg.side_effect = side_effect
        checkout_branch(Path("/tmp"), "feature", create=True)
        calls = mock_rg.call_args_list
        assert calls[1][0][0] == "ls-remote"
        assert calls[2][0] == ("fetch", "origin", "feature")
        assert calls[3][0] == ("checkout", "feature")


# ---------------------------------------------------------------------------
# pull_rebase
# ---------------------------------------------------------------------------

class TestPullRebase:
    @patch("pm_core.git_ops.run_git")
    def test_calls_pull_rebase(self, mock_rg):
        mock_rg.return_value = MagicMock(returncode=0)
        pull_rebase(Path("/tmp"))
        mock_rg.assert_called_once_with("pull", "--rebase", cwd=Path("/tmp"), check=False)


# ---------------------------------------------------------------------------
# commit_and_push
# ---------------------------------------------------------------------------

class TestCommitAndPush:
    @patch("pm_core.git_ops.run_git")
    def test_add_all_commit_push(self, mock_rg):
        """When no specific files, adds -A, commits, pushes."""
        mock_rg.return_value = MagicMock(returncode=1)  # diff --cached --quiet returns 1 = has changes
        commit_and_push(Path("/tmp"), "msg")
        calls = [c[0] for c in mock_rg.call_args_list]
        assert ("add", "-A") == calls[0][:2]
        assert calls[2][0] == "commit"
        assert calls[3][0] == "push"

    @patch("pm_core.git_ops.run_git")
    def test_specific_files(self, mock_rg):
        mock_rg.return_value = MagicMock(returncode=1)
        commit_and_push(Path("/tmp"), "msg", files=["a.py", "b.py"])
        calls = [c[0] for c in mock_rg.call_args_list]
        assert calls[0] == ("add", "a.py")
        assert calls[1] == ("add", "b.py")

    @patch("pm_core.git_ops.run_git")
    def test_no_changes_skips_commit(self, mock_rg):
        """diff --cached --quiet returning 0 means no staged changes."""
        mock_rg.return_value = MagicMock(returncode=0)
        commit_and_push(Path("/tmp"), "msg")
        call_first_args = [c[0][0] for c in mock_rg.call_args_list]
        assert "commit" not in call_first_args


# ---------------------------------------------------------------------------
# No-op functions
# ---------------------------------------------------------------------------

class TestNoOps:
    def test_sync_state(self, tmp_path):
        assert sync_state(tmp_path) == "no-op"

    def test_auto_commit_state(self, tmp_path):
        assert auto_commit_state(tmp_path) is None


# ---------------------------------------------------------------------------
# push_pm_branch
# ---------------------------------------------------------------------------

class TestPushPmBranch:
    @patch("pm_core.git_ops.is_git_repo", return_value=False)
    @patch("pm_core.store.is_internal_pm_dir", return_value=False)
    def test_not_git_repo(self, mock_ipd, mock_igr, tmp_path):
        result = push_pm_branch(tmp_path)
        assert "error" in result
        assert "Not a git repo" in result["error"]

    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    @patch("pm_core.store.is_internal_pm_dir", return_value=False)
    def test_no_changes(self, mock_ipd, mock_igr, mock_rg, tmp_path):
        """No changes to push returns error."""
        mock_rg.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),  # rev-parse HEAD
            MagicMock(returncode=0),  # git add .
            MagicMock(returncode=0),  # diff --cached --quiet (0 = no changes)
            MagicMock(returncode=0, stdout=""),  # status --porcelain
        ]
        result = push_pm_branch(tmp_path)
        assert "error" in result
        assert "No pm changes" in result["error"]

    @patch("pm_core.git_ops.pull_rebase")
    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    @patch("pm_core.store.is_internal_pm_dir", return_value=True)
    def test_internal_pm_dir_uses_parent(self, mock_ipd, mock_igr, mock_rg, mock_pr, tmp_path):
        """Internal PM dir uses parent as repo root."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        mock_rg.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),  # rev-parse HEAD
            MagicMock(returncode=0),  # git add pm/
            MagicMock(returncode=1),  # diff --cached --quiet (1 = has changes)
            MagicMock(returncode=0),  # checkout -b
            MagicMock(returncode=0),  # commit
            MagicMock(returncode=0),  # push
            MagicMock(returncode=0),  # checkout original
            MagicMock(returncode=0),  # checkout -- pm/
        ]
        result = push_pm_branch(pm_dir, backend="vanilla")
        assert "branch" in result
        # First add call should use "pm/"
        add_call = mock_rg.call_args_list[1]
        assert "pm/" in add_call[0]

    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    @patch("pm_core.store.is_internal_pm_dir", return_value=False)
    def test_local_backend_no_push(self, mock_ipd, mock_igr, mock_rg, tmp_path):
        """Local backend commits but doesn't push."""
        mock_rg.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),  # rev-parse HEAD
            MagicMock(returncode=0),  # git add .
            MagicMock(returncode=1),  # diff --cached (1 = has changes)
            MagicMock(returncode=0),  # checkout -b
            MagicMock(returncode=0),  # commit
            MagicMock(returncode=0),  # checkout original
            MagicMock(returncode=0),  # checkout -- .
        ]
        result = push_pm_branch(tmp_path, backend="local")
        assert "branch" in result
        # No push call — verify no "push" in any call args
        for call in mock_rg.call_args_list:
            assert call[0][0] != "push"

    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    @patch("pm_core.store.is_internal_pm_dir", return_value=False)
    def test_detect_branch_failure(self, mock_ipd, mock_igr, mock_rg, tmp_path):
        mock_rg.return_value = MagicMock(returncode=1, stdout="", stderr="not a branch")
        result = push_pm_branch(tmp_path)
        assert "error" in result
        assert "Failed to detect" in result["error"]


# ---------------------------------------------------------------------------
# _checkout_and_restore_pm
# ---------------------------------------------------------------------------

class TestCheckoutAndRestorePm:
    @patch("pm_core.git_ops.run_git")
    def test_restores_files(self, mock_rg):
        _checkout_and_restore_pm(Path("/tmp"), "main", "pm/sync-123", "pm/")
        calls = mock_rg.call_args_list
        assert calls[0][0] == ("checkout", "main")
        assert calls[1][0] == ("checkout", "pm/sync-123", "--", "pm/")
