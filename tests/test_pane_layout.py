"""Tests for pane_layout module: layout computation, mobile detection, etc."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.pane_layout import (
    base_session_name,
    compute_layout,
    is_mobile,
    _layout_node,
    _checksum,
    _get_window_data,
    _iter_all_panes,
    load_registry,
    save_registry,
    register_pane,
    unregister_pane,
    _reconcile_registry,
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


# --- Multi-window registry tests ---

@pytest.fixture
def mock_registry(tmp_path):
    """Patch registry_path to use a temp directory."""
    def _reg_path(session):
        return tmp_path / f"{session}.json"
    with patch("pm_core.pane_layout.registry_path", side_effect=_reg_path):
        yield tmp_path


class TestMultiWindowRegistry:
    """Test multi-window pane registry data model."""

    def test_old_format_migration(self, mock_registry):
        """Old single-window format is auto-migrated on load."""
        old_data = {
            "session": "pm-test",
            "window": "@30",
            "panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "tui"}],
            "user_modified": False,
            "generation": "12345",
        }
        (mock_registry / "pm-test.json").write_text(json.dumps(old_data))

        data = load_registry("pm-test")
        # Should have migrated to windows dict
        assert "windows" in data
        assert "panes" not in data
        assert "window" not in data
        assert "user_modified" not in data
        # Panes should be under the window key
        assert "@30" in data["windows"]
        assert data["windows"]["@30"]["panes"] == [
            {"id": "%1", "role": "tui", "order": 0, "cmd": "tui"}
        ]
        assert data["windows"]["@30"]["user_modified"] is False
        # Generation stays top-level
        assert data["generation"] == "12345"

    def test_new_format_loads_unchanged(self, mock_registry):
        """New multi-window format loads cleanly."""
        new_data = {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "tui"}],
                        "user_modified": False},
            },
            "generation": "12345",
        }
        (mock_registry / "pm-test.json").write_text(json.dumps(new_data))

        data = load_registry("pm-test")
        assert data == new_data

    def test_empty_registry(self, mock_registry):
        """Missing registry file returns empty windows dict."""
        data = load_registry("pm-nonexistent")
        assert data["windows"] == {}
        assert data["generation"] == ""

    def test_register_pane_different_windows(self, mock_registry):
        """Registering panes in different windows creates separate entries."""
        save_registry("pm-test", {
            "session": "pm-test", "windows": {}, "generation": "1",
        })

        register_pane("pm-test", "@30", "%1", "tui", "tui")
        register_pane("pm-test", "@38", "%5", "review-claude", "claude")

        data = load_registry("pm-test")
        assert len(data["windows"]) == 2
        assert len(data["windows"]["@30"]["panes"]) == 1
        assert len(data["windows"]["@38"]["panes"]) == 1
        assert data["windows"]["@30"]["panes"][0]["id"] == "%1"
        assert data["windows"]["@38"]["panes"][0]["id"] == "%5"

    def test_unregister_pane_finds_across_windows(self, mock_registry):
        """Unregister searches all windows for the pane."""
        save_registry("pm-test", {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "tui"}],
                        "user_modified": False},
                "@38": {"panes": [{"id": "%5", "role": "review", "order": 0, "cmd": "r"}],
                        "user_modified": False},
            },
            "generation": "1",
        })

        unregister_pane("pm-test", "%5")
        data = load_registry("pm-test")
        # Window @38 should have no panes (but entry still exists)
        assert data["windows"]["@38"]["panes"] == []
        # Window @30 untouched
        assert len(data["windows"]["@30"]["panes"]) == 1

    @patch("pm_core.tmux.get_pane_indices")
    def test_reconcile_one_window_doesnt_affect_other(self, mock_panes, mock_registry):
        """Reconciling window @30 doesn't touch window @38."""
        save_registry("pm-test", {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [
                    {"id": "%1", "role": "tui", "order": 0, "cmd": "tui"},
                    {"id": "%2", "role": "editor", "order": 1, "cmd": "vim"},
                ], "user_modified": False},
                "@38": {"panes": [
                    {"id": "%5", "role": "review", "order": 0, "cmd": "r"},
                ], "user_modified": False},
            },
            "generation": "1",
        })

        # Only %1 is alive in @30, %2 is dead
        mock_panes.return_value = [("%1", 0)]
        removed = _reconcile_registry("pm-test", "@30")
        assert removed == ["%2"]

        data = load_registry("pm-test")
        # @30 lost %2
        assert len(data["windows"]["@30"]["panes"]) == 1
        assert data["windows"]["@30"]["panes"][0]["id"] == "%1"
        # @38 untouched
        assert len(data["windows"]["@38"]["panes"]) == 1

    @patch("pm_core.tmux.get_pane_indices")
    def test_empty_window_removed_after_reconcile(self, mock_panes, mock_registry):
        """Window entry is removed when all its panes die."""
        save_registry("pm-test", {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [
                    {"id": "%1", "role": "tui", "order": 0, "cmd": "tui"},
                ], "user_modified": False},
                "@38": {"panes": [
                    {"id": "%5", "role": "review", "order": 0, "cmd": "r"},
                ], "user_modified": False},
            },
            "generation": "1",
        })

        # All panes dead in @38 — but return empty means window may not exist
        # so we need at least one live pane to trigger cleanup logic.
        # Actually: if no live panes AND registry has panes, reconcile skips.
        # So simulate: %5 is dead but tmux returns other panes
        mock_panes.return_value = [("%99", 0)]  # some other pane, not %5
        removed = _reconcile_registry("pm-test", "@38")
        assert removed == ["%5"]

        data = load_registry("pm-test")
        assert "@38" not in data["windows"]
        assert "@30" in data["windows"]

    def test_per_window_user_modified_isolation(self, mock_registry):
        """user_modified is per-window, not global."""
        save_registry("pm-test", {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "tui"}],
                        "user_modified": True},
                "@38": {"panes": [{"id": "%5", "role": "review", "order": 0, "cmd": "r"}],
                        "user_modified": False},
            },
            "generation": "1",
        })

        data = load_registry("pm-test")
        assert data["windows"]["@30"]["user_modified"] is True
        assert data["windows"]["@38"]["user_modified"] is False

    def test_get_window_data_creates_if_absent(self, mock_registry):
        """_get_window_data creates a new entry for unknown windows."""
        data = {"session": "pm-test", "windows": {}, "generation": "1"}
        wdata = _get_window_data(data, "@99")
        assert wdata == {"panes": [], "user_modified": False}
        assert "@99" in data["windows"]

    def test_iter_all_panes(self, mock_registry):
        """_iter_all_panes yields panes from all windows."""
        data = {
            "windows": {
                "@30": {"panes": [{"id": "%1", "role": "tui"}]},
                "@38": {"panes": [{"id": "%5", "role": "review"}, {"id": "%6", "role": "diff"}]},
            }
        }
        result = list(_iter_all_panes(data))
        assert len(result) == 3
        ids = {p["id"] for _, p in result}
        assert ids == {"%1", "%5", "%6"}


