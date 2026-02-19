"""Tests for pane registry I/O functions in pm_core.pane_registry."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core.pane_registry import (
    load_registry,
    save_registry,
    register_pane,
    unregister_pane,
    find_live_pane_by_role,
)


@pytest.fixture
def registry_dir(tmp_path):
    """Patch registry_dir to use a tmp directory, return that directory."""
    with patch("pm_core.pane_registry.registry_dir", return_value=tmp_path):
        yield tmp_path


class TestLoadRegistry:
    def test_missing_file_returns_default(self, registry_dir):
        data = load_registry("test-session")
        assert data["session"] == "test-session"
        assert data["window"] == "0"
        assert data["panes"] == []
        assert data["user_modified"] is False

    def test_loads_existing_file(self, registry_dir):
        registry_file = registry_dir / "test-session.json"
        content = {
            "session": "test-session",
            "window": "1",
            "panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "pm _tui"}],
            "user_modified": False,
        }
        registry_file.write_text(json.dumps(content))
        data = load_registry("test-session")
        assert data["window"] == "1"
        assert len(data["panes"]) == 1
        assert data["panes"][0]["id"] == "%1"

    def test_corrupted_json_returns_default(self, registry_dir):
        registry_file = registry_dir / "test-session.json"
        registry_file.write_text("not valid json {{{")
        data = load_registry("test-session")
        assert data["session"] == "test-session"
        assert data["panes"] == []

    def test_grouped_session_uses_base_name(self, registry_dir):
        registry_file = registry_dir / "test-session.json"
        content = {
            "session": "test-session",
            "window": "0",
            "panes": [{"id": "%5", "role": "claude", "order": 0, "cmd": "claude"}],
            "user_modified": False,
        }
        registry_file.write_text(json.dumps(content))
        # Loading with grouped session name should find the base session file
        data = load_registry("test-session~2")
        assert len(data["panes"]) == 1
        assert data["panes"][0]["id"] == "%5"


class TestSaveRegistry:
    def test_creates_file(self, registry_dir):
        data = {"session": "my-session", "window": "0", "panes": [], "user_modified": False}
        save_registry("my-session", data)
        file_path = registry_dir / "my-session.json"
        assert file_path.exists()
        saved = json.loads(file_path.read_text())
        assert saved == data

    def test_overwrites_existing(self, registry_dir):
        data1 = {"session": "s", "window": "0", "panes": [], "user_modified": False}
        save_registry("s", data1)
        data2 = {"session": "s", "window": "1", "panes": [{"id": "%1"}], "user_modified": True}
        save_registry("s", data2)
        saved = json.loads((registry_dir / "s.json").read_text())
        assert saved["window"] == "1"
        assert len(saved["panes"]) == 1


class TestLoadSaveRoundTrip:
    def test_round_trip(self, registry_dir):
        data = {
            "session": "rt-session",
            "window": "2",
            "panes": [
                {"id": "%10", "role": "tui", "order": 0, "cmd": "pm _tui"},
                {"id": "%11", "role": "claude", "order": 1, "cmd": "claude"},
            ],
            "user_modified": False,
        }
        save_registry("rt-session", data)
        loaded = load_registry("rt-session")
        assert loaded == data

    def test_round_trip_empty_panes(self, registry_dir):
        data = {"session": "empty", "window": "0", "panes": [], "user_modified": False}
        save_registry("empty", data)
        loaded = load_registry("empty")
        assert loaded == data


class TestRegisterPane:
    def test_registers_first_pane(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        data = load_registry("sess")
        assert len(data["panes"]) == 1
        pane = data["panes"][0]
        assert pane["id"] == "%1"
        assert pane["role"] == "tui"
        assert pane["order"] == 0
        assert pane["cmd"] == "pm _tui"

    def test_registers_second_pane_increments_order(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "0", "%2", "claude", "claude")
        data = load_registry("sess")
        assert len(data["panes"]) == 2
        assert data["panes"][0]["order"] == 0
        assert data["panes"][1]["order"] == 1

    def test_updates_window(self, registry_dir):
        register_pane("sess", "3", "%1", "tui", "pm _tui")
        data = load_registry("sess")
        assert data["window"] == "3"

    def test_registers_multiple_panes(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "0", "%2", "claude", "claude")
        register_pane("sess", "0", "%3", "notes", "pm notes")
        data = load_registry("sess")
        assert len(data["panes"]) == 3
        roles = [p["role"] for p in data["panes"]]
        assert roles == ["tui", "claude", "notes"]


class TestUnregisterPane:
    def test_removes_existing_pane(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "0", "%2", "claude", "claude")
        unregister_pane("sess", "%1")
        data = load_registry("sess")
        assert len(data["panes"]) == 1
        assert data["panes"][0]["id"] == "%2"

    def test_noop_for_nonexistent_pane(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        unregister_pane("sess", "%99")
        data = load_registry("sess")
        assert len(data["panes"]) == 1

    def test_removes_all_panes(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        unregister_pane("sess", "%1")
        data = load_registry("sess")
        assert len(data["panes"]) == 0


class TestFindLivePaneByRole:
    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_returns_pane_id_when_alive(self, mock_indices, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "window": "0",
            "panes": [
                {"id": "%1", "role": "tui"},
                {"id": "%2", "role": "claude"},
            ],
        }
        mock_indices.return_value = [("%1", 0), ("%2", 1)]
        result = find_live_pane_by_role("sess", "claude")
        assert result == "%2"

    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_returns_none_when_dead(self, mock_indices, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "window": "0",
            "panes": [{"id": "%1", "role": "tui"}],
        }
        # Pane %1 not in live panes
        mock_indices.return_value = [("%5", 0)]
        result = find_live_pane_by_role("sess", "tui")
        assert result is None

    @patch("pm_core.pane_registry.load_registry")
    def test_returns_none_when_role_not_in_registry(self, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "window": "0",
            "panes": [{"id": "%1", "role": "tui"}],
        }
        result = find_live_pane_by_role("sess", "nonexistent")
        assert result is None

    @patch("pm_core.pane_registry.load_registry")
    def test_returns_none_when_no_panes(self, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "window": "0",
            "panes": [],
        }
        result = find_live_pane_by_role("sess", "tui")
        assert result is None
