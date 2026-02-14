"""Tests for pane deduplication logic in pm_core.pane_layout."""

import json
from unittest.mock import patch

import pytest

from pm_core import pane_layout


@pytest.fixture
def tmp_registry_dir(tmp_path):
    """Redirect pane registry to a temp directory."""
    reg_dir = tmp_path / "pane-registry"
    reg_dir.mkdir()
    with patch.object(pane_layout, "registry_dir", return_value=reg_dir):
        yield reg_dir


@pytest.fixture
def session_with_panes(tmp_registry_dir):
    """Set up a registry with two panes (tui + guide) and mock tmux live panes."""
    session = "test-session"
    data = {
        "session": session,
        "window": "0",
        "panes": [
            {"id": "%0", "role": "tui", "order": 0, "cmd": "pm tui"},
            {"id": "%1", "role": "guide", "order": 1, "cmd": "pm guide"},
        ],
        "user_modified": False,
    }
    path = tmp_registry_dir / f"{session}.json"
    path.write_text(json.dumps(data))
    return session, data


class TestFindLivePaneByRole:
    """Core dedup function: find a live pane with a given role."""

    def test_returns_pane_id_when_alive(self, session_with_panes):
        session, _ = session_with_panes
        live = [("%0", 0), ("%1", 1)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            assert pane_layout.find_live_pane_by_role(session, "guide") == "%1"

    def test_returns_none_when_dead(self, session_with_panes):
        session, _ = session_with_panes
        # Only %0 alive — %1 (guide) is dead
        live = [("%0", 0)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            assert pane_layout.find_live_pane_by_role(session, "guide") is None

    def test_returns_none_when_role_not_in_registry(self, session_with_panes):
        session, _ = session_with_panes
        live = [("%0", 0), ("%1", 1)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            assert pane_layout.find_live_pane_by_role(session, "notes") is None

    def test_returns_none_when_registry_empty(self, tmp_registry_dir):
        session = "empty-session"
        with patch("pm_core.tmux.get_pane_indices", return_value=[]):
            assert pane_layout.find_live_pane_by_role(session, "guide") is None

    def test_returns_none_when_no_live_panes(self, session_with_panes):
        session, _ = session_with_panes
        with patch("pm_core.tmux.get_pane_indices", return_value=[]):
            assert pane_layout.find_live_pane_by_role(session, "guide") is None

    def test_finds_first_matching_role(self, tmp_registry_dir):
        """If two panes have the same role (shouldn't happen), returns the first alive one."""
        session = "dup-role"
        data = {
            "session": session,
            "window": "0",
            "panes": [
                {"id": "%0", "role": "guide", "order": 0, "cmd": "pm guide"},
                {"id": "%1", "role": "guide", "order": 1, "cmd": "pm guide"},
            ],
            "user_modified": False,
        }
        (tmp_registry_dir / f"{session}.json").write_text(json.dumps(data))
        live = [("%0", 0), ("%1", 1)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            assert pane_layout.find_live_pane_by_role(session, "guide") == "%0"


class TestRegisterPane:
    def test_adds_pane_to_empty_registry(self, tmp_registry_dir):
        session = "test-session"
        pane_layout.register_pane(session, "0", "%5", "notes", "pm notes")
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 1
        assert data["panes"][0]["id"] == "%5"
        assert data["panes"][0]["role"] == "notes"
        assert data["panes"][0]["order"] == 0

    def test_increments_order(self, session_with_panes):
        session, _ = session_with_panes
        pane_layout.register_pane(session, "0", "%5", "notes", "pm notes")
        data = pane_layout.load_registry(session)
        notes_pane = [p for p in data["panes"] if p["role"] == "notes"][0]
        assert notes_pane["order"] == 2  # max was 1, so next is 2

    def test_allows_duplicate_roles(self, session_with_panes):
        """register_pane does NOT check for duplicates — that's _launch_pane's job."""
        session, _ = session_with_panes
        pane_layout.register_pane(session, "0", "%5", "guide", "pm guide")
        data = pane_layout.load_registry(session)
        guide_panes = [p for p in data["panes"] if p["role"] == "guide"]
        assert len(guide_panes) == 2


class TestUnregisterPane:
    def test_removes_pane(self, session_with_panes):
        session, _ = session_with_panes
        pane_layout.unregister_pane(session, "%1")
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 1
        assert data["panes"][0]["id"] == "%0"

    def test_noop_for_unknown_pane(self, session_with_panes):
        session, _ = session_with_panes
        pane_layout.unregister_pane(session, "%99")
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 2  # unchanged


class TestReconcileRegistry:
    def test_removes_dead_panes(self, session_with_panes):
        session, _ = session_with_panes
        # Only %0 alive
        live = [("%0", 0)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            removed = pane_layout._reconcile_registry(session, "0")
        assert removed == ["%1"]
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 1

    def test_keeps_all_alive_panes(self, session_with_panes):
        session, _ = session_with_panes
        live = [("%0", 0), ("%1", 1)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            removed = pane_layout._reconcile_registry(session, "0")
        assert removed == []
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 2

    def test_skips_wipe_when_no_live_panes(self, session_with_panes):
        """Don't wipe registry if tmux returns zero panes (window may not exist)."""
        session, _ = session_with_panes
        with patch("pm_core.tmux.get_pane_indices", return_value=[]):
            removed = pane_layout._reconcile_registry(session, "0")
        assert removed == []
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 2  # preserved


class TestLoadSaveRegistry:
    def test_returns_default_when_no_file(self, tmp_registry_dir):
        data = pane_layout.load_registry("nonexistent")
        assert data["panes"] == []
        assert data["session"] == "nonexistent"

    def test_round_trip(self, tmp_registry_dir):
        session = "test"
        pane_layout.register_pane(session, "0", "%0", "tui", "pm tui")
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 1
        assert data["panes"][0]["role"] == "tui"

    def test_handles_corrupted_json(self, tmp_registry_dir):
        path = tmp_registry_dir / "bad.json"
        path.write_text("not json {{{")
        data = pane_layout.load_registry("bad")
        assert data["panes"] == []


class TestBaseSessionName:
    def test_strips_grouped_suffix(self):
        assert pane_layout.base_session_name("pm~1") == "pm"
        assert pane_layout.base_session_name("pm~42") == "pm"

    def test_no_suffix(self):
        assert pane_layout.base_session_name("pm") == "pm"

    def test_grouped_session_uses_base_registry(self, tmp_registry_dir):
        """Grouped sessions (pm~1) should share the base session's registry."""
        pane_layout.register_pane("pm", "0", "%0", "tui", "pm tui")
        # Loading from grouped session should find the same data
        data = pane_layout.load_registry("pm~1")
        assert len(data["panes"]) == 1
        assert data["panes"][0]["role"] == "tui"


class TestDedupIntegration:
    """End-to-end scenarios that verify dedup prevents duplicate panes."""

    def test_second_launch_finds_existing(self, session_with_panes):
        """Simulates pressing 'g' twice — second time should find existing guide."""
        session, _ = session_with_panes
        live = [("%0", 0), ("%1", 1)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            # First check: guide exists and is alive
            result = pane_layout.find_live_pane_by_role(session, "guide")
            assert result == "%1"
            # This means _launch_pane would focus instead of creating a new pane

    def test_relaunch_after_pane_dies(self, session_with_panes):
        """Guide pane dies, unregister it, then check allows re-launch."""
        session, _ = session_with_panes

        # Guide dies — unregister it
        pane_layout.unregister_pane(session, "%1")

        # Now only %0 is alive
        live = [("%0", 0)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            result = pane_layout.find_live_pane_by_role(session, "guide")
            assert result is None  # allows re-launch

    def test_stale_registry_entry_detected(self, session_with_panes):
        """Registry says guide is %1 but tmux says %1 is dead."""
        session, _ = session_with_panes
        # %1 not in live panes
        live = [("%0", 0)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            result = pane_layout.find_live_pane_by_role(session, "guide")
            assert result is None

    def test_reconcile_then_find(self, session_with_panes):
        """Reconcile cleans dead panes, then find correctly returns None."""
        session, _ = session_with_panes
        live = [("%0", 0)]
        with patch("pm_core.tmux.get_pane_indices", return_value=live):
            pane_layout._reconcile_registry(session, "0")
            result = pane_layout.find_live_pane_by_role(session, "guide")
            assert result is None
        data = pane_layout.load_registry(session)
        assert len(data["panes"]) == 1
