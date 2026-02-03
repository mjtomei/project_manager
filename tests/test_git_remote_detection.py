"""Tests for git remote detection functions in git_ops.py."""

import subprocess
from pathlib import Path

import pytest

from pm_core.git_ops import list_remotes, select_remote, run_git


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True
    )
    # Create an initial commit so the repo is fully initialized
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, check=True, capture_output=True
    )
    return repo


class TestListRemotes:
    """Tests for list_remotes() function."""

    def test_no_remotes(self, git_repo):
        """A git repo with no remotes returns empty dict."""
        result = list_remotes(git_repo)
        assert result == {}

    def test_single_remote(self, git_repo):
        """A git repo with one remote returns that remote."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        result = list_remotes(git_repo)
        assert result == {"origin": "git@github.com:org/repo.git"}

    def test_multiple_remotes(self, git_repo):
        """A git repo with multiple remotes returns all of them."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "upstream", "git@github.com:upstream/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "gitlab", "git@gitlab.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        result = list_remotes(git_repo)
        assert result == {
            "origin": "git@github.com:org/repo.git",
            "upstream": "git@github.com:upstream/repo.git",
            "gitlab": "git@gitlab.com:org/repo.git",
        }

    def test_not_a_git_repo(self, tmp_path):
        """A non-git directory returns empty dict."""
        result = list_remotes(tmp_path)
        assert result == {}

    def test_https_url(self, git_repo):
        """HTTPS URLs are correctly parsed."""
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        result = list_remotes(git_repo)
        assert result == {"origin": "https://github.com/org/repo.git"}


class TestSelectRemote:
    """Tests for select_remote() function."""

    def test_no_remotes(self):
        """No remotes returns selected=None."""
        result = select_remote({})
        assert result == {"selected": None}

    def test_single_remote(self):
        """Single remote is always selected."""
        result = select_remote({"origin": "git@github.com:org/repo.git"})
        assert result == {"selected": ("origin", "git@github.com:org/repo.git")}

    def test_single_remote_not_origin(self):
        """Single remote is selected even if not named 'origin'."""
        result = select_remote({"github": "git@github.com:org/repo.git"})
        assert result == {"selected": ("github", "git@github.com:org/repo.git")}

    def test_origin_preferred_no_backend(self):
        """Origin is preferred when no backend preference specified."""
        remotes = {
            "origin": "git@github.com:org/repo.git",
            "upstream": "git@github.com:upstream/repo.git",
        }
        result = select_remote(remotes)
        assert result == {"selected": ("origin", "git@github.com:org/repo.git")}

    def test_origin_preferred_matching_backend(self):
        """Origin is preferred when it matches the preferred backend."""
        remotes = {
            "origin": "git@github.com:org/repo.git",
            "gitlab": "git@gitlab.com:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert result == {"selected": ("origin", "git@github.com:org/repo.git")}

    def test_backend_preference_overrides_origin(self):
        """Backend preference can override origin if origin doesn't match."""
        remotes = {
            "origin": "git@gitlab.com:org/repo.git",  # Not github
            "github": "git@github.com:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert result == {"selected": ("github", "git@github.com:org/repo.git")}

    def test_multiple_matching_backend_is_ambiguous(self):
        """Multiple remotes matching preferred backend returns ambiguous."""
        remotes = {
            "fork": "git@github.com:fork/repo.git",
            "upstream": "git@github.com:upstream/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert "ambiguous" in result
        assert len(result["ambiguous"]) == 2

    def test_fallback_to_origin_when_no_backend_match(self):
        """Falls back to origin when preferred backend doesn't match any remote."""
        remotes = {
            "origin": "git@gitlab.com:org/repo.git",
            "bitbucket": "git@bitbucket.org:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        # No github remote, but origin exists - fall back to origin
        assert result == {"selected": ("origin", "git@gitlab.com:org/repo.git")}

    def test_ambiguous_when_no_origin_no_backend_match(self):
        """Returns ambiguous when no origin and no backend match."""
        remotes = {
            "gitlab": "git@gitlab.com:org/repo.git",
            "bitbucket": "git@bitbucket.org:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        # No github remote and no origin - returns ambiguous with all remotes
        assert "ambiguous" in result
        assert len(result["ambiguous"]) == 2

    def test_vanilla_backend_matches_any_remote(self):
        """Vanilla backend matches any remote URL (SSH or HTTPS)."""
        remotes = {
            "gitlab": "git@gitlab.com:org/repo.git",
            "bitbucket": "https://bitbucket.org/org/repo.git",
        }
        # Vanilla matches both remotes, so the result is ambiguous
        result = select_remote(remotes, preferred_backend="vanilla")
        assert "ambiguous" in result
        assert len(result["ambiguous"]) == 2

    def test_github_backend_case_insensitive(self):
        """GitHub detection is case-insensitive."""
        remotes = {
            "origin": "git@GITHUB.COM:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert result == {"selected": ("origin", "git@GITHUB.COM:org/repo.git")}

    def test_https_github_url(self):
        """HTTPS GitHub URLs are detected as github backend."""
        remotes = {
            "origin": "https://github.com/org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert result == {"selected": ("origin", "https://github.com/org/repo.git")}


class TestSelectRemoteEdgeCases:
    """Edge case tests for select_remote()."""

    def test_empty_url(self):
        """Handles empty URL gracefully."""
        remotes = {"origin": ""}
        result = select_remote(remotes)
        assert result == {"selected": ("origin", "")}

    def test_local_path_remote(self):
        """Local path remotes are handled."""
        remotes = {"local": "/path/to/repo"}
        result = select_remote(remotes)
        assert result == {"selected": ("local", "/path/to/repo")}

    def test_many_remotes_with_origin(self):
        """With many remotes, origin is still preferred."""
        remotes = {
            "fork1": "git@github.com:fork1/repo.git",
            "fork2": "git@github.com:fork2/repo.git",
            "origin": "git@github.com:org/repo.git",
            "upstream": "git@github.com:upstream/repo.git",
        }
        result = select_remote(remotes)
        assert result == {"selected": ("origin", "git@github.com:org/repo.git")}

    def test_ambiguous_returns_all_matching(self):
        """Ambiguous result includes all matching remotes."""
        remotes = {
            "github1": "git@github.com:org1/repo.git",
            "github2": "git@github.com:org2/repo.git",
            "gitlab": "git@gitlab.com:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="github")
        assert "ambiguous" in result
        # Should only include the github remotes, not gitlab
        urls = [url for _, url in result["ambiguous"]]
        assert "git@gitlab.com:org/repo.git" not in urls
        assert len(result["ambiguous"]) == 2

    def test_file_url_not_matched_as_vanilla(self):
        """file:// URLs should not be matched as vanilla backend."""
        remotes = {
            "local": "file:///path/to/repo",
            "remote": "git@github.com:org/repo.git",
        }
        result = select_remote(remotes, preferred_backend="vanilla")
        # Only the git@ remote matches vanilla, so it should be selected
        assert result == {"selected": ("remote", "git@github.com:org/repo.git")}
