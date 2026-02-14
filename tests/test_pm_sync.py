"""Tests for pm_sync: hash-based PR IDs and remote state sync/merge."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from pm_core import store, pm_sync


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a temporary PM root directory with minimal project.yaml."""
    root = tmp_path / "pm"
    root.mkdir()
    (root / "plans").mkdir()
    data = {
        "project": {
            "name": "test-project",
            "repo": "/tmp/test-repo",
            "base_branch": "main",
            "backend": "vanilla",
        },
        "plans": [],
        "prs": [],
    }
    store.save(data, root)
    return root


# ── generate_pr_id tests ─────────────────────────────────────────────


class TestGeneratePrId:
    """Tests for hash-based PR ID generation."""

    def test_deterministic(self):
        """Same title+desc always produces the same ID."""
        id1 = store.generate_pr_id("Add feature X", "Description")
        id2 = store.generate_pr_id("Add feature X", "Description")
        assert id1 == id2

    def test_starts_with_pr_prefix(self):
        """Generated IDs start with 'pr-'."""
        pr_id = store.generate_pr_id("Test PR", "")
        assert pr_id.startswith("pr-")

    def test_hash_length(self):
        """Default hash is 7 hex chars."""
        pr_id = store.generate_pr_id("Test PR", "")
        # pr- prefix + 7 hex chars
        assert len(pr_id) == 3 + 7

    def test_different_titles_different_ids(self):
        """Different titles produce different IDs."""
        id1 = store.generate_pr_id("Feature A", "")
        id2 = store.generate_pr_id("Feature B", "")
        assert id1 != id2

    def test_different_descriptions_different_ids(self):
        """Different descriptions produce different IDs."""
        id1 = store.generate_pr_id("Same Title", "Desc A")
        id2 = store.generate_pr_id("Same Title", "Desc B")
        assert id1 != id2

    def test_avoids_existing_ids(self):
        """Extends hash when collision with existing ID."""
        pr_id = store.generate_pr_id("Test", "")
        # Force collision by including the generated ID in existing set
        extended = store.generate_pr_id("Test", "", existing_ids={pr_id})
        assert extended != pr_id
        assert extended.startswith("pr-")
        # Extended hash should be longer
        assert len(extended) > len(pr_id)

    def test_empty_description_ok(self):
        """Works with empty description."""
        pr_id = store.generate_pr_id("Title Only", "")
        assert pr_id.startswith("pr-")

    def test_no_existing_ids(self):
        """Works when no existing IDs provided."""
        pr_id = store.generate_pr_id("Title", "Desc", existing_ids=None)
        assert pr_id.startswith("pr-")

    def test_backwards_compatible_with_old_ids(self):
        """Old pr-001 style IDs in existing set don't interfere."""
        existing = {"pr-001", "pr-002", "pr-003"}
        pr_id = store.generate_pr_id("New Feature", "", existing_ids=existing)
        assert pr_id.startswith("pr-")
        assert pr_id not in existing


# ── merge_project_data tests ─────────────────────────────────────────


