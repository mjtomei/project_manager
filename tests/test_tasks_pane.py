"""Tests for the tasks pane widget."""

import pytest

from pm_core.tui.tasks_pane import (
    TasksPane,
    TaskEntry,
    TaskWindowSwitch,
    TaskAction,
    _classify_window,
    GROUP_ORDER,
)


class TestClassifyWindow:
    """Tests for window name classification."""

    def test_implementation_gh_pr(self):
        group, pr_id, role, sub_id = _classify_window("#128")
        assert group == "Implementation"
        assert pr_id == "#128"
        assert role == "main"
        assert sub_id is None

    def test_implementation_local_pr(self):
        group, pr_id, role, sub_id = _classify_window("pr-001")
        assert group == "Implementation"
        assert pr_id == "pr-001"
        assert role == "main"

    def test_review_window(self):
        group, pr_id, role, sub_id = _classify_window("review-#128")
        assert group == "Review"
        assert pr_id == "#128"
        assert role == "main"

    def test_review_local_pr(self):
        group, pr_id, role, sub_id = _classify_window("review-pr-001")
        assert group == "Review"
        assert pr_id == "pr-001"

    def test_merge_window(self):
        group, pr_id, role, sub_id = _classify_window("merge-#128")
        assert group == "Review"
        assert pr_id == "#128"

    def test_qa_main(self):
        group, pr_id, role, sub_id = _classify_window("qa-#128")
        assert group == "QA"
        assert pr_id == "#128"
        assert role == "main"
        assert sub_id is None

    def test_qa_scenario(self):
        group, pr_id, role, sub_id = _classify_window("qa-#128-s1")
        assert group == "QA"
        assert pr_id == "#128"
        assert role == "sub"
        assert sub_id == "1"

    def test_qa_scenario_local_pr(self):
        group, pr_id, role, sub_id = _classify_window("qa-pr-001-s3")
        assert group == "QA"
        assert pr_id == "pr-001"
        assert role == "sub"
        assert sub_id == "3"

    def test_watcher(self):
        group, pr_id, role, sub_id = _classify_window("watcher")
        assert group == "Watcher"
        assert pr_id == ""
        assert role == "main"

    def test_unknown_window(self):
        group, pr_id, role, sub_id = _classify_window("random-window")
        assert group == "Other"
        assert role == "main"

    def test_main_window(self):
        group, pr_id, role, sub_id = _classify_window("main")
        assert group == "Other"


class TestTaskEntry:
    """Tests for TaskEntry data structure."""

    def test_basic_creation(self):
        entry = TaskEntry("Implementation", "#128", "#128", "1")
        assert entry.group == "Implementation"
        assert entry.pr_display_id == "#128"
        assert entry.main_window == "#128"
        assert entry.expanded is False
        assert entry.sub_windows == []

    def test_sub_windows(self):
        entry = TaskEntry("QA", "#128", "qa-#128", "2")
        entry.sub_windows.append(("qa-#128-s1", "3", "1"))
        entry.sub_windows.append(("qa-#128-s2", "4", "2"))
        assert len(entry.sub_windows) == 2


