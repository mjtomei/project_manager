"""Tests for pm_core.git_ops — git operations (run_git, get_git_root, etc.)."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from pm_core.git_ops import (
    run_git,
    get_git_root,
    get_github_repo_name,
    is_git_repo,
    clone,
    checkout_branch,
    pull_rebase,
    commit_and_push,
    sync_state,
    auto_commit_state,
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
# get_git_root
# ---------------------------------------------------------------------------

class TestGetGitRoot:
    def test_finds_root_in_current_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert get_git_root(tmp_path) == tmp_path

    def test_finds_root_in_parent(self, tmp_path):
        (tmp_path / ".git").mkdir()
        child = tmp_path / "sub" / "deep"
        child.mkdir(parents=True)
        assert get_git_root(child) == tmp_path

    def test_returns_none_when_no_git(self, tmp_path):
        child = tmp_path / "sub"
        child.mkdir()
        assert get_git_root(child) is None


# ---------------------------------------------------------------------------
# get_github_repo_name
# ---------------------------------------------------------------------------

class TestGetGithubRepoName:
    @patch("pm_core.git_ops.subprocess.run")
    def test_https_url(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/user/myrepo.git\n"
        )
        assert get_github_repo_name(Path("/tmp")) == "myrepo"

    @patch("pm_core.git_ops.subprocess.run")
    def test_ssh_url(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="git@github.com:user/myrepo.git\n"
        )
        assert get_github_repo_name(Path("/tmp")) == "myrepo"

    @patch("pm_core.git_ops.subprocess.run")
    def test_non_github_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://gitlab.com/user/repo.git\n"
        )
        assert get_github_repo_name(Path("/tmp")) is None

    @patch("pm_core.git_ops.subprocess.run")
    def test_no_remote_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        assert get_github_repo_name(Path("/tmp")) is None

    @patch("pm_core.git_ops.subprocess.run")
    def test_url_without_git_suffix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/user/myrepo\n"
        )
        assert get_github_repo_name(Path("/tmp")) == "myrepo"

    @patch("pm_core.git_ops.subprocess.run")
    def test_subprocess_error(self, mock_run):
        mock_run.side_effect = subprocess.SubprocessError("fail")
        assert get_github_repo_name(Path("/tmp")) is None


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
        clone("https://github.com/org/repo.git", Path("/tmp/dest"))
        mock_rg.assert_called_once_with("clone", "https://github.com/org/repo.git", "/tmp/dest")

    @patch("pm_core.git_ops.run_git")
    def test_clone_with_branch(self, mock_rg):
        clone("url", Path("/tmp/dest"), branch="main")
        args = mock_rg.call_args[0]
        assert "--branch" in args
        assert "main" in args


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
        """When branch doesn't exist on remote, creates with -b."""
        mock_rg.return_value = MagicMock(stdout="")
        checkout_branch(Path("/tmp"), "feature", create=True)
        # First call: ls-remote; second: checkout -b
        calls = mock_rg.call_args_list
        assert calls[0][0][0] == "ls-remote"
        assert calls[1][0] == ("checkout", "-b", "feature")

    @patch("pm_core.git_ops.run_git")
    def test_create_branch_exists_remote(self, mock_rg):
        """When branch exists on remote, fetches then checks out."""
        mock_rg.return_value = MagicMock(stdout="abc123\trefs/heads/feature")
        checkout_branch(Path("/tmp"), "feature", create=True)
        calls = mock_rg.call_args_list
        assert calls[1][0] == ("fetch", "origin", "feature")
        assert calls[2][0] == ("checkout", "feature")


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
