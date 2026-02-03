"""Tests for TUI tech tree status display."""

import pytest

from pm_core.tui.tech_tree import STATUS_ICONS, STATUS_STYLES, STATUS_BG


class TestStatusIcons:
    """Tests for STATUS_ICONS dictionary."""

    def test_pending_icon(self):
        """Pending status has empty circle icon."""
        assert STATUS_ICONS["pending"] == "○"

    def test_in_progress_icon(self):
        """In-progress status has filled circle icon."""
        assert STATUS_ICONS["in_progress"] == "●"

    def test_in_review_icon(self):
        """In-review status has target circle icon."""
        assert STATUS_ICONS["in_review"] == "◎"

    def test_merged_icon(self):
        """Merged status has checkmark icon."""
        assert STATUS_ICONS["merged"] == "✓"

    def test_closed_icon(self):
        """Closed status has X icon."""
        assert STATUS_ICONS["closed"] == "✗"

    def test_blocked_icon(self):
        """Blocked status has X icon."""
        assert STATUS_ICONS["blocked"] == "✗"


class TestStatusStyles:
    """Tests for STATUS_STYLES dictionary."""

    def test_pending_style(self):
        """Pending status has white style."""
        assert STATUS_STYLES["pending"] == "white"

    def test_in_progress_style(self):
        """In-progress status has bold yellow style."""
        assert STATUS_STYLES["in_progress"] == "bold yellow"

    def test_in_review_style(self):
        """In-review status has bold cyan style."""
        assert STATUS_STYLES["in_review"] == "bold cyan"

    def test_merged_style(self):
        """Merged status has bold green style."""
        assert STATUS_STYLES["merged"] == "bold green"

    def test_closed_style(self):
        """Closed status has dim red style."""
        assert STATUS_STYLES["closed"] == "dim red"

    def test_blocked_style(self):
        """Blocked status has bold red style."""
        assert STATUS_STYLES["blocked"] == "bold red"


class TestStatusBackground:
    """Tests for STATUS_BG dictionary."""

    def test_pending_no_background(self):
        """Pending status has no background."""
        assert STATUS_BG["pending"] == ""

    def test_in_progress_yellow_background(self):
        """In-progress status has subtle yellow background."""
        assert "on" in STATUS_BG["in_progress"]

    def test_in_review_cyan_background(self):
        """In-review status has subtle cyan background."""
        assert "on" in STATUS_BG["in_review"]

    def test_merged_green_background(self):
        """Merged status has subtle green background."""
        assert "on" in STATUS_BG["merged"]

    def test_closed_red_background(self):
        """Closed status has subtle/dim red background."""
        assert "on" in STATUS_BG["closed"]

    def test_blocked_red_background(self):
        """Blocked status has subtle red background."""
        assert "on" in STATUS_BG["blocked"]


class TestAllStatusesCovered:
    """Tests to ensure all expected statuses are covered."""

    EXPECTED_STATUSES = {"pending", "in_progress", "in_review", "merged", "closed", "blocked"}

    def test_icons_cover_all_statuses(self):
        """STATUS_ICONS covers all expected statuses."""
        assert set(STATUS_ICONS.keys()) == self.EXPECTED_STATUSES

    def test_styles_cover_all_statuses(self):
        """STATUS_STYLES covers all expected statuses."""
        assert set(STATUS_STYLES.keys()) == self.EXPECTED_STATUSES

    def test_backgrounds_cover_all_statuses(self):
        """STATUS_BG covers all expected statuses."""
        assert set(STATUS_BG.keys()) == self.EXPECTED_STATUSES