class TestTasksPane:
    """Tests for the TasksPane widget."""

    def test_initializes_empty(self):
        pane = TasksPane()
        assert pane._entries == []
        assert pane._flat_items == []

    def test_update_tasks_with_windows(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "#128"},
            {"id": "@3", "index": "2", "name": "review-#128"},
            {"id": "@4", "index": "3", "name": "qa-#128"},
            {"id": "@5", "index": "4", "name": "qa-#128-s1"},
        ]
        prs = [
            {"id": "pr-001", "gh_pr_number": 128, "title": "Fix bug", "status": "in_review"},
        ]
        pane.update_tasks(windows, prs, {}, {})

        # main window should be skipped
        # Should have: Implementation (#128), Review (#128), QA (#128 + s1)
        assert len(pane._entries) == 3

        # Check groups
        groups = [e.group for e in pane._entries]
        assert "Implementation" in groups
        assert "Review" in groups
        assert "QA" in groups

    def test_qa_sub_windows_collapsed(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "qa-#128"},
            {"id": "@3", "index": "2", "name": "qa-#128-s1"},
            {"id": "@4", "index": "3", "name": "qa-#128-s2"},
        ]
        prs = [{"id": "pr-001", "gh_pr_number": 128, "title": "Fix", "status": "qa"}]
        pane.update_tasks(windows, prs, {}, {})

        # Should have 1 QA entry with 2 sub-windows
        qa_entries = [e for e in pane._entries if e.group == "QA"]
        assert len(qa_entries) == 1
        assert len(qa_entries[0].sub_windows) == 2
        assert qa_entries[0].expanded is False

    def test_watcher_entry(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "watcher"},
        ]
        pane.update_tasks(windows, [], {}, {})

        watcher = [e for e in pane._entries if e.group == "Watcher"]
        assert len(watcher) == 1
        assert watcher[0].pr_display_id == ""

    def test_selectable_indices_skip_headers(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "#128"},
            {"id": "@3", "index": "2", "name": "watcher"},
        ]
        prs = [{"id": "pr-001", "gh_pr_number": 128, "title": "Fix", "status": "in_progress"}]
        pane.update_tasks(windows, prs, {}, {})

        selectable = pane._selectable_indices()
        # Headers are not selectable
        for idx in selectable:
            assert "_header" not in pane._flat_items[idx]

    def test_group_boundaries(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "#128"},
            {"id": "@3", "index": "2", "name": "review-#129"},
            {"id": "@4", "index": "3", "name": "watcher"},
        ]
        prs = [
            {"id": "pr-001", "gh_pr_number": 128, "title": "Fix", "status": "in_progress"},
            {"id": "pr-002", "gh_pr_number": 129, "title": "Add", "status": "in_review"},
        ]
        pane.update_tasks(windows, prs, {}, {})

        boundaries = pane._group_boundaries()
        # Should have boundaries for each group
        assert len(boundaries) >= 2  # Implementation, Review, Watcher

    def test_selected_pr_id(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "#128"},
        ]
        prs = [{"id": "pr-001", "gh_pr_number": 128, "title": "Fix", "status": "in_progress"}]
        pane.update_tasks(windows, prs, {}, {})

        # Select the first selectable item
        selectable = pane._selectable_indices()
        if selectable:
            pane.selected_index = selectable[0]
            assert pane.selected_pr_id == "pr-001"

    def test_selected_window_name(self):
        pane = TasksPane()
        windows = [
            {"id": "@1", "index": "0", "name": "main"},
            {"id": "@2", "index": "1", "name": "#128"},
        ]
        prs = [{"id": "pr-001", "gh_pr_number": 128, "title": "Fix", "status": "in_progress"}]
        pane.update_tasks(windows, prs, {}, {})

        selectable = pane._selectable_indices()
        if selectable:
            pane.selected_index = selectable[0]
            assert pane.selected_window_name == "#128"

    def test_empty_tasks_no_crash(self):
        pane = TasksPane()
        pane.update_tasks([], [], {}, {})
        assert pane._entries == []
        assert pane.selected_pr_id is None
        assert pane.selected_window_name is None


class TestGroupOrder:
    """Test group ordering."""

    def test_group_order_complete(self):
        assert "Implementation" in GROUP_ORDER
        assert "Review" in GROUP_ORDER
        assert "QA" in GROUP_ORDER
        assert "Watcher" in GROUP_ORDER
        assert "Other" in GROUP_ORDER

    def test_implementation_first(self):
        assert GROUP_ORDER.index("Implementation") < GROUP_ORDER.index("Review")
        assert GROUP_ORDER.index("Implementation") < GROUP_ORDER.index("QA")
