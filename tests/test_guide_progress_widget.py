"""Tests for the GuideProgress widget."""

import pytest
from rich.text import Text

from pm_core.tui.guide_progress import (
    GuideProgress,
    INTERACTIVE_STEPS,
    MARKER_DONE,
    MARKER_CURRENT,
    MARKER_TODO,
)
from pm_core.guide import STEP_ORDER, STEP_DESCRIPTIONS


class TestGuideProgress:
    """Tests for the GuideProgress widget."""

    def test_interactive_steps_excludes_terminal_states(self):
        """INTERACTIVE_STEPS should not include terminal states."""
        assert "all_in_progress" not in INTERACTIVE_STEPS
        assert "all_done" not in INTERACTIVE_STEPS

    def test_interactive_steps_includes_user_facing_steps(self):
        """INTERACTIVE_STEPS should include all user-facing steps."""
        assert "no_project" in INTERACTIVE_STEPS
        assert "initialized" in INTERACTIVE_STEPS
        assert "has_plan_draft" in INTERACTIVE_STEPS
        assert "has_plan_prs" in INTERACTIVE_STEPS

    def test_interactive_steps_excludes_detection_only_states(self):
        """INTERACTIVE_STEPS should not include detection-only states."""
        assert "ready_to_work" not in INTERACTIVE_STEPS

    def test_widget_initializes_with_default_step(self):
        """Widget should default to no_project step."""
        widget = GuideProgress()
        assert widget.current_step == "no_project"

    def test_widget_initializes_with_custom_step(self):
        """Widget should accept a custom initial step."""
        widget = GuideProgress(current_step="initialized")
        assert widget.current_step == "initialized"

    def test_update_step_changes_current_step(self):
        """update_step should change the current step."""
        widget = GuideProgress()
        widget.update_step("has_plan_draft")
        assert widget.current_step == "has_plan_draft"

    def test_render_returns_text_object(self):
        """render() should return a Text object."""
        widget = GuideProgress()
        result = widget.render()
        assert isinstance(result, Text)

    def test_render_includes_header(self):
        """render() should include the header."""
        widget = GuideProgress()
        result = widget.render()
        assert "Project Setup" in result.plain

    def test_render_includes_checklist_items(self):
        """render() should include all checklist items."""
        widget = GuideProgress()
        result = widget.render()
        text = result.plain
        assert "Project file" in text
        assert "Plan file" in text
        assert "PRs loaded" in text

    def test_render_uses_current_marker_for_first_item(self):
        """On no_project, first checklist item should be current."""
        widget = GuideProgress(current_step="no_project")
        result = widget.render()
        assert MARKER_CURRENT in result.plain

    def test_render_uses_done_marker_for_past_items(self):
        """On has_plan_draft, project file should be done."""
        widget = GuideProgress(current_step="has_plan_draft")
        result = widget.render()
        assert MARKER_DONE in result.plain

    def test_render_uses_todo_marker_for_future_items(self):
        """On no_project, later items should be todo."""
        widget = GuideProgress(current_step="no_project")
        result = widget.render()
        assert MARKER_TODO in result.plain

    def test_render_shows_h_key_hint(self):
        """render() should show H key hint for restarting guide."""
        widget = GuideProgress(current_step="no_project")
        result = widget.render()
        assert "H" in result.plain
        assert "restart" in result.plain
        assert "Guide running" in result.plain

    def test_render_no_dismiss_hint(self):
        """render() should not show a dismiss hint."""
        widget = GuideProgress(current_step="initialized")
        result = widget.render()
        assert "dismiss" not in result.plain
