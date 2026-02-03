"""Tests for the GuideProgress widget."""

import pytest
from rich.text import Text

from pm_core.tui.guide_progress import (
    GuideProgress,
    INTERACTIVE_STEPS,
    MARKER_COMPLETED,
    MARKER_CURRENT,
    MARKER_FUTURE,
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
        assert "needs_deps_review" in INTERACTIVE_STEPS
        assert "ready_to_work" in INTERACTIVE_STEPS

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
        assert "Guide Workflow" in result.plain

    def test_render_includes_all_interactive_steps(self):
        """render() should include all interactive step descriptions."""
        widget = GuideProgress()
        result = widget.render()
        text = result.plain
        for step in INTERACTIVE_STEPS:
            desc = STEP_DESCRIPTIONS[step]
            assert desc in text, f"Missing step description: {desc}"

    def test_render_includes_step_numbers(self):
        """render() should include step numbers."""
        widget = GuideProgress()
        result = widget.render()
        text = result.plain
        for i in range(1, len(INTERACTIVE_STEPS) + 1):
            assert f"{i}." in text, f"Missing step number: {i}"

    def test_render_uses_current_marker_for_current_step(self):
        """render() should use the current marker for the active step."""
        widget = GuideProgress(current_step="initialized")
        result = widget.render()
        # The marker should appear in the text
        assert MARKER_CURRENT in result.plain

    def test_render_uses_completed_marker_for_past_steps(self):
        """render() should use completed markers for past steps."""
        widget = GuideProgress(current_step="has_plan_draft")
        result = widget.render()
        # Should have completed markers for steps before current
        assert MARKER_COMPLETED in result.plain

    def test_render_uses_future_marker_for_upcoming_steps(self):
        """render() should use future markers for upcoming steps."""
        widget = GuideProgress(current_step="no_project")
        result = widget.render()
        # Should have future markers for steps after current
        assert MARKER_FUTURE in result.plain

    def test_render_shows_guide_running_hint(self):
        """render() should show guide running hint."""
        widget = GuideProgress(current_step="no_project")
        result = widget.render()
        assert "Guide running in adjacent pane" in result.plain

    def test_render_shows_dismiss_hint(self):
        """render() should show dismiss hint."""
        widget = GuideProgress(current_step="initialized")
        result = widget.render()
        assert "to dismiss" in result.plain