class TestMergeProjectData:
    """Tests for YAML-aware merge of project.yaml data."""

    def _base_data(self, **overrides):
        data = {
            "project": {
                "name": "test",
                "repo": "git@example.com:test.git",
                "base_branch": "main",
                "backend": "vanilla",
            },
            "plans": [],
            "prs": [],
        }
        data.update(overrides)
        return data

    def test_identical_data_returns_equivalent(self):
        """Merging identical data produces equivalent output."""
        data = self._base_data()
        merged = pm_sync.merge_project_data(data, data)
        assert merged["project"]["name"] == "test"
        assert merged["prs"] == []
        assert merged["plans"] == []

    def test_remote_new_pr_added(self):
        """PRs only in remote are added to merged result."""
        local = self._base_data()
        remote = self._base_data(prs=[
            {"id": "pr-abc1234", "title": "Remote PR", "branch": "pm/pr-abc1234-remote",
             "status": "pending", "depends_on": []},
        ])
        merged = pm_sync.merge_project_data(local, remote)
        assert len(merged["prs"]) == 1
        assert merged["prs"][0]["id"] == "pr-abc1234"

    def test_local_new_pr_preserved(self):
        """PRs only in local are preserved."""
        local = self._base_data(prs=[
            {"id": "pr-def5678", "title": "Local PR", "branch": "pm/pr-def5678-local",
             "status": "pending", "depends_on": []},
        ])
        remote = self._base_data()
        merged = pm_sync.merge_project_data(local, remote)
        assert len(merged["prs"]) == 1
        assert merged["prs"][0]["id"] == "pr-def5678"

    def test_both_new_prs_unioned(self):
        """PRs from both local and remote are included."""
        local = self._base_data(prs=[
            {"id": "pr-local1", "title": "Local", "branch": "pm/pr-local1",
             "status": "pending", "depends_on": []},
        ])
        remote = self._base_data(prs=[
            {"id": "pr-remote1", "title": "Remote", "branch": "pm/pr-remote1",
             "status": "pending", "depends_on": []},
        ])
        merged = pm_sync.merge_project_data(local, remote)
        ids = {p["id"] for p in merged["prs"]}
        assert ids == {"pr-local1", "pr-remote1"}

    def test_status_progression_prefers_higher(self):
        """For shared PRs, more advanced status wins."""
        pr = {"id": "pr-abc", "title": "T", "branch": "b", "depends_on": []}
        local = self._base_data(prs=[{**pr, "status": "in_progress"}])
        remote = self._base_data(prs=[{**pr, "status": "merged"}])
        merged = pm_sync.merge_project_data(local, remote)
        assert merged["prs"][0]["status"] == "merged"

    def test_status_closed_wins(self):
        """Closed status always wins over other statuses."""
        pr = {"id": "pr-abc", "title": "T", "branch": "b", "depends_on": []}
        local = self._base_data(prs=[{**pr, "status": "in_review"}])
        remote = self._base_data(prs=[{**pr, "status": "closed"}])
        merged = pm_sync.merge_project_data(local, remote)
        assert merged["prs"][0]["status"] == "closed"

    def test_gh_fields_prefer_non_none(self):
        """GitHub fields prefer non-None values."""
        pr_base = {"id": "pr-abc", "title": "T", "branch": "b",
                   "status": "pending", "depends_on": []}
        local = self._base_data(prs=[
            {**pr_base, "gh_pr": None, "gh_pr_number": None},
        ])
        remote = self._base_data(prs=[
            {**pr_base, "gh_pr": "https://github.com/test/pull/1", "gh_pr_number": 1},
        ])
        merged = pm_sync.merge_project_data(local, remote)
        assert merged["prs"][0]["gh_pr_number"] == 1
        assert "github.com" in merged["prs"][0]["gh_pr"]

    def test_workdir_prefers_local(self):
        """Machine-specific fields prefer local values."""
        pr_base = {"id": "pr-abc", "title": "T", "branch": "b",
                   "status": "pending", "depends_on": []}
        local = self._base_data(prs=[
            {**pr_base, "workdir": "/local/path", "agent_machine": "laptop"},
        ])
        remote = self._base_data(prs=[
            {**pr_base, "workdir": "/remote/path", "agent_machine": "server"},
        ])
        merged = pm_sync.merge_project_data(local, remote)
        assert merged["prs"][0]["workdir"] == "/local/path"
        assert merged["prs"][0]["agent_machine"] == "laptop"

    def test_depends_on_union(self):
        """depends_on lists are unioned."""
        pr_base = {"id": "pr-abc", "title": "T", "branch": "b", "status": "pending"}
        local = self._base_data(prs=[{**pr_base, "depends_on": ["pr-001", "pr-002"]}])
        remote = self._base_data(prs=[{**pr_base, "depends_on": ["pr-002", "pr-003"]}])
        merged = pm_sync.merge_project_data(local, remote)
        assert sorted(merged["prs"][0]["depends_on"]) == ["pr-001", "pr-002", "pr-003"]

    def test_active_pr_prefers_local(self):
        """active_pr is a local preference."""
        local = self._base_data()
        local["project"]["active_pr"] = "pr-local"
        remote = self._base_data()
        remote["project"]["active_pr"] = "pr-remote"
        merged = pm_sync.merge_project_data(local, remote)
        assert merged["project"]["active_pr"] == "pr-local"

    def test_plan_union(self):
        """Plans from both sides are unioned by ID."""
        local = self._base_data(plans=[
            {"id": "plan-001", "name": "Local Plan", "file": "plans/plan-001.md", "status": "draft"},
        ])
        remote = self._base_data(plans=[
            {"id": "plan-002", "name": "Remote Plan", "file": "plans/plan-002.md", "status": "draft"},
        ])
        merged = pm_sync.merge_project_data(local, remote)
        ids = {p["id"] for p in merged["plans"]}
        assert ids == {"plan-001", "plan-002"}

    def test_plan_status_prefers_higher(self):
        """Shared plan's status prefers the more advanced one."""
        plan = {"id": "plan-001", "name": "Plan", "file": "plans/plan-001.md"}
        local = self._base_data(plans=[{**plan, "status": "accepted"}])
        remote = self._base_data(plans=[{**plan, "status": "in_progress"}])
        merged = pm_sync.merge_project_data(local, remote)
        assert merged["plans"][0]["status"] == "accepted"

    def test_remote_order_preserved(self):
        """Remote PRs appear first in the merged list, then local-only."""
        local = self._base_data(prs=[
            {"id": "pr-local", "title": "L", "branch": "b1", "status": "pending", "depends_on": []},
            {"id": "pr-shared", "title": "S", "branch": "b2", "status": "pending", "depends_on": []},
        ])
        remote = self._base_data(prs=[
            {"id": "pr-shared", "title": "S", "branch": "b2", "status": "pending", "depends_on": []},
            {"id": "pr-remote", "title": "R", "branch": "b3", "status": "pending", "depends_on": []},
        ])
        merged = pm_sync.merge_project_data(local, remote)
        ids = [p["id"] for p in merged["prs"]]
        # Remote order first (pr-shared, pr-remote), then local-only (pr-local)
        assert ids == ["pr-shared", "pr-remote", "pr-local"]


