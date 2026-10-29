"""Tests for pm_core.cli.helpers — shared CLI utility functions."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from pm_core.cli.helpers import (
    _infer_pr_id,
    _make_pr_entry,
    _pr_display_id,
    _pr_id_sort_key,
    _record_status_timestamp,
    _resolve_pr_id,
)


# ---------------------------------------------------------------------------
# _resolve_pr_id
# ---------------------------------------------------------------------------


class TestResolvePrId:
    """Tests for _resolve_pr_id (resolve by pm ID or GitHub PR number)."""

    @pytest.fixture()
    def data(self):
        return {
            "prs": [
                {"id": "pr-001", "title": "First", "gh_pr_number": 42},
                {"id": "pr-002", "title": "Second"},
                {"id": "pr-a3f2b1c", "title": "Hash ID", "gh_pr_number": 99},
            ]
        }

    def test_resolve_by_exact_pm_id(self, data):
        pr = _resolve_pr_id(data, "pr-001")
        assert pr is not None
        assert pr["id"] == "pr-001"

    def test_resolve_by_pm_id_not_found(self, data):
        assert _resolve_pr_id(data, "pr-999") is None

    def test_resolve_by_github_number(self, data):
        pr = _resolve_pr_id(data, "42")
        assert pr is not None
        assert pr["id"] == "pr-001"

    def test_resolve_by_github_number_not_found(self, data):
        assert _resolve_pr_id(data, "123") is None

    def test_resolve_hash_id(self, data):
        pr = _resolve_pr_id(data, "pr-a3f2b1c")
        assert pr is not None
        assert pr["title"] == "Hash ID"

    def test_resolve_invalid_string(self, data):
        assert _resolve_pr_id(data, "not-a-pr") is None

    def test_resolve_empty_prs(self):
        assert _resolve_pr_id({"prs": []}, "pr-001") is None

    def test_resolve_no_prs_key(self):
        assert _resolve_pr_id({}, "42") is None

    def test_resolve_pr_without_gh_number(self, data):
        """PR pr-002 has no gh_pr_number; resolving by number skips it."""
        pr = _resolve_pr_id(data, "99")
        assert pr is not None
        assert pr["id"] == "pr-a3f2b1c"


# ---------------------------------------------------------------------------
# _infer_pr_id
# ---------------------------------------------------------------------------


class TestInferPrId:
    """Tests for _infer_pr_id (infer PR from context)."""

    @pytest.fixture()
    def data(self):
        return {
            "project": {"active_pr": "pr-002"},
            "prs": [
                {"id": "pr-001", "status": "merged", "workdir": "/tmp/wd1"},
                {"id": "pr-002", "status": "in_progress", "workdir": "/tmp/wd2"},
                {"id": "pr-003", "status": "pending"},
            ],
        }

    def test_infer_from_active_pr(self, data):
        """If there's an active PR it should be returned (no status filter)."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data)
        assert result == "pr-002"

    def test_infer_from_active_pr_with_matching_filter(self, data):
        """Active PR returned when it matches the status filter."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("in_progress",))
        assert result == "pr-002"

    def test_infer_from_active_pr_with_nonmatching_filter(self, data):
        """Active PR skipped when it doesn't match the status filter."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("pending",))
        # Falls through to single-match: only pr-003 is pending
        assert result == "pr-003"

    def test_infer_from_workdir(self, data, tmp_path):
        """If cwd is inside a PR's workdir, that PR is returned."""
        wd = tmp_path / "wd"
        wd.mkdir()
        data["prs"][0]["workdir"] = str(wd)
        subdir = wd / "src"
        subdir.mkdir()
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = str(subdir)
            mock_path.return_value.resolve.return_value = wd.resolve()
            result = _infer_pr_id(data)
        assert result == "pr-001"

    def test_infer_no_active_no_filter(self, data):
        """No active PR and no status filter returns None when multiple PRs exist."""
        data["project"]["active_pr"] = None
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data)
        assert result is None

    def test_infer_single_match_on_filter(self, data):
        """When exactly one PR matches the status filter, return it."""
        data["project"]["active_pr"] = None
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("merged",))
        assert result == "pr-001"

    def test_infer_multiple_matches_returns_none(self, data):
        """When multiple PRs match the filter, return None."""
        data["prs"][2]["status"] = "in_progress"
        data["project"]["active_pr"] = None
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("in_progress",))
        assert result is None

    def test_infer_empty_prs(self):
        """With no PRs, returns None."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id({"prs": [], "project": {}})
        assert result is None


# ---------------------------------------------------------------------------
# _pr_id_sort_key
# ---------------------------------------------------------------------------


class TestPrIdSortKey:
    """Tests for _pr_id_sort_key (sort PR IDs numerically)."""

    def test_numeric_id(self):
        assert _pr_id_sort_key("pr-001") == (1, "")
        assert _pr_id_sort_key("pr-42") == (42, "")

    def test_hash_id(self):
        assert _pr_id_sort_key("pr-a3f2b1c") == (0, "a3f2b1c")

    def test_sorting_order(self):
        ids = ["pr-003", "pr-a3f2b1c", "pr-001", "pr-010"]
        sorted_ids = sorted(ids, key=_pr_id_sort_key)
        assert sorted_ids == ["pr-a3f2b1c", "pr-001", "pr-003", "pr-010"]

    def test_bare_id(self):
        assert _pr_id_sort_key("something") == (0, "something")


# ---------------------------------------------------------------------------
# _pr_display_id
# ---------------------------------------------------------------------------


class TestPrDisplayId:
    """Tests for _pr_display_id (prefer GitHub #N, fall back to local ID)."""

    def test_with_gh_number(self):
        assert _pr_display_id({"id": "pr-001", "gh_pr_number": 42}) == "#42"

    def test_without_gh_number(self):
        assert _pr_display_id({"id": "pr-001"}) == "pr-001"

    def test_with_none_gh_number(self):
        assert _pr_display_id({"id": "pr-002", "gh_pr_number": None}) == "pr-002"


# ---------------------------------------------------------------------------
# _make_pr_entry timestamps
# ---------------------------------------------------------------------------


class TestMakePrEntryTimestamps:
    """Tests for created_at and updated_at in _make_pr_entry."""

    def test_created_at_is_set(self):
        entry = _make_pr_entry("pr-001", "Test PR", "pm/pr-001-test")
        assert entry["created_at"] is not None
        # Should be a valid ISO 8601 timestamp
        dt = datetime.fromisoformat(entry["created_at"])
        assert dt.tzinfo is not None

    def test_updated_at_is_set(self):
        entry = _make_pr_entry("pr-001", "Test PR", "pm/pr-001-test")
        assert entry["updated_at"] is not None
        dt = datetime.fromisoformat(entry["updated_at"])
        assert dt.tzinfo is not None

    def test_created_at_equals_updated_at_on_creation(self):
        entry = _make_pr_entry("pr-001", "Test PR", "pm/pr-001-test")
        assert entry["created_at"] == entry["updated_at"]

    def test_started_at_still_none(self):
        entry = _make_pr_entry("pr-001", "Test PR", "pm/pr-001-test")
        assert entry["started_at"] is None
        assert entry["reviewed_at"] is None
        assert entry["merged_at"] is None


# ---------------------------------------------------------------------------
# _record_status_timestamp — updated_at
# ---------------------------------------------------------------------------


class TestRecordStatusTimestamp:
    """Tests for _record_status_timestamp setting updated_at."""

    def test_sets_updated_at_on_status_change(self):
        entry = {"status": "pending"}
        _record_status_timestamp(entry, "in_progress")
        assert "updated_at" in entry
        dt = datetime.fromisoformat(entry["updated_at"])
        assert dt.tzinfo is not None

    def test_sets_started_at_on_first_in_progress(self):
        entry = {"status": "pending"}
        _record_status_timestamp(entry, "in_progress")
        assert entry["started_at"] is not None
        assert entry["updated_at"] is not None

    def test_does_not_overwrite_started_at(self):
        entry = {"status": "in_progress", "started_at": "2024-01-01T00:00:00+00:00"}
        _record_status_timestamp(entry, "in_progress")
        assert entry["started_at"] == "2024-01-01T00:00:00+00:00"
        # But updated_at should be refreshed
        assert entry["updated_at"] != "2024-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# _record_status_timestamp without status (updated_at only)
# ---------------------------------------------------------------------------


class TestRecordStatusTimestampNoStatus:
    """Tests for _record_status_timestamp called without a status arg."""

    def test_sets_updated_at(self):
        entry = {}
        _record_status_timestamp(entry)
        assert "updated_at" in entry
        dt = datetime.fromisoformat(entry["updated_at"])
        assert dt.tzinfo is not None

    def test_overwrites_existing(self):
        entry = {"updated_at": "2024-01-01T00:00:00+00:00"}
        _record_status_timestamp(entry)
        assert entry["updated_at"] != "2024-01-01T00:00:00+00:00"

    def test_does_not_set_status_timestamps(self):
        entry = {}
        _record_status_timestamp(entry)
        assert "started_at" not in entry
        assert "reviewed_at" not in entry
        assert "merged_at" not in entry


# ---------------------------------------------------------------------------
# _ensure_workdir
# ---------------------------------------------------------------------------

from pm_core.cli.helpers import _ensure_workdir


class TestEnsureWorkdir:
    """Tests for _ensure_workdir — auto-create workdir when missing."""

    def test_returns_existing_workdir(self, tmp_path):
        """When workdir exists on disk, returns it unchanged."""
        workdir = tmp_path / "existing"
        workdir.mkdir()
        pr_entry = {"id": "pr-001", "workdir": str(workdir), "branch": "pm/pr-001"}
        data = {"project": {"name": "test", "repo": "/tmp/repo"}}
        result = _ensure_workdir(data, pr_entry, tmp_path)
        assert result == str(workdir)

    def test_returns_none_when_no_branch(self, tmp_path):
        """When PR has no branch, returns None."""
        pr_entry = {"id": "pr-001", "workdir": "/nonexistent"}
        data = {"project": {"name": "test"}}
        result = _ensure_workdir(data, pr_entry, tmp_path)
        assert result is None

    def test_returns_none_when_no_repo_source(self, tmp_path):
        """When there's no repo source, returns None."""
        pr_entry = {"id": "pr-001", "workdir": "/nonexistent", "branch": "pm/pr-001"}
        data = {"project": {"name": "test"}}
        with patch("pm_core.cli.helpers._resolve_repo_dir", return_value=tmp_path / "nope"):
            result = _ensure_workdir(data, pr_entry, tmp_path)
        assert result is None

    def test_clones_and_returns_new_workdir(self, tmp_path):
        """When workdir is missing, clones repo and returns new path."""
        pm_root = tmp_path / "pm"
        pm_root.mkdir()
        pr_entry = {"id": "pr-001", "workdir": "/nonexistent", "branch": "pm/pr-001"}
        data = {"project": {"name": "test", "repo_id": "abc12345def", "repo": "https://example.com/repo.git"}}

        fake_workdir = tmp_path / "workdirs" / "test-abc12345"
        calls = {}

        def fake_clone(src, dest, branch=None):
            dest.mkdir(parents=True, exist_ok=True)
            calls["clone"] = (src, dest, branch)

        def fake_checkout(wd, branch, create=False, no_hooks=False):
            calls["checkout"] = (wd, branch, create)
            calls["checkout_no_hooks"] = no_hooks

        def fake_run_git(*args, cwd=None, check=True, **kw):
            from types import SimpleNamespace
            return SimpleNamespace(stdout="abcd1234", returncode=0, stderr="")

        with patch("pm_core.cli.helpers._resolve_repo_dir", return_value=tmp_path / "nope"), \
             patch("pm_core.cli.helpers.git_ops.clone", side_effect=fake_clone), \
             patch("pm_core.cli.helpers.git_ops.checkout_branch", side_effect=fake_checkout), \
             patch("pm_core.cli.helpers.git_ops.run_git", side_effect=fake_run_git), \
             patch("pm_core.cli.helpers.git_ops.is_git_repo", return_value=False), \
             patch("pm_core.cli.helpers._resolve_repo_id"), \
             patch("pm_core.cli.helpers.store.locked_update"):
            result = _ensure_workdir(data, pr_entry, pm_root)

        assert result is not None
        assert pr_entry["workdir"] == result
        assert "clone" in calls
        assert "checkout" in calls
        # The workdir is container-writable: its hooks never run on the host.
        assert calls["checkout_no_hooks"] is True

    def test_returns_none_when_no_workdir_set(self, tmp_path):
        """When workdir is None/empty, returns None (no branch to clone)."""
        pr_entry = {"id": "pr-001", "workdir": None}
        data = {"project": {"name": "test"}}
        result = _ensure_workdir(data, pr_entry, tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# _find_live_tui_pane
# ---------------------------------------------------------------------------


class TestFindLiveTuiPane:
    """_find_live_tui_pane must not hand a dead pane to pm tui view/send.

    The pane registry keeps its ``role="tui"`` entry after the TUI exits
    until the next heal_registry pass.  Driving that pane used to make
    ``pm tui view`` print an empty frame with exit 0 and ``pm tui send``
    raise a raw tmux error.
    """

    def _registry(self, *panes):
        return {
            "session": "pm-test",
            "windows": {"@0": {"panes": list(panes), "user_modified": False}},
            "generation": "1",
        }

    def _panes(self, stdout):
        from types import SimpleNamespace
        return patch(
            "pm_core.cli.helpers.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=stdout),
        )

    def test_dead_tui_entry_is_not_returned(self):
        from pm_core.cli.helpers import _find_live_tui_pane

        data = self._registry(
            {"id": "%6", "role": "tui", "order": 0, "cmd": "pm _tui"})
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=data), \
             self._panes("%3 pm-test bash\n"):
            assert _find_live_tui_pane("pm-test") == (None, "pm-test")

    def test_live_tui_entry_is_returned(self):
        from pm_core.cli.helpers import _find_live_tui_pane

        data = self._registry(
            {"id": "%6", "role": "tui", "order": 0, "cmd": "pm _tui"})
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=data), \
             self._panes('%6 pm-test "pm _tui"\n'):
            assert _find_live_tui_pane("pm-test") == ("%6", "pm-test")

    def test_dead_entry_falls_back_to_a_live_tui_in_same_session(self):
        from pm_core.cli.helpers import _find_live_tui_pane

        data = self._registry(
            {"id": "%6", "role": "tui", "order": 0, "cmd": "pm _tui"})
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=data), \
             self._panes("%3 pm-test bash\n"
                         '%8 pm-test "pm _tui"\n'
                         '%9 pm-other "pm _tui"\n'):
            assert _find_live_tui_pane("pm-test") == ("%8", "pm-test")

    def test_never_falls_back_to_another_session(self):
        from pm_core.cli.helpers import _find_live_tui_pane

        data = self._registry(
            {"id": "%6", "role": "tui", "order": 0, "cmd": "pm _tui"})
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=data), \
             self._panes('%9 pm-other "pm _tui"\n'):
            assert _find_live_tui_pane("pm-test") == (None, "pm-test")

    def test_tmux_unavailable_degrades_to_no_live_tui(self):
        from pm_core.cli.helpers import _find_live_tui_pane

        data = self._registry(
            {"id": "%6", "role": "tui", "order": 0, "cmd": "pm _tui"})
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=data), \
             patch("pm_core.cli.helpers.subprocess.run",
                   side_effect=OSError("no tmux")):
            assert _find_live_tui_pane("pm-test") == (None, "pm-test")

    def test_find_tui_pane_still_reports_the_dead_pane_for_autostart(self):
        """pm autostart needs the session even when its pane is dead so it
        can report the stale pidfile for that session."""
        from pm_core.cli.helpers import _find_tui_pane

        data = self._registry(
            {"id": "%6", "role": "tui", "order": 0, "cmd": "pm _tui"})
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=data):
            assert _find_tui_pane("pm-test") == ("%6", "pm-test")

    def test_explicit_session_without_a_registry_entry_falls_back(self):
        """A hand-started TUI has no registry entry until heal_registry
        runs; ``pm tui view -s S`` must still resolve its live pane.

        ``_find_tui_pane`` only consults the registry when a session is
        passed, so it returns ``(None, None)`` here — the live-pane scan
        is what makes the explicit-session path work at all."""
        from pm_core.cli.helpers import _find_live_tui_pane

        empty = {"session": "pm-test", "windows": {}, "generation": "1"}
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=empty), \
             self._panes('%3 pm-test bash\n'
                         '%8 pm-test "pm _tui"\n'):
            assert _find_live_tui_pane("pm-test") == ("%8", "pm-test")

    def test_explicit_session_without_a_live_tui_still_reports_the_session(
            self):
        """The caller needs the session name for its error message."""
        from pm_core.cli.helpers import _find_live_tui_pane

        empty = {"session": "pm-test", "windows": {}, "generation": "1"}
        with patch("pm_core.cli.helpers.pane_registry.load_registry",
                   return_value=empty), \
             self._panes("%3 pm-test bash\n"):
            assert _find_live_tui_pane("pm-test") == (None, "pm-test")


