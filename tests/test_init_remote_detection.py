"""Integration tests for pm init with various git remote configurations."""

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from pm_core.cli import cli


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository for testing."""
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
    # Create an initial commit
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, check=True, capture_output=True
    )
    return repo


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return CliRunner()


class TestInitWithSingleRemote:
    """Tests for pm init with a single git remote."""

    def test_single_origin_remote(self, git_repo, runner, monkeypatch):
        """When only 'origin' exists, it should be auto-selected."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0
        assert "git@github.com:org/repo.git" in result.output
        assert "backend: github" in result.output

    def test_single_non_origin_remote(self, git_repo, runner, monkeypatch):
        """When only one remote exists (not named 'origin'), it should be used."""
        subprocess.run(
            ["git", "remote", "add", "github", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0
        assert "git@github.com:org/repo.git" in result.output
        assert "backend: github" in result.output


class TestInitWithMultipleRemotes:
    """Tests for pm init with multiple git remotes."""

    def test_origin_preferred_over_others(self, git_repo, runner, monkeypatch):
        """Origin should be preferred when multiple remotes exist."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "upstream", "git@github.com:upstream/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0
        assert "git@github.com:org/repo.git" in result.output

    def test_backend_override_influences_selection(self, git_repo, runner, monkeypatch):
        """Backend override should influence remote selection."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@gitlab.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "github", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        # With --backend github, the github remote should be selected
        result = runner.invoke(cli, ["init", "--no-import", "--backend", "github"])

        assert result.exit_code == 0
        assert "git@github.com:org/repo.git" in result.output
        assert "backend: github" in result.output

    def test_origin_used_when_backend_matches(self, git_repo, runner, monkeypatch):
        """Origin should be used when it matches the preferred backend."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "gitlab", "git@gitlab.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["init", "--no-import", "--backend", "github"])

        assert result.exit_code == 0
        # Origin matches github backend, so it should be selected
        assert "git@github.com:org/repo.git" in result.output


class TestInitWithAmbiguousRemotes:
    """Tests for pm init when remote selection is ambiguous."""

    def test_prompts_user_when_ambiguous(self, git_repo, runner, monkeypatch):
        """When multiple remotes match, user should be prompted."""
        subprocess.run(
            ["git", "remote", "add", "fork", "git@github.com:fork/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "upstream", "git@github.com:upstream/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        # Simulate user selecting option 1
        result = runner.invoke(cli, ["init", "--no-import", "--backend", "github"], input="1\n")

        assert result.exit_code == 0
        assert "Multiple git remotes found" in result.output
        # One of the remotes should be in the final output
        assert "git@github.com:" in result.output

    def test_user_can_choose_second_option(self, git_repo, runner, monkeypatch):
        """User should be able to choose any option."""
        subprocess.run(
            ["git", "remote", "add", "fork", "git@github.com:fork/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "upstream", "git@github.com:upstream/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        # Simulate user selecting option 2
        result = runner.invoke(cli, ["init", "--no-import", "--backend", "github"], input="2\n")

        assert result.exit_code == 0
        assert "Multiple git remotes found" in result.output


class TestInitWithNoRemotes:
    """Tests for pm init with no git remotes."""

    def test_falls_back_to_local_path(self, git_repo, runner, monkeypatch):
        """When no remotes exist, should use local path."""
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0
        # Should use cwd as repo URL
        assert str(git_repo) in result.output
        assert "backend: local" in result.output


class TestInitWithExplicitUrl:
    """Tests for pm init when URL is explicitly provided."""

    def test_explicit_url_overrides_detection(self, git_repo, runner, monkeypatch):
        """Explicitly provided URL should override any remote detection."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["init", "git@gitlab.com:other/repo.git", "--no-import"])

        assert result.exit_code == 0
        assert "git@gitlab.com:other/repo.git" in result.output
        assert "backend: vanilla" in result.output


class TestDetectGitRepo:
    """Tests for the _detect_git_repo function used in pm help."""

    def test_detect_repo_with_single_remote(self, git_repo, runner, monkeypatch):
        """_detect_git_repo should work with single remote."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        # pm help uses _detect_git_repo internally
        result = runner.invoke(cli, ["help"])

        assert result.exit_code == 0
        assert "github.com:org/repo.git" in result.output

    def test_detect_repo_with_no_remotes(self, git_repo, runner, monkeypatch):
        """_detect_git_repo should work with no remotes."""
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["help"])

        assert result.exit_code == 0
        # Should detect as local repo
        assert "local" in result.output.lower()

    def test_detect_repo_prefers_github_remote(self, git_repo, runner, monkeypatch):
        """_detect_git_repo should prefer github.com remotes."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@gitlab.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "github", "git@github.com:org/repo.git"],
            cwd=git_repo, check=True, capture_output=True
        )
        monkeypatch.chdir(git_repo)

        result = runner.invoke(cli, ["help"])

        assert result.exit_code == 0
        # Should prefer the github remote
        assert "github.com" in result.output