# ── sync_pm_state tests ──────────────────────────────────────────────


class TestSyncPmState:
    """Tests for the top-level sync function."""

    def test_throttled_returns_unchanged(self, tmp_pm_root):
        """sync_pm_state returns unchanged data when throttled."""
        data = store.load(tmp_pm_root)
        # Set recent sync timestamp
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        data["project"]["last_pm_sync"] = recent.isoformat()

        merged, changed = pm_sync.sync_pm_state(tmp_pm_root, data)
        assert changed is False

    def test_force_bypasses_throttle(self, tmp_pm_root):
        """force=True bypasses the throttle interval."""
        data = store.load(tmp_pm_root)
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        data["project"]["last_pm_sync"] = recent.isoformat()

        with patch("pm_core.pm_sync.fetch_remote_state", return_value=None):
            merged, changed = pm_sync.sync_pm_state(tmp_pm_root, data, force=True)
        # fetch was called (bypassed throttle) but no remote → no change
        assert changed is False

    def test_no_remote_returns_unchanged(self, tmp_pm_root):
        """When fetch returns None, data is unchanged."""
        data = store.load(tmp_pm_root)

        with patch("pm_core.pm_sync.fetch_remote_state", return_value=None):
            merged, changed = pm_sync.sync_pm_state(tmp_pm_root, data, force=True)
        assert changed is False

    def test_identical_remote_no_change(self, tmp_pm_root):
        """When remote is identical to local, no change."""
        data = store.load(tmp_pm_root)

        with patch("pm_core.pm_sync.fetch_remote_state", return_value=dict(data)):
            merged, changed = pm_sync.sync_pm_state(tmp_pm_root, data, force=True)
        assert changed is False

    def test_remote_with_new_pr_merges(self, tmp_pm_root):
        """When remote has a new PR, it gets merged in."""
        data = store.load(tmp_pm_root)
        remote = dict(data)
        remote["prs"] = [
            {"id": "pr-remote1", "title": "Remote PR", "branch": "pm/pr-remote1",
             "status": "pending", "depends_on": []},
        ]

        with patch("pm_core.pm_sync.fetch_remote_state", return_value=remote):
            merged, changed = pm_sync.sync_pm_state(tmp_pm_root, data, force=True)
        assert changed is True
        assert len(merged["prs"]) == 1
        assert merged["prs"][0]["id"] == "pr-remote1"


# ── fetch_remote_state tests ─────────────────────────────────────────


