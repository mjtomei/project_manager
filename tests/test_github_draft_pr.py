"""Tests for GitHub draft PR workflow in pr_start and pr_done."""

import json
from pathlib import Path
from unittest import mock
import tempfile

import pytest
from click.testing import CliRunner

from pm_core import cli, store, git_ops


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with project.yaml."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()

    # Create a minimal project.yaml with GitHub backend
    data = {
        "project": {
            "name": "test-project",
            "repo": "https://github.com/owner/repo.git",
            "base_branch": "main",
            "backend": "github",
        },
        "prs": [],
        "plans": [{"id": "plan-001", "name": "Test Plan"}],
    }
    store.save(data, pm_dir)

    # Create a mock workdir that looks like a git repo
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / ".git").mkdir()

    return {
        "pm_dir": pm_dir,
        "workdir": workdir,
        "data": data,
    }


@pytest.fixture
def tmp_project_with_pr(tmp_path):
    """Create a temporary project with an existing PR."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()

    data = {
        "project": {
            "name": "test-project",
            "repo": "https://github.com/owner/repo.git",
            "base_branch": "main",
            "backend": "github",
        },
        "prs": [
            {
                "id": "pr-001",
                "title": "Test PR",
                "description": "Test description",
                "branch": "pm/pr-001",
                "status": "pending",
                "gh_pr": "https://github.com/owner/repo/pull/42",
                "gh_pr_number": 42,
            }
        ],
        "plans": [],
    }
    store.save(data, pm_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / ".git").mkdir()

    return {
        "pm_dir": pm_dir,
        "workdir": workdir,
        "data": data,
    }


@pytest.fixture
def tmp_project_with_pending_pr(tmp_path):
    """Create a temporary project with a pending PR (no gh_pr yet)."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()

    data = {
        "project": {
            "name": "test-project",
            "repo": "https://github.com/owner/repo.git",
            "base_branch": "main",
            "backend": "github",
        },
        "prs": [
            {
                "id": "pr-001",
                "title": "Test PR",
                "description": "Test description",
                "branch": "pm/pr-001-test-pr",
                "status": "pending",
                "depends_on": [],
                "agent_machine": None,
                "gh_pr": None,
                "gh_pr_number": None,
            }
        ],
        "plans": [],
    }
    store.save(data, pm_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / ".git").mkdir()

    return {
        "pm_dir": pm_dir,
        "workdir": workdir,
        "data": data,
    }


@pytest.fixture
def mock_gh_ops():
    """Mock GitHub CLI operations."""
    with mock.patch("pm_core.gh_ops._check_gh"):
        with mock.patch("pm_core.gh_ops.create_draft_pr") as mock_create:
            with mock.patch("pm_core.gh_ops.mark_pr_ready") as mock_ready:
                mock_create.return_value = {
                    "url": "https://github.com/owner/repo/pull/42",
                    "number": 42,
                }
                mock_ready.return_value = True
                yield {
                    "create_draft_pr": mock_create,
                    "mark_pr_ready": mock_ready,
                }


class TestPrAddNoDraftPr:
    """Tests that pr_add no longer creates draft PRs."""

    def test_no_draft_pr_for_github_backend(self, tmp_project, mock_gh_ops):
        """pr_add should NOT create a draft PR (moved to pr_start)."""
        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            result = runner.invoke(cli.pr, ["add", "Test PR", "--description", "Test description"])

        assert result.exit_code == 0

        # Should NOT have attempted to create draft PR
        mock_gh_ops["create_draft_pr"].assert_not_called()

        # PR should be created with gh_pr=None
        data = store.load(tmp_project["pm_dir"])
        prs = data.get("prs") or []
        assert len(prs) == 1
        pr = prs[0]
        assert pr["gh_pr"] is None
        assert pr["gh_pr_number"] is None

    def test_no_draft_flag_removed(self, tmp_project):
        """pr_add should not accept --no-draft flag."""
        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            result = runner.invoke(cli.pr, ["add", "Test PR", "--no-draft"])

        # Should fail because --no-draft is no longer a valid option
        assert result.exit_code != 0
        assert "No such option" in result.output or "no such option" in result.output.lower()


