"""Tests for deduplicated functions: _extract_field, get_git_root, get_github_repo_name."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.plan_parser import _extract_field
from pm_core.git_ops import get_git_root, get_github_repo_name


# ---------------------------------------------------------------------------
# _extract_field tests
# ---------------------------------------------------------------------------

class TestExtractField:
    """Tests for _extract_field imported from plan_parser."""

    def test_extracts_description(self):
        body = "- **description**: Implement JWT auth\n- **tests**: Unit tests"
        assert _extract_field(body, "description") == "Implement JWT auth"

    def test_extracts_tests(self):
        body = "- **description**: Something\n- **tests**: Run pytest tests/"
        assert _extract_field(body, "tests") == "Run pytest tests/"

    def test_extracts_files(self):
        body = "- **files**: src/auth.py, tests/test_auth.py"
        assert _extract_field(body, "files") == "src/auth.py, tests/test_auth.py"

    def test_missing_field_returns_empty(self):
        body = "- **description**: Something"
        assert _extract_field(body, "tests") == ""

    def test_empty_body_returns_empty(self):
        assert _extract_field("", "description") == ""

    def test_case_insensitive(self):
        body = "- **Description**: Some value"
        assert _extract_field(body, "description") == "Some value"

    def test_strips_whitespace(self):
        body = "- **tests**:   extra spaces   "
        assert _extract_field(body, "tests") == "extra spaces"

    def test_field_with_leading_whitespace(self):
        body = "  - **description**: indented item"
        assert _extract_field(body, "description") == "indented item"


# ---------------------------------------------------------------------------
# get_git_root tests
# ---------------------------------------------------------------------------

class TestGetGitRoot:
    """Tests for get_git_root from git_ops."""

    def test_finds_git_root(self, tmp_path):
        """Finds .git directory in the given path."""
        (tmp_path / ".git").mkdir()
        assert get_git_root(tmp_path) == tmp_path.resolve()

    def test_traverses_parent_dirs(self, tmp_path):
        """Walks up to find .git in a parent directory."""
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src" / "pkg"
        subdir.mkdir(parents=True)
        assert get_git_root(subdir) == tmp_path.resolve()

    def test_returns_none_when_missing(self, tmp_path):
        """Returns None when no .git directory exists."""
        subdir = tmp_path / "not-a-repo"
        subdir.mkdir()
        assert get_git_root(subdir) is None

    def test_defaults_to_cwd(self):
        """Uses cwd when no start_path is given."""
        result = get_git_root()
        # We're in a git repo (the project itself), so this should find it
        assert result is not None
        assert (result / ".git").exists()


# ---------------------------------------------------------------------------
# get_github_repo_name tests
# ---------------------------------------------------------------------------

class TestGetGithubRepoName:
    """Tests for get_github_repo_name from git_ops."""

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a minimal git repo for testing."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo, check=True, capture_output=True,
        )
        return repo

    def test_https_url(self, git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/my-project.git"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert get_github_repo_name(git_repo) == "my-project"

    def test_ssh_url(self, git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:user/my-project.git"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert get_github_repo_name(git_repo) == "my-project"

    def test_https_without_dot_git(self, git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/my-project"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert get_github_repo_name(git_repo) == "my-project"

    def test_non_github_returns_none(self, git_repo):
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.com/user/project.git"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert get_github_repo_name(git_repo) is None

    def test_no_remote_returns_none(self, git_repo):
        assert get_github_repo_name(git_repo) is None

    def test_not_a_git_dir_returns_none(self, tmp_path):
        assert get_github_repo_name(tmp_path) is None


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

class TestImportSmoke:
    """Verify that modules successfully import the shared versions."""

    def test_detail_panel_imports_extract_field(self):
        """detail_panel.py imports _extract_field from plan_parser."""
        from pm_core.tui import detail_panel
        # _extract_field should be used in the module (imported, not defined locally)
        assert hasattr(detail_panel, '_extract_field')
        # Confirm it's the same function from plan_parser
        assert detail_panel._extract_field is _extract_field

    def test_paths_uses_git_ops_functions(self):
        """paths.py uses get_git_root and get_github_repo_name from git_ops."""
        # Verify the old private names are no longer defined in paths
        import pm_core.paths as paths_mod
        assert not hasattr(paths_mod, '_find_git_root')
        assert not hasattr(paths_mod, '_get_github_repo_name')

    def test_wrapper_uses_git_ops_functions(self):
        """wrapper.py uses get_git_root and get_github_repo_name from git_ops."""
        import pm_core.wrapper as wrapper_mod
        assert not hasattr(wrapper_mod, '_find_git_root')
        assert not hasattr(wrapper_mod, '_get_github_repo_name')

    def test_git_ops_exports_functions(self):
        """git_ops.py exports get_git_root and get_github_repo_name."""
        import pm_core.git_ops as git_ops_mod
        assert hasattr(git_ops_mod, 'get_git_root')
        assert hasattr(git_ops_mod, 'get_github_repo_name')
        assert callable(git_ops_mod.get_git_root)
        assert callable(git_ops_mod.get_github_repo_name)