class TestFetchRemoteState:
    """Tests for fetching remote project.yaml via git."""

    def test_fetch_failure_returns_none(self, tmp_pm_root):
        """Returns None when git fetch fails."""
        data = store.load(tmp_pm_root)
        mock_fail = MagicMock()
        mock_fail.returncode = 1
        mock_fail.stderr = "fatal: no remote"

        with patch("pm_core.git_ops.run_git", return_value=mock_fail):
            result = pm_sync.fetch_remote_state(tmp_pm_root, data)
        assert result is None

    def test_git_show_failure_returns_none(self, tmp_pm_root):
        """Returns None when git show fails (file doesn't exist on remote)."""
        data = store.load(tmp_pm_root)
        mock_fetch_ok = MagicMock(returncode=0)
        mock_show_fail = MagicMock(returncode=1, stderr="does not exist")

        def side_effect(*args, **kwargs):
            if args[0] == "fetch":
                return mock_fetch_ok
            return mock_show_fail

        with patch("pm_core.git_ops.run_git", side_effect=side_effect):
            result = pm_sync.fetch_remote_state(tmp_pm_root, data)
        assert result is None

    def test_successful_fetch_returns_data(self, tmp_pm_root):
        """Returns parsed dict when git fetch + show succeed."""
        data = store.load(tmp_pm_root)
        remote_yaml = yaml.dump({
            "project": {"name": "test-project", "base_branch": "main"},
            "plans": [],
            "prs": [{"id": "pr-abc", "title": "Remote PR"}],
        })
        mock_fetch_ok = MagicMock(returncode=0)
        mock_show_ok = MagicMock(returncode=0, stdout=remote_yaml)

        def side_effect(*args, **kwargs):
            if args[0] == "fetch":
                return mock_fetch_ok
            return mock_show_ok

        with patch("pm_core.git_ops.run_git", side_effect=side_effect):
            result = pm_sync.fetch_remote_state(tmp_pm_root, data)
        assert result is not None
        assert len(result["prs"]) == 1
        assert result["prs"][0]["id"] == "pr-abc"

    def test_yaml_parse_error_returns_none(self, tmp_pm_root):
        """Returns None when remote YAML is malformed."""
        data = store.load(tmp_pm_root)
        mock_fetch_ok = MagicMock(returncode=0)
        mock_show_ok = MagicMock(returncode=0, stdout="{{invalid yaml: [")

        def side_effect(*args, **kwargs):
            if args[0] == "fetch":
                return mock_fetch_ok
            return mock_show_ok

        with patch("pm_core.git_ops.run_git", side_effect=side_effect):
            result = pm_sync.fetch_remote_state(tmp_pm_root, data)
        assert result is None

    def test_local_backend_skips_fetch(self, tmp_pm_root):
        """Local backend reads from local branch, not origin."""
        data = store.load(tmp_pm_root)
        data["project"]["backend"] = "local"

        calls = []

        def track_calls(*args, **kwargs):
            calls.append(args)
            return MagicMock(returncode=1, stderr="no ref", stdout="")

        with patch("pm_core.git_ops.run_git", side_effect=track_calls):
            pm_sync.fetch_remote_state(tmp_pm_root, data)

        # Should NOT call "fetch", only "show"
        git_commands = [c[0] for c in calls]
        assert "fetch" not in git_commands
        assert "show" in git_commands


# ── sync_plan_files tests ────────────────────────────────────────────


class TestSyncPlanFiles:
    """Tests for plan file syncing."""

    def test_existing_file_not_overwritten(self, tmp_pm_root):
        """Plan files that already exist locally are not overwritten."""
        plan_file = tmp_pm_root / "plans" / "plan-001.md"
        plan_file.write_text("# Local content")

        data = {
            "project": {"base_branch": "main", "backend": "vanilla"},
            "plans": [{"id": "plan-001", "file": "plans/plan-001.md"}],
        }

        synced = pm_sync.sync_plan_files(tmp_pm_root, data)
        assert synced == 0
        assert plan_file.read_text() == "# Local content"

    def test_missing_file_pulled(self, tmp_pm_root):
        """Missing plan files are pulled from remote."""
        data = {
            "project": {"base_branch": "main", "backend": "vanilla"},
            "plans": [{"id": "plan-002", "file": "plans/plan-002.md"}],
        }

        mock_show = MagicMock(returncode=0, stdout="# Remote plan content\n")

        with patch("pm_core.git_ops.run_git", return_value=mock_show):
            synced = pm_sync.sync_plan_files(tmp_pm_root, data)

        assert synced == 1
        assert (tmp_pm_root / "plans" / "plan-002.md").read_text() == "# Remote plan content\n"