# ---------------------------------------------------------------------------
# trigger_tui_restart
# ---------------------------------------------------------------------------


class TestTriggerTuiRestart:
    """The merge-restart marker must not outlive a restart that failed.

    ``save_breadcrumb`` is the only consumer and it runs when the TUI
    actually restarts, so a marker left behind by a failed send would make
    the next start (even a plain Ctrl+R) behave as a merge restart.
    """

    def _run(self, tmp_path, pane, send_side_effect=None):
        from pm_core.cli.helpers import trigger_tui_restart

        marker = tmp_path / "merge-restart"
        with patch("pm_core.cli.helpers.tmux_mod.has_tmux",
                   return_value=True), \
             patch("pm_core.cli.helpers._find_live_tui_pane",
                   return_value=pane), \
             patch("pm_core.cli.helpers.tmux_mod.send_keys_literal",
                   side_effect=send_side_effect) as send, \
             patch("pm_core.paths.pm_home", return_value=tmp_path):
            trigger_tui_restart()
        return marker, send

    def test_writes_the_marker_and_sends_ctrl_r(self, tmp_path):
        marker, send = self._run(tmp_path, ("%8", "pm-test"))
        assert marker.exists()
        send.assert_called_once_with("%8", "C-r")

    def test_removes_the_marker_when_the_send_fails(self, tmp_path):
        marker, send = self._run(tmp_path, ("%8", "pm-test"),
                                 send_side_effect=RuntimeError("no pane"))
        assert send.called
        assert not marker.exists()

    def test_writes_nothing_without_a_live_pane(self, tmp_path):
        marker, send = self._run(tmp_path, (None, "pm-test"))
        assert not marker.exists()
        assert not send.called