class TestHealRegistry:
    """Test _heal_registry corruption recovery scenarios."""

    @patch("pm_core.tmux.get_pane_indices")
    def test_old_format_with_review_window(self, mock_panes, mock_registry):
        """Old format with wrong window pointer (from review window) gets healed."""
        # Simulate: old format where window drifted to review window
        old_data = {
            "session": "pm-test",
            "window": "@38",  # wrong — should be @30
            "panes": [
                {"id": "%1", "role": "tui", "order": 0, "cmd": "tui"},
                {"id": "%5", "role": "review-claude", "order": 1, "cmd": "claude"},
            ],
            "user_modified": False,
            "generation": "12345",
        }
        (mock_registry / "pm-test.json").write_text(json.dumps(old_data))

        # load_registry migrates to new format: panes go under @38
        data = load_registry("pm-test")
        assert "@38" in data["windows"]
        assert "panes" not in data

    @patch("pm_core.tmux.get_pane_indices")
    def test_dead_panes_removed(self, mock_panes, mock_registry):
        """Dead panes are removed during reconciliation."""
        save_registry("pm-test", {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [
                    {"id": "%1", "role": "tui", "order": 0, "cmd": "tui"},
                    {"id": "%2", "role": "editor", "order": 1, "cmd": "vim"},
                    {"id": "%3", "role": "shell", "order": 2, "cmd": "bash"},
                ], "user_modified": False},
            },
            "generation": "1",
        })

        # Only %1 alive
        mock_panes.return_value = [("%1", 0)]
        removed = _reconcile_registry("pm-test", "@30")
        assert set(removed) == {"%2", "%3"}

        data = load_registry("pm-test")
        assert len(data["windows"]["@30"]["panes"]) == 1
        assert data["windows"]["@30"]["panes"][0]["id"] == "%1"

    @patch("pm_core.tmux.get_pane_indices")
    def test_dead_window_cleaned_up(self, mock_panes, mock_registry):
        """Window with all dead panes is removed (if tmux returns other panes)."""
        save_registry("pm-test", {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "tui"}],
                        "user_modified": False},
                "@38": {"panes": [{"id": "%5", "role": "review", "order": 0, "cmd": "r"}],
                        "user_modified": False},
            },
            "generation": "1",
        })

        # @38's window has a live pane, but it's not %5
        mock_panes.return_value = [("%99", 0)]
        _reconcile_registry("pm-test", "@38")

        data = load_registry("pm-test")
        assert "@38" not in data["windows"]
        assert "@30" in data["windows"]

    @patch("pm_core.tmux.get_pane_indices")
    def test_already_correct_is_noop(self, mock_panes, mock_registry):
        """Correct registry is not modified."""
        original = {
            "session": "pm-test",
            "windows": {
                "@30": {"panes": [
                    {"id": "%1", "role": "tui", "order": 0, "cmd": "tui"},
                    {"id": "%2", "role": "editor", "order": 1, "cmd": "vim"},
                ], "user_modified": False},
            },
            "generation": "1",
        }
        save_registry("pm-test", original)

        # Both panes alive
        mock_panes.return_value = [("%1", 0), ("%2", 1)]
        removed = _reconcile_registry("pm-test", "@30")
        assert removed == []

        data = load_registry("pm-test")
        assert len(data["windows"]["@30"]["panes"]) == 2
