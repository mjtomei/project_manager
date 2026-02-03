"""Tests for GitHub draft PR workflow in pr_start and pr_done."""

import json
from pathlib import Path
from unittest import mock

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
        "prs": [
            {
                "id": "pr-001",
                "title": "Test PR",
                "description": "Test description",
                "branch": "pm/pr-001",
                "status": "pending",
            }
        ],
        "plans": [],
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
def mock_git_ops():
    """Mock git operations."""
    with mock.patch.multiple(
        git_ops,
        clone=mock.DEFAULT,
        checkout_branch=mock.DEFAULT,
        pull_rebase=mock.DEFAULT,
        is_git_repo=mock.Mock(return_value=True),
        run_git=mock.Mock(return_value=mock.Mock(
            returncode=0,
            stdout="abc12345\n",
            stderr="",
        )),
    ) as mocks:
        yield mocks


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


class TestPrStartCreatesDraftPr:
    """Tests for draft PR creation during pr_start."""

    def test_creates_draft_pr_for_github_backend(self, tmp_project, mock_git_ops, mock_gh_ops):
        """pr_start should create a draft PR for GitHub backend."""
        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                with mock.patch.object(cli, "_workdirs_dir", return_value=tmp_project["workdir"].parent):
                    # Mock shutil.rmtree and shutil.move
                    with mock.patch("shutil.rmtree"):
                        with mock.patch("shutil.move"):
                            result = runner.invoke(cli.pr, ["start", "pr-001", "--workdir", str(tmp_project["workdir"])])

        # Should have attempted to create draft PR
        mock_gh_ops["create_draft_pr"].assert_called_once()
        call_args = mock_gh_ops["create_draft_pr"].call_args
        assert call_args[0][1] == "Test PR"  # title
        assert call_args[0][2] == "main"  # base branch

        # Check that gh_pr was stored in project.yaml
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["gh_pr"] == "https://github.com/owner/repo/pull/42"
        assert pr["gh_pr_number"] == 42

    def test_creates_empty_commit_before_draft_pr(self, tmp_project, mock_gh_ops):
        """pr_start should create an empty commit to enable draft PR creation."""
        runner = CliRunner()

        # Track run_git calls separately to verify empty commit
        run_git_calls = []
        original_run_git = git_ops.run_git

        def tracking_run_git(*args, **kwargs):
            run_git_calls.append((args, kwargs))
            return mock.Mock(returncode=0, stdout="abc12345\n", stderr="")

        with mock.patch.multiple(
            git_ops,
            clone=mock.DEFAULT,
            checkout_branch=mock.DEFAULT,
            pull_rebase=mock.DEFAULT,
            is_git_repo=mock.Mock(return_value=True),
            run_git=tracking_run_git,
        ):
            with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
                with mock.patch.object(cli, "find_claude", return_value=None):
                    with mock.patch.object(cli, "_workdirs_dir", return_value=tmp_project["workdir"].parent):
                        with mock.patch("shutil.rmtree"):
                            with mock.patch("shutil.move"):
                                result = runner.invoke(cli.pr, ["start", "pr-001", "--workdir", str(tmp_project["workdir"])])

        # Find the commit call in run_git calls
        commit_calls = [
            call for call in run_git_calls
            if len(call[0]) >= 2 and call[0][0] == "commit"
        ]
        assert len(commit_calls) >= 1, f"Expected at least one git commit call, got: {run_git_calls}"

        # Verify the commit is an empty commit with proper message
        commit_call = commit_calls[0]
        args = commit_call[0]
        assert "--allow-empty" in args
        assert "-m" in args
        # Find the message after -m
        msg_idx = args.index("-m") + 1
        commit_msg = args[msg_idx]
        assert "Start work on:" in commit_msg
        assert "Test PR" in commit_msg
        assert "pr-001" in commit_msg

    def test_skips_draft_pr_if_already_exists(self, tmp_project, mock_git_ops, mock_gh_ops):
        """pr_start should skip draft PR creation if gh_pr already set."""
        # Set gh_pr in project.yaml
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["gh_pr"] = "https://github.com/owner/repo/pull/99"
        pr["gh_pr_number"] = 99
        store.save(data, tmp_project["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                result = runner.invoke(cli.pr, ["start", "pr-001", "--workdir", str(tmp_project["workdir"])])

        # Should NOT have attempted to create draft PR
        mock_gh_ops["create_draft_pr"].assert_not_called()

    def test_no_draft_pr_for_vanilla_backend(self, tmp_project, mock_git_ops, mock_gh_ops):
        """pr_start should not create draft PR for vanilla backend."""
        # Change backend to vanilla
        data = store.load(tmp_project["pm_dir"])
        data["project"]["backend"] = "vanilla"
        store.save(data, tmp_project["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            with mock.patch.object(cli, "find_claude", return_value=None):
                result = runner.invoke(cli.pr, ["start", "pr-001", "--workdir", str(tmp_project["workdir"])])

        # Should NOT have attempted to create draft PR
        mock_gh_ops["create_draft_pr"].assert_not_called()

    def test_handles_push_failure_gracefully(self, tmp_project, mock_gh_ops):
        """pr_start should continue if push fails."""
        runner = CliRunner()

        # Mock git_ops with push failure
        with mock.patch.multiple(
            git_ops,
            clone=mock.DEFAULT,
            checkout_branch=mock.DEFAULT,
            pull_rebase=mock.DEFAULT,
            is_git_repo=mock.Mock(return_value=True),
            run_git=mock.Mock(return_value=mock.Mock(
                returncode=1,
                stdout="",
                stderr="push failed",
            )),
        ):
            with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
                with mock.patch.object(cli, "find_claude", return_value=None):
                    result = runner.invoke(cli.pr, ["start", "pr-001", "--workdir", str(tmp_project["workdir"])])

        # Should NOT have attempted to create draft PR since push failed
        mock_gh_ops["create_draft_pr"].assert_not_called()

        # But status should still be in_progress
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_progress"


class TestPrDoneUpgradesDraftPr:
    """Tests for draft PR upgrade during pr_done."""

    def test_upgrades_draft_to_ready_for_github_backend(self, tmp_project, mock_gh_ops):
        """pr_done should upgrade draft PR to ready for review."""
        # Set up PR as in_progress with gh_pr
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["gh_pr"] = "https://github.com/owner/repo/pull/42"
        pr["gh_pr_number"] = 42
        pr["workdir"] = str(tmp_project["workdir"])
        store.save(data, tmp_project["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0

        # Should have called mark_pr_ready
        mock_gh_ops["mark_pr_ready"].assert_called_once_with(
            str(tmp_project["workdir"]), 42
        )

        # Status should be in_review
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_skips_upgrade_if_no_gh_pr(self, tmp_project, mock_gh_ops):
        """pr_done should skip upgrade if no gh_pr is set."""
        # Set up PR as in_progress without gh_pr
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["workdir"] = str(tmp_project["workdir"])
        store.save(data, tmp_project["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0

        # Should NOT have called mark_pr_ready
        mock_gh_ops["mark_pr_ready"].assert_not_called()

        # Status should still be in_review
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_handles_upgrade_failure_gracefully(self, tmp_project, mock_gh_ops):
        """pr_done should continue if upgrade fails."""
        # Make upgrade fail
        mock_gh_ops["mark_pr_ready"].return_value = False

        # Set up PR as in_progress with gh_pr
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["gh_pr"] = "https://github.com/owner/repo/pull/42"
        pr["gh_pr_number"] = 42
        pr["workdir"] = str(tmp_project["workdir"])
        store.save(data, tmp_project["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0
        assert "Warning" in result.output

        # Status should still be in_review even if upgrade failed
        data = store.load(tmp_project["pm_dir"])
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_no_upgrade_for_vanilla_backend(self, tmp_project, mock_gh_ops):
        """pr_done should not upgrade for vanilla backend."""
        # Change backend to vanilla
        data = store.load(tmp_project["pm_dir"])
        data["project"]["backend"] = "vanilla"
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_progress"
        pr["workdir"] = str(tmp_project["workdir"])
        store.save(data, tmp_project["pm_dir"])

        runner = CliRunner()

        with mock.patch.object(cli, "state_root", return_value=tmp_project["pm_dir"]):
            result = runner.invoke(cli.pr, ["done", "pr-001"])

        assert result.exit_code == 0

        # Should NOT have called mark_pr_ready
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
        # Should NOT include gh pr create command
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

        # Should include gh pr create command
        assert "gh pr create" in instructions
