"""Tests for pane_layout module: layout computation, mobile detection, etc."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core.pane_layout import (
    base_session_name,
    compute_layout,
    is_mobile,
    _layout_node,
    _checksum,
    MOBILE_WIDTH_THRESHOLD,
)


class TestBaseSessionName:
    def test_plain_session(self):
        assert base_session_name("my-project") == "my-project"

    def test_grouped_session(self):
        assert base_session_name("my-project~1") == "my-project"

    def test_grouped_session_high_number(self):
        assert base_session_name("my-project~42") == "my-project"

    def test_multiple_tildes(self):
        # Only the first ~ splits
        assert base_session_name("a~b~c") == "a"


class TestComputeLayout:
    """Test layout string generation for different terminal geometries."""

    def test_empty(self):
        assert compute_layout(0, 200, 50) == ""

    def test_single_pane(self):
        layout = compute_layout(1, 200, 50)
        # Single pane: just dimensions and pane index 0
        assert "200x50,0,0,0" in layout

    def test_two_panes_landscape(self):
        """Landscape terminal (wider than tall) should produce horizontal split."""
        layout = compute_layout(2, 200, 50)
        # Should have { } for horizontal split
        assert "{" in layout
        assert "}" in layout

    def test_two_panes_portrait(self):
        """Portrait terminal (taller than wide) should produce vertical split."""
        layout = compute_layout(2, 80, 120)
        # Should have [ ] for vertical split
        assert "[" in layout
        assert "]" in layout

    def test_two_panes_square(self):
        """Square char grid is physically portrait (chars ~2:1), so vertical split."""
        layout = compute_layout(2, 100, 100)
        assert "[" in layout

    def test_three_panes_landscape(self):
        """Three panes in landscape: first split horizontal, children alternate."""
        layout = compute_layout(3, 200, 50)
        # Top-level horizontal split
        assert "{" in layout

    def test_layout_has_valid_checksum(self):
        """Layout string should start with a 4-hex-digit checksum."""
        layout = compute_layout(2, 200, 50)
        checksum_part = layout.split(",")[0]
        assert len(checksum_part) == 4
        # Should be valid hex
        int(checksum_part, 16)

    def test_layout_dimensions_match(self):
        """The root node dimensions should match the input."""
        layout = compute_layout(2, 200, 50)
        # After checksum, the body starts with WxH,X,Y
        body = layout[5:]  # skip "xxxx,"
        assert body.startswith("200x50,0,0")

    def test_portrait_vs_landscape_differ(self):
        """Same number of panes but different aspect ratios produce different layouts."""
        portrait = compute_layout(2, 80, 120)
        landscape = compute_layout(2, 200, 50)
        assert portrait != landscape

    def test_four_panes_landscape(self):
        """Four panes in a landscape terminal."""
        layout = compute_layout(4, 200, 50)
        # Should have both horizontal and vertical splits
        assert "{" in layout or "[" in layout
        # All 4 pane indices should be present
        for i in range(4):
            assert f",{i}" in layout or layout.endswith(str(i))


class TestChecksum:
    def test_deterministic(self):
        body = "200x50,0,0{99x50,0,0,0,100x50,100,0,1}"
        assert _checksum(body) == _checksum(body)

    def test_different_inputs(self):
        a = _checksum("200x50,0,0,0")
        b = _checksum("80x120,0,0,0")
        assert a != b


class TestIsMobile:
    """Test mobile detection with mocked tmux calls."""

    @patch("pm_core.pane_layout.mobile_flag_path")
    def test_force_mobile_flag(self, mock_flag_path, tmp_path):
        """Force-mobile flag file makes is_mobile True."""
        flag = tmp_path / "test.mobile"
        flag.touch()
        mock_flag_path.return_value = flag
        assert is_mobile("test-session") is True

    @patch("pm_core.tmux.get_window_size")
    @patch("pm_core.pane_layout.mobile_flag_path")
    def test_narrow_terminal(self, mock_flag_path, mock_size, tmp_path):
        """Terminal narrower than threshold is mobile."""
        mock_flag_path.return_value = tmp_path / "nonexistent.mobile"
        mock_size.return_value = (80, 24)
        assert is_mobile("test-session") is True

    @patch("pm_core.tmux.get_window_size")
    @patch("pm_core.pane_layout.mobile_flag_path")
    def test_wide_terminal(self, mock_flag_path, mock_size, tmp_path):
        """Terminal wider than threshold is not mobile."""
        mock_flag_path.return_value = tmp_path / "nonexistent.mobile"
        mock_size.return_value = (200, 50)
        assert is_mobile("test-session") is False

    @patch("pm_core.tmux.get_window_size")
    @patch("pm_core.pane_layout.mobile_flag_path")
    def test_exact_threshold(self, mock_flag_path, mock_size, tmp_path):
        """Terminal at exact threshold is not mobile (threshold is exclusive)."""
        mock_flag_path.return_value = tmp_path / "nonexistent.mobile"
        mock_size.return_value = (MOBILE_WIDTH_THRESHOLD, 50)
        assert is_mobile("test-session") is False

    @patch("pm_core.tmux.get_window_size")
    @patch("pm_core.pane_layout.mobile_flag_path")
    def test_zero_width(self, mock_flag_path, mock_size, tmp_path):
        """Zero width (no client) is not mobile."""
        mock_flag_path.return_value = tmp_path / "nonexistent.mobile"
        mock_size.return_value = (0, 0)
        assert is_mobile("test-session") is False


class TestLayoutSplitDirection:
    """Verify that layout correctly chooses horizontal vs vertical splits
    based on aspect ratio — the core of the grouped-session fix."""

    def test_landscape_first_split_is_horizontal(self):
        """In landscape (200x50), first split should be horizontal { }."""
        body = _layout_node([0, 1], 0, 0, 200, 50)
        # Horizontal splits use { }
        assert body.startswith("200x50,0,0{")

    def test_portrait_first_split_is_vertical(self):
        """In portrait (80x120), first split should be vertical [ ]."""
        body = _layout_node([0, 1], 0, 0, 80, 120)
        # Vertical splits use [ ]
        assert body.startswith("80x120,0,0[")

    def test_equal_dimensions_uses_vertical(self):
        """When w == h in chars, physically portrait (chars ~2:1), so vertical."""
        body = _layout_node([0, 1], 0, 0, 100, 100)
        assert body.startswith("100x100,0,0[")

    def test_physically_landscape(self):
        """Physically landscape (w >= h*2) should use horizontal."""
        body = _layout_node([0, 1], 0, 0, 200, 50)
        assert body.startswith("200x50,0,0{")

    def test_boundary_landscape(self):
        """At exact boundary (w == h*2), horizontal split."""
        body = _layout_node([0, 1], 0, 0, 200, 100)
        assert body.startswith("200x100,0,0{")

    def test_just_below_boundary_is_vertical(self):
        """Just below boundary (w < h*2), vertical split."""
        body = _layout_node([0, 1], 0, 0, 199, 100)
        assert body.startswith("199x100,0,0[")

    def test_slightly_portrait(self):
        """Even slightly taller than wide should use vertical."""
        body = _layout_node([0, 1], 0, 0, 100, 101)
        assert body.startswith("100x101,0,0[")