class TestPrStartCreatesDraftPr:
    """Tests for draft PR creation during pr_start."""

    def test_creates_draft_pr_on_start(self, tmp_project_with_pending_pr, mock_gh_ops):
        """pr_start should create a draft PR for GitHub backend."""
        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pending_pr["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                with mock.patch.object(cli, "_workdirs_dir", return_value=tmp_project_with_pending_pr["workdir"].parent):
                    with mock.patch.object(cli.tmux_mod, "has_tmux", return_value=False):
                        with mock.patch.multiple(
                            git_ops,
                            clone=mock.DEFAULT,
                            checkout_branch=mock.DEFAULT,
                            pull_rebase=mock.DEFAULT,
                            is_git_repo=mock.Mock(return_value=True),
                            run_git=mock.Mock(return_value=mock.Mock(returncode=0, stdout="abc12345\n", stderr="")),
                        ):
                            with mock.patch("shutil.rmtree"):
                                with mock.patch("shutil.move"):
                                    result = runner.invoke(cli.pr, [
                                        "start", "pr-001",
                                        "--workdir", str(tmp_project_with_pending_pr["workdir"]),
                                    ])

        assert result.exit_code == 0

        # Should have attempted to create draft PR
        mock_gh_ops["create_draft_pr"].assert_called_once()
        call_args = mock_gh_ops["create_draft_pr"].call_args
        assert call_args[0][1] == "Test PR"  # title
        assert call_args[0][2] == "main"  # base branch

        # Check that gh_pr was stored in project.yaml
        data = store.load(tmp_project_with_pending_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["gh_pr"] == "https://github.com/owner/repo/pull/42"
        assert pr["gh_pr_number"] == 42

    def test_skips_draft_pr_if_already_set(self, tmp_project_with_pr, mock_gh_ops):
        """pr_start should not create draft PR if gh_pr_number already exists."""
        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pr["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                with mock.patch.object(cli, "_workdirs_dir", return_value=tmp_project_with_pr["workdir"].parent):
                    with mock.patch.object(cli.tmux_mod, "has_tmux", return_value=False):
                        with mock.patch.multiple(
                            git_ops,
                            clone=mock.DEFAULT,
                            checkout_branch=mock.DEFAULT,
                            pull_rebase=mock.DEFAULT,
                            is_git_repo=mock.Mock(return_value=True),
                            run_git=mock.Mock(return_value=mock.Mock(returncode=0, stdout="abc12345\n", stderr="")),
                        ):
                            with mock.patch("shutil.rmtree"):
                                with mock.patch("shutil.move"):
                                    result = runner.invoke(cli.pr, [
                                        "start", "pr-001",
                                        "--workdir", str(tmp_project_with_pr["workdir"]),
                                    ])

        # Should NOT have created a new draft PR
        mock_gh_ops["create_draft_pr"].assert_not_called()

    def test_handles_push_failure_gracefully(self, tmp_project_with_pending_pr, mock_gh_ops):
        """pr_start should continue if push fails."""
        runner = CliRunner()

        call_count = [0]

        def selective_run_git(*args, **kwargs):
            call_count[0] += 1
            if args[0] == "push":
                return mock.Mock(returncode=1, stdout="", stderr="push failed")
            return mock.Mock(returncode=0, stdout="abc12345\n", stderr="")

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pending_pr["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                with mock.patch.object(cli, "_workdirs_dir", return_value=tmp_project_with_pending_pr["workdir"].parent):
                    with mock.patch.object(cli.tmux_mod, "has_tmux", return_value=False):
                        with mock.patch.multiple(
                            git_ops,
                            clone=mock.DEFAULT,
                            checkout_branch=mock.DEFAULT,
                            pull_rebase=mock.DEFAULT,
                            is_git_repo=mock.Mock(return_value=True),
                            run_git=selective_run_git,
                        ):
                            with mock.patch("shutil.rmtree"):
                                with mock.patch("shutil.move"):
                                    result = runner.invoke(cli.pr, [
                                        "start", "pr-001",
                                        "--workdir", str(tmp_project_with_pending_pr["workdir"]),
                                    ])

        assert result.exit_code == 0
        assert "Warning" in result.output

        # Should NOT have attempted to create draft PR since push failed
        mock_gh_ops["create_draft_pr"].assert_not_called()

        # PR should still be in_progress
        data = store.load(tmp_project_with_pending_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr is not None
        assert pr["gh_pr"] is None
        assert pr["status"] == "in_progress"

    def test_no_draft_pr_for_vanilla_backend(self, tmp_project_with_pending_pr, mock_gh_ops):
        """pr_start should not create draft PR for vanilla backend."""
        # Change backend to vanilla
        data = store.load(tmp_project_with_pending_pr["pm_dir"])
        data["project"]["backend"] = "vanilla"
        store.save(data, tmp_project_with_pending_pr["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pending_pr["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                with mock.patch.object(cli, "_workdirs_dir", return_value=tmp_project_with_pending_pr["workdir"].parent):
                    with mock.patch.object(cli.tmux_mod, "has_tmux", return_value=False):
                        with mock.patch.multiple(
                            git_ops,
                            clone=mock.DEFAULT,
                            checkout_branch=mock.DEFAULT,
                            pull_rebase=mock.DEFAULT,
                            is_git_repo=mock.Mock(return_value=True),
                            run_git=mock.Mock(return_value=mock.Mock(returncode=0, stdout="abc12345\n", stderr="")),
                        ):
                            with mock.patch("shutil.rmtree"):
                                with mock.patch("shutil.move"):
                                    result = runner.invoke(cli.pr, [
                                        "start", "pr-001",
                                        "--workdir", str(tmp_project_with_pending_pr["workdir"]),
                                    ])

        assert result.exit_code == 0

        # Should NOT have attempted to create draft PR
        mock_gh_ops["create_draft_pr"].assert_not_called()


class TestPrDoneUpgradesDraftPr:
    """Tests for draft PR upgrade during pr_done."""

    def test_upgrades_draft_to_ready_for_github_backend(self, tmp_project_with_pr, mock_gh_ops):
        """pr_done should upgrade draft PR to ready for review."""
        # Set up PR as in_progress
        data = store.load(tmp_project_with_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["workdir"] = str(tmp_project_with_pr["workdir"])
        store.save(data, tmp_project_with_pr["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pr["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0

        # Should have called mark_pr_ready
        mock_gh_ops["mark_pr_ready"].assert_called_once_with(
            str(tmp_project_with_pr["workdir"]), 42
        )

        # Status should be in_review
        data = store.load(tmp_project_with_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_skips_upgrade_if_no_gh_pr(self, tmp_project_with_pr, mock_gh_ops):
        """pr_done should skip upgrade if no gh_pr is set."""
        # Remove gh_pr
        data = store.load(tmp_project_with_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["gh_pr"] = None
        pr["gh_pr_number"] = None
        pr["workdir"] = str(tmp_project_with_pr["workdir"])
        store.save(data, tmp_project_with_pr["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pr["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0

        # Should NOT have called mark_pr_ready
        mock_gh_ops["mark_pr_ready"].assert_not_called()

    def test_handles_upgrade_failure_gracefully(self, tmp_project_with_pr, mock_gh_ops):
        """pr_done should continue if upgrade fails."""
        mock_gh_ops["mark_pr_ready"].return_value = False

        data = store.load(tmp_project_with_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["workdir"] = str(tmp_project_with_pr["workdir"])
        store.save(data, tmp_project_with_pr["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pr["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0
        assert "Warning" in result.output

        # Status should still be in_review
        data = store.load(tmp_project_with_pr["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_no_upgrade_for_vanilla_backend(self, tmp_project_with_pr, mock_gh_ops):
        """pr_done should not upgrade for vanilla backend."""
        data = store.load(tmp_project_with_pr["pm_dir"])
        data["project"]["backend"] = "vanilla"
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["workdir"] = str(tmp_project_with_pr["workdir"])
        store.save(data, tmp_project_with_pr["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project_with_pr["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0
        mock_gh_ops["mark_pr_ready"].assert_not_called()


class TestBackendPrInstructions:
    """Tests for GitHubBackend.pr_instructions with draft PR URL."""

    def test_instructions_with_draft_pr_url(self):
        """pr_instructions should include draft PR URL when provided."""
        from pm_core.backend import GitHubBackend

        backend = GitHubBackend()
        instructions = backend.pr_instructions(
            branch="pm/pr-001",
            title="Test PR",
            base_branch="main",
            pr_id="pr-001",
            gh_pr_url="https://github.com/owner/repo/pull/42",
        )

        assert "https://github.com/owner/repo/pull/42" in instructions
        assert "gh pr create" not in instructions

    def test_instructions_without_draft_pr_url(self):
        """pr_instructions should include gh pr create when no draft PR."""
        from pm_core.backend import GitHubBackend

        backend = GitHubBackend()
        instructions = backend.pr_instructions(
            branch="pm/pr-001",
            title="Test PR",
            base_branch="main",
            pr_id="pr-001",
            gh_pr_url=None,
        )

        assert "gh pr create" in instructions


class TestPrDisplayId:
    """Tests for _pr_display_id helper."""

    def test_with_gh_pr_number(self):
        """Should return #N when gh_pr_number is set."""
        pr = {"id": "pr-001", "gh_pr_number": 42}
        assert cli._pr_display_id(pr) == "#42"

    def test_without_gh_pr_number(self):
        """Should return pr-NNN when gh_pr_number is not set."""
        pr = {"id": "pr-001", "gh_pr_number": None}
        assert cli._pr_display_id(pr) == "pr-001"

    def test_without_gh_pr_number_key(self):
        """Should return pr-NNN when gh_pr_number key is missing."""
        pr = {"id": "pr-003"}
        assert cli._pr_display_id(pr) == "pr-003"
