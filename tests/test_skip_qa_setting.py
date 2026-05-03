"""Tests for project-level skip_qa setting.

When project.skip_qa is true, the auto-start flow skips QA entirely:
review PASS goes straight to merge instead of transitioning to qa status.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pm_core import store


def _make_project(tmp_path, *, pr_status="in_review", auto_start=True,
                  auto_start_target="pr-001", skip_qa=False):
    """Create a minimal project.yaml and return (pm_dir, app mock)."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    project = {"name": "test", "repo": "/tmp/r", "base_branch": "master"}
    if skip_qa:
        project["skip_qa"] = True
    data = {
        "project": project,
        "prs": [{
            "id": "pr-001",
            "title": "Test PR",
            "branch": "test-branch",
            "status": pr_status,
            "workdir": str(tmp_path / "wd"),
            "depends_on": [],
            "notes": [],
        }],
    }
    store.save(data, pm_dir)

    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._auto_start = auto_start
    app._auto_start_target = auto_start_target
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    return pm_dir, app


class TestSkipQaReviewPass:
    """When skip_qa is true, review PASS skips QA and merges directly."""

    def test_skip_qa_calls_merge_instead_of_qa(self, tmp_path):
        """Review PASS with skip_qa should call _maybe_auto_merge, not QA."""
        pm_dir, app = _make_project(tmp_path, skip_qa=True)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch("pm_core.tui.auto_start.get_target", return_value="pr-001"), \
             patch("pm_core.tui.auto_start._transitive_deps", return_value=set()), \
             patch("pm_core.tui.review_loop_ui._maybe_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_qa:
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        mock_merge.assert_called_once_with(app, "pr-001")
        mock_qa.assert_not_called()

    def test_skip_qa_does_not_transition_to_qa_status(self, tmp_path):
        """PR should stay in_review (not transition to qa) when skip_qa is set."""
        pm_dir, app = _make_project(tmp_path, skip_qa=True)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch("pm_core.tui.auto_start.get_target", return_value="pr-001"), \
             patch("pm_core.tui.auto_start._transitive_deps", return_value=set()), \
             patch("pm_core.tui.review_loop_ui._maybe_auto_merge"):
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_without_skip_qa_still_transitions_to_qa(self, tmp_path):
        """Without skip_qa, the normal QA flow still works."""
        pm_dir, app = _make_project(tmp_path, skip_qa=False)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch("pm_core.tui.auto_start.get_target", return_value="pr-001"), \
             patch("pm_core.tui.auto_start._transitive_deps", return_value=set()), \
             patch("pm_core.tui.qa_loop_ui.start_qa"):
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"


class TestSkipQaSelfDriving:
    """skip_qa also applies to self-driving QA (zz t).  Manual zz t
    never triggers a merge itself — merge only fires when auto-start
    is enabled."""

    def test_self_driving_skip_qa_without_auto_start_does_not_merge(self, tmp_path):
        """Self-driving + skip_qa but auto-start off should not merge."""
        pm_dir, app = _make_project(tmp_path, skip_qa=True, auto_start=False)
        app._self_driving_qa = {"pr-001": MagicMock()}

        with patch("pm_core.tui.auto_start.is_enabled", return_value=False), \
             patch("pm_core.tui.review_loop_ui._attempt_merge") as mock_attempt, \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_qa:
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        # _maybe_auto_merge is called but returns early because auto-start
        # is disabled — so the underlying merge attempt never runs.
        mock_attempt.assert_not_called()
        mock_qa.assert_not_called()


class TestSkipQaAutoStartLoops:
    """_auto_start_qa_loops is a no-op when skip_qa is set."""

    def test_qa_loops_skipped_with_skip_qa(self, tmp_path):
        """No QA loops started when skip_qa is true."""
        pm_dir, app = _make_project(tmp_path, pr_status="qa", skip_qa=True)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_qa:
            from pm_core.tui.auto_start import _auto_start_qa_loops
            _auto_start_qa_loops(app, target="pr-001", prs=app._data["prs"])

        mock_qa.assert_not_called()

    def test_qa_loops_run_without_skip_qa(self, tmp_path):
        """QA loops still start normally without skip_qa."""
        pm_dir, app = _make_project(tmp_path, pr_status="qa", skip_qa=False)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch("pm_core.tui.auto_start._transitive_deps", return_value=set()), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_qa:
            from pm_core.tui.auto_start import _auto_start_qa_loops
            _auto_start_qa_loops(app, target="pr-001", prs=app._data["prs"])

        mock_qa.assert_called_once()
