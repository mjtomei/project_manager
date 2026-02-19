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
    select_remote,
    list_remotes,
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


# ---------------------------------------------------------------------------
# select_remote
# ---------------------------------------------------------------------------

class TestSelectRemote:
    def test_no_remotes(self):
        result = select_remote({})
        assert result == {"selected": None}

    def test_single_remote(self):
        result = select_remote({"origin": "git@github.com:org/repo.git"})
        assert result["selected"] == ("origin", "git@github.com:org/repo.git")

    def test_origin_preferred_no_backend(self):
        remotes = {
            "origin": "git@github.com:org/repo.git",
            "upstream": "git@github.com:other/repo.git",
        }
        result = select_remote(remotes)
        assert result["selected"][0] == "origin"

    def test_origin_preferred_with_matching_github_backend(self):
        remotes = {
            "origin": "https://github.com/org/repo.git",
            "upstream": "https://github.com/other/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert result["selected"][0] == "origin"

    def test_origin_skipped_when_backend_mismatch(self):
        remotes = {
            "origin": "/local/path/repo",
            "github": "https://github.com/org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert result["selected"] == ("github", "https://github.com/org/repo.git")

    def test_local_backend_matches_anything(self):
        """Line 319: 'local' or None matches anything."""
        remotes = {
            "origin": "https://github.com/org/repo.git",
            "other": "/local/path",
        }
        result = select_remote(remotes, preferred_backend="local")
        assert result["selected"][0] == "origin"

    def test_ambiguous_multiple_github(self):
        remotes = {
            "fork1": "https://github.com/user1/repo.git",
            "fork2": "https://github.com/user2/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert "ambiguous" in result
        assert len(result["ambiguous"]) == 2

    def test_ambiguous_no_origin_no_backend(self):
        remotes = {
            "upstream": "git@github.com:org/repo.git",
            "fork": "git@github.com:user/repo.git",
        }
        # No origin → ambiguous without preferred_backend
        # Actually origin isn't there, but preferred_backend is None
        # so matches_backend matches anything → origin check fails → preferred_backend is None → skip → ambiguous
        result = select_remote(remotes)
        assert "ambiguous" in result

    def test_vanilla_backend_matches_remote_urls(self):
        remotes = {
            "local": "/home/user/repos/proj",
            "remote": "https://gitlab.com/org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="vanilla")
        assert result["selected"] == ("remote", "https://gitlab.com/org/repo.git")

    def test_vanilla_backend_matches_ssh(self):
        remotes = {
            "local": "/home/user/repos/proj",
            "remote": "git@gitlab.com:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="vanilla")
        assert result["selected"] == ("remote", "git@gitlab.com:org/repo.git")


# ---------------------------------------------------------------------------
# list_remotes
# ---------------------------------------------------------------------------

class TestListRemotes:
    @patch("pm_core.git_ops.is_git_repo", return_value=False)
    def test_not_git_repo(self, mock_igr):
        assert list_remotes(Path("/tmp")) == {}

    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    def test_parses_fetch_remotes(self, mock_igr, mock_rg):
        mock_rg.return_value = MagicMock(
            returncode=0,
            stdout="origin\tgit@github.com:org/repo.git (fetch)\norigin\tgit@github.com:org/repo.git (push)\n"
        )
        result = list_remotes(Path("/tmp"))
        assert result == {"origin": "git@github.com:org/repo.git"}

    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    def test_no_remotes(self, mock_igr, mock_rg):
        mock_rg.return_value = MagicMock(returncode=0, stdout="")
        assert list_remotes(Path("/tmp")) == {}

    @patch("pm_core.git_ops.run_git")
    @patch("pm_core.git_ops.is_git_repo", return_value=True)
    def test_error(self, mock_igr, mock_rg):
        mock_rg.return_value = MagicMock(returncode=1, stdout="")
        assert list_remotes(Path("/tmp")) == {}


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
