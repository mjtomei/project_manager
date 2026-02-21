"""Tests for pm init across different repo types.

Covers three scenarios:
  1. Existing repo with a GitHub remote
  2. Notes-only (local) repo — no remote
  3. Empty (bare) repo — no commits, no remote

Each test is fully isolated in a tmp directory and verifies that init
creates the expected pm/ directory, project.yaml, and gitignore entries.
"""

import subprocess
import yaml
from pathlib import Path

import pytest
from click.testing import CliRunner

from pm_core.cli import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


def _git(*args, cwd):
    """Run a git command in the given directory."""
    subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    )


def _make_repo(tmp_path, *, name="repo", commit=True, remote=None):
    """Create a git repo under tmp_path/<name>.

    Args:
        commit:  If True, create an initial commit.
        remote:  If set, add an 'origin' remote with this URL.
    Returns the repo Path.
    """
    repo = tmp_path / name
    repo.mkdir()
    _git("init", cwd=repo)
    _git("config", "user.email", "test@test.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    if commit:
        (repo / "README.md").write_text("# Test\n")
        _git("add", ".", cwd=repo)
        _git("commit", "-m", "Initial commit", cwd=repo)
    if remote:
        _git("remote", "add", "origin", remote, cwd=repo)
    return repo


# ---------------------------------------------------------------------------
# 1. Existing repo with a GitHub remote
# ---------------------------------------------------------------------------

class TestInitExistingRepo:
    """pm init in a repo that has commits and a github.com origin."""

    def test_creates_pm_dir_and_project_yaml(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0, result.output
        pm_dir = repo / "pm"
        assert pm_dir.is_dir()
        assert (pm_dir / "project.yaml").exists()
        assert (pm_dir / "plans").is_dir()

    def test_project_yaml_contents(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["repo"] == "git@github.com:org/myapp.git"
        assert data["project"]["backend"] == "github"
        # base_branch is auto-detected from HEAD; may be "main" or "master"
        assert data["project"]["base_branch"] in ("main", "master")
        assert data["project"]["name"] == "myapp"
        assert data["plans"] == []
        assert data["prs"] == []

    def test_detects_current_branch(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        # Create and switch to a different branch
        _git("checkout", "-b", "develop", cwd=repo)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["base_branch"] == "develop"

    def test_backend_auto_detected_github(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert "backend: github" in result.output

    def test_backend_auto_detected_vanilla(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@gitlab.com:org/myapp.git")
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert "backend: vanilla" in result.output

    def test_gitignore_created(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        gitignore = (repo / "pm" / ".gitignore").read_text()
        assert "notes.txt" in gitignore
        assert ".pm-sessions.json" in gitignore

    def test_explicit_url_overrides_remote(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "git@myhost.com:team/other.git", "--no-import"])

        assert result.exit_code == 0
        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["repo"] == "git@myhost.com:team/other.git"
        assert data["project"]["backend"] == "vanilla"

    def test_backend_override(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import", "--backend", "vanilla"])

        assert result.exit_code == 0
        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["backend"] == "vanilla"

    def test_double_init_fails(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])
        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code != 0
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# 2. Notes-only (local) repo — no remote
# ---------------------------------------------------------------------------

class TestInitLocalRepo:
    """pm init in a repo that has commits but no remote."""

    def test_falls_back_to_local_path(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0
        assert "backend: local" in result.output

    def test_project_yaml_uses_local_path(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["repo"] == str(repo)
        assert data["project"]["backend"] == "local"

    def test_creates_pm_structure(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        pm_dir = repo / "pm"
        assert pm_dir.is_dir()
        assert (pm_dir / "project.yaml").exists()
        assert (pm_dir / "plans").is_dir()
        assert (pm_dir / ".gitignore").exists()

    def test_name_derived_from_dirname(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, name="my-notes-app")
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["name"] == "my-notes-app"

    def test_custom_name(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import", "--name", "My Cool Project"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["name"] == "My Cool Project"


# ---------------------------------------------------------------------------
# 3. Empty (bare) repo — no commits, no remote
# ---------------------------------------------------------------------------

class TestInitEmptyRepo:
    """pm init in a freshly git-init'd repo with no commits and no remote."""

    def test_init_succeeds(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, commit=False)
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert result.exit_code == 0, result.output

    def test_backend_local(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, commit=False)
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import"])

        assert "backend: local" in result.output

    def test_base_branch_defaults_to_master(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, commit=False)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        # Empty repo: rev-parse returns "HEAD" which is not a valid branch,
        # so init falls back to "master"
        assert data["project"]["base_branch"] == "master"

    def test_project_yaml_contents(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, commit=False)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        data = yaml.safe_load((repo / "pm" / "project.yaml").read_text())
        assert data["project"]["repo"] == str(repo)
        assert data["project"]["backend"] == "local"
        assert data["plans"] == []
        assert data["prs"] == []

    def test_pm_structure_created(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, commit=False)
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import"])

        pm_dir = repo / "pm"
        assert pm_dir.is_dir()
        assert (pm_dir / "project.yaml").exists()
        assert (pm_dir / "plans").is_dir()


# ---------------------------------------------------------------------------
# 4. External PM directory (--dir)
# ---------------------------------------------------------------------------

class TestInitExternalDir:
    """pm init with --dir pointing outside the repo."""

    def test_standalone_pm_repo(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        pm_dir = tmp_path / "pm-state"
        monkeypatch.chdir(repo)

        result = runner.invoke(cli, ["init", "--no-import", "--dir", str(pm_dir)])

        assert result.exit_code == 0, result.output
        assert pm_dir.is_dir()
        assert (pm_dir / "project.yaml").exists()
        # External dirs get their own git repo
        assert (pm_dir / ".git").exists()

    def test_standalone_has_initial_commit(self, tmp_path, runner, monkeypatch):
        repo = _make_repo(tmp_path, remote="git@github.com:org/myapp.git")
        pm_dir = tmp_path / "pm-state"
        monkeypatch.chdir(repo)

        runner.invoke(cli, ["init", "--no-import", "--dir", str(pm_dir)])

        # Should have at least one commit
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=pm_dir,
            capture_output=True, text=True,
        )
        assert log.returncode == 0
        assert "pm: init project" in log.stdout
